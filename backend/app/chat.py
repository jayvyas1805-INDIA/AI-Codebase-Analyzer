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
from .rag import _build_query, _format_context
from .vector_store import retrieve_context

CHAT_SYSTEM_PROMPT = (
    "You are a senior frontend engineer helping a developer understand ONE "
    "specific static-analysis finding about CSS class usage in their React "
    "codebase. Only use the ISSUE CONTEXT below — never invent file names, "
    "class names, or details not present in it. If asked about something "
    "unrelated to this issue, say you can only discuss this specific issue. "
    "Be concise."
)


def continue_chat(
    issue: Issue, collection, history: List[Dict[str, str]], user_message: str
) -> str:
    query = _build_query(issue)
    retrieved = retrieve_context(collection, query, top_k=5)
    context = _format_context(issue, retrieved)

    messages = [
        {"role": "system", "content": f"{CHAT_SYSTEM_PROMPT}\n\nISSUE CONTEXT:\n{context}"}
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    return call_ollama_chat_conversation(messages)
