"""
Thin wrapper around a locally-running Ollama server.
API docs: https://github.com/ollama/ollama/blob/main/docs/api.md

Requires, on your machine:
  1. Ollama installed (https://ollama.com) and running (it runs automatically
     after install, or start it with `ollama serve`)
  2. A chat model pulled:      ollama pull llama3.2
  3. An embedding model pulled: ollama pull nomic-embed-text

Both functions fail SOFTLY (return a message / raise a clear error) rather
than crashing the whole API request if Ollama isn't running — analysis
should still work even before you've set up the LLM piece.
"""
from typing import List

import requests

from .config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL


def call_ollama_chat(prompt: str, system: str = None) -> str:
    payload = {"model": OLLAMA_CHAT_MODEL, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system

    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return (
            f"[AI explanation unavailable — could not connect to Ollama at {OLLAMA_BASE_URL}. "
            f"Make sure Ollama is running and the model has been pulled: "
            f"`ollama pull {OLLAMA_CHAT_MODEL}`]"
        )
    except requests.exceptions.RequestException as e:
        return f"[AI explanation failed: {e}]"


def call_ollama_embedding(text: str) -> List[float]:
    """
    Raises on failure (unlike call_ollama_chat) — the caller (vector_store.py)
    decides how to handle that, since a broken embedding call means the whole
    vector index for this request should be skipped, not silently degraded.
    """
    payload = {"model": OLLAMA_EMBED_MODEL, "prompt": text}
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/embeddings", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["embedding"]
