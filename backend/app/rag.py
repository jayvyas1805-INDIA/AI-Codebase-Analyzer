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
from .llm_client import call_llm_chat
from .vector_store import retrieve_context
from .ai_context_builder import build_issue_context, CONTEXT_GUARDRAIL

SYSTEM_PROMPT = (
    "You are a senior frontend engineer explaining static analysis findings "
    "about CSS class usage in a React codebase, including cross-application "
    "scope and reachability analysis. Be concise and practical.\n\n"
    f"{CONTEXT_GUARDRAIL}"
)


def _build_query(issue: Issue) -> str:
    return f"{issue.issue_type} involving CSS class '{issue.class_name}': {issue.message}"


def explain_issue(issue: Issue, job, collection) -> dict:
    """
    Returns {"explanation": str, "recommendation": str}.
    Asks the LLM for two clearly delimited sections and splits them apart.
    If the model doesn't follow the format (small local models sometimes
    don't), the whole response is used as the explanation and the
    recommendation is left empty rather than guessing.

    `job` is job_cache.JobData — carries the codebase map / reachability
    graph the Phase 4 context builder needs. `collection` (the RAG vector
    store) is still consulted for extra loosely-related chunks, but the
    issue's own structured context always comes first and is never
    dropped, per spec section 12.
    """
    query = _build_query(issue)
    retrieved = retrieve_context(collection, query, top_k=5)
    context = build_issue_context(issue, job)
    if retrieved:
        context += "\n\n=== ADDITIONAL RETRIEVED CONTEXT (loosely related, lower priority) ===\n"
        context += "\n".join(f"- {chunk}" for chunk in retrieved)

    prompt = (
        f"{context}\n\n"
        "Using ONLY the information above, respond in EXACTLY this format "
        "(keep each section under 120 words):\n\n"
        "EXPLANATION:\n"
        "<what the issue is, why it happens, which component(s)/application(s) "
        "are affected, and — if another definition of this class exists "
        "elsewhere in the project — why it either is or isn't part of this finding>\n\n"
        "RECOMMENDATION:\n"
        "<a concrete, actionable fix, or \"No action needed\" if this is an isolated duplicate>"
    )

    raw = call_llm_chat(prompt, system=SYSTEM_PROMPT)
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
