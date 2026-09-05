"""
Multi-turn AI chat scoped to ONE issue (Phase 7 - optional, per spec).

Each issue gets its own conversation, cached per job in job_cache.py. Every
turn is anchored to the SAME issue context Phase 5 uses for the one-shot
explanation (reusing rag.py's context builder), so the chat can't wander
into inventing facts about files or classes it was never shown.
"""
from typing import Dict, List

from .models import Issue
from .llm_client import call_ollama_chat_conversation
from .rag import _build_query
from .vector_store import retrieve_context
from .ai_context_builder import build_issue_context, CONTEXT_GUARDRAIL

CHAT_SYSTEM_PROMPT = (
    "You are a senior frontend engineer helping a developer understand ONE "
    "specific static-analysis finding about CSS class usage in their React "
    "codebase, including cross-application scope and reachability analysis. "
    "If asked about something unrelated to this issue, say you can only "
    "discuss this specific issue. Be concise.\n\n"
    f"{CONTEXT_GUARDRAIL}"
)


def continue_chat(
    issue: Issue, job, collection, history: List[Dict[str, str]], user_message: str
) -> str:
    query = _build_query(issue)
    retrieved = retrieve_context(collection, query, top_k=5)
    context = build_issue_context(issue, job)
    if retrieved:
        context += "\n\n=== ADDITIONAL RETRIEVED CONTEXT (loosely related, lower priority) ===\n"
        context += "\n".join(f"- {chunk}" for chunk in retrieved)

    messages = [
        {"role": "system", "content": f"{CHAT_SYSTEM_PROMPT}\n\nISSUE CONTEXT:\n{context}"}
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    return call_ollama_chat_conversation(messages)
