"""
RAG + LLM Explanation (Phase 5b).

For each Issue (already found deterministically by Phase 4 — NOT by the
LLM), this module:
  1. Builds a retrieval query describing the issue
  2. Pulls the most relevant extra context chunks from the vector store
  3. Combines that with the issue's own exact data (always included,
     regardless of retrieval — we never want to lose the ground truth)
  4. Sends it all to the local LLM with instructions to explain using
     ONLY the given context, never inventing details
"""
from .models import Issue
from .llm_client import call_ollama_chat
from .vector_store import retrieve_context

SYSTEM_PROMPT = (
    "You are a senior frontend engineer explaining static analysis findings "
    "about CSS class usage in a React codebase. Only use the CONTEXT provided "
    "below — never invent file names, class names, or details that aren't in "
    "it. Be concise and practical."
)


def _build_query(issue: Issue) -> str:
    return f"{issue.issue_type} involving CSS class '{issue.class_name}': {issue.message}"


def _format_context(issue: Issue, retrieved_chunks) -> str:
    lines = [
        "ISSUE DETECTED BY STATIC ANALYSIS:",
        f"- Type: {issue.issue_type}",
        f"- Severity: {issue.severity}",
        f"- Class: {issue.class_name}",
        f"- Details: {issue.message}",
    ]

    if issue.css_definitions:
        lines.append("\nCSS DEFINITIONS INVOLVED:")
        for d in issue.css_definitions:
            decl_text = "; ".join(f"{x.property}: {x.value}" for x in d.declarations)
            lines.append(f"- {d.file_path}:{d.line_number}  .{issue.class_name} {{ {decl_text} }}")

    if issue.jsx_usages:
        lines.append("\nJSX USAGES INVOLVED:")
        for u in issue.jsx_usages:
            lines.append(f"- {u.file_path}:{u.line_number}  <{u.element}>")

    if retrieved_chunks:
        lines.append("\nADDITIONAL RELATED CONTEXT FROM THE CODEBASE:")
        for chunk in retrieved_chunks:
            lines.append(f"- {chunk}")

    return "\n".join(lines)


def explain_issue(issue: Issue, collection) -> dict:
    """
    Returns {"explanation": str, "recommendation": str}.
    Asks the LLM for two clearly delimited sections and splits them apart.
    If the model doesn't follow the format (small local models sometimes
    don't), the whole response is used as the explanation and the
    recommendation is left empty rather than guessing.
    """
    query = _build_query(issue)
    retrieved = retrieve_context(collection, query, top_k=5)
    context = _format_context(issue, retrieved)

    prompt = (
        f"{context}\n\n"
        "Using ONLY the information above, respond in EXACTLY this format "
        "(keep each section under 100 words):\n\n"
        "EXPLANATION:\n"
        "<what the issue is, why it happens, and which component(s)/file(s) are affected>\n\n"
        "RECOMMENDATION:\n"
        "<a concrete, actionable fix>"
    )

    raw = call_ollama_chat(prompt, system=SYSTEM_PROMPT)
    return _split_explanation_and_recommendation(raw)


def _split_explanation_and_recommendation(raw: str) -> dict:
    explanation, recommendation = raw, ""

    exp_marker = "EXPLANATION:"
    rec_marker = "RECOMMENDATION:"
    exp_idx = raw.upper().find(exp_marker)
    rec_idx = raw.upper().find(rec_marker)

    if exp_idx != -1 and rec_idx != -1 and rec_idx > exp_idx:
        explanation = raw[exp_idx + len(exp_marker): rec_idx].strip()
        recommendation = raw[rec_idx + len(rec_marker):].strip()
    elif rec_idx != -1:
        explanation = raw[:rec_idx].strip()
        recommendation = raw[rec_idx + len(rec_marker):].strip()

    return {"explanation": explanation, "recommendation": recommendation}
