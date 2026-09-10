"""
Thin wrapper around an OpenAI-compatible chat completions API.

Provider-agnostic by design: Groq, OpenAI, Together, Fireworks, or even a
local Ollama instance running its /v1 compatibility layer all speak the
same request/response shape at POST {LLM_BASE_URL}/chat/completions with
an `Authorization: Bearer {LLM_API_KEY}` header. Switching providers is
just an env var change (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY /
LLM_BASE_URL in config.py) — nothing in rag.py, chat.py, or
chat_commands.py needs to change.

IMPORTANT: this file only ever explains/discusses issues. It NEVER
generates a patch, a line number, or a file change — those are computed
deterministically in fix_planner.py/patch_generator.py. See those files'
docstrings for why (spec sections 12/23: never trust generative output
for the actual code change).

Both chat functions fail SOFTLY (return a message) rather than crashing
the whole API request if the provider is unreachable or misconfigured —
analysis and fixing should still work even without an LLM configured.
"""
from typing import List, Optional

import requests

from .config import LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL, OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL


def _chat_completions_request(messages: List[dict]) -> str:
    if not LLM_API_KEY:
        return (
            f"[AI explanation unavailable — LLM_API_KEY is not set for provider "
            f"'{LLM_PROVIDER}'. Set LLM_API_KEY (and LLM_MODEL/LLM_BASE_URL if using "
            f"a non-default provider) as environment variables.]"
        )

    payload = {"model": LLM_MODEL, "messages": messages}
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return (
            f"[AI explanation unavailable — could not connect to {LLM_PROVIDER} at "
            f"{LLM_BASE_URL}. Check LLM_BASE_URL and your network connection.]"
        )
    except requests.exceptions.Timeout:
        return f"[AI explanation timed out contacting {LLM_PROVIDER}.]"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        detail = ""
        try:
            detail = e.response.json().get("error", {}).get("message", "")
        except Exception:
            pass
        return f"[AI explanation failed — {LLM_PROVIDER} returned HTTP {status}: {detail or e}]"
    except (KeyError, IndexError, ValueError):
        return f"[AI explanation failed — unexpected response shape from {LLM_PROVIDER}.]"
    except requests.exceptions.RequestException as e:
        return f"[AI explanation failed: {e}]"


def call_llm_chat(prompt: str, system: Optional[str] = None) -> str:
    """Single-turn helper — used by rag.py's explain_issue()."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _chat_completions_request(messages)


def call_llm_chat_conversation(messages: List[dict]) -> str:
    """
    Multi-turn version, used by chat.py's continue_chat(). The model sees
    the whole conversation, not just the latest message.
    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    """
    return _chat_completions_request(messages)


def call_ollama_embedding(text: str) -> List[float]:
    """
    Embeddings for the OPTIONAL RAG retrieval layer (vector_store.py) —
    kept on a local Ollama instance since Groq/most fast-inference
    providers don't serve embeddings. Raises on failure (unlike the chat
    functions above) — the caller (vector_store.py / main.py) already
    catches this and skips RAG retrieval entirely rather than crashing;
    explanations still work fine off the Phase 4 structured context alone.
    """
    payload = {"model": OLLAMA_EMBED_MODEL, "prompt": text}
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/embeddings", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["embedding"]


# Backward-compatible aliases (old names, in case anything external still
# imports them) — prefer call_llm_chat / call_llm_chat_conversation above.
call_ollama_chat = call_llm_chat
call_ollama_chat_conversation = call_llm_chat_conversation
