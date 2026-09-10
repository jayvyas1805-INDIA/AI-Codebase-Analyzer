"""
Central place for constants used across the backend.
Keeping these here (instead of scattered in each file) means when you
later want to support .ts/.tsx or change ignored folders, you change one file.
"""
import os
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Ambika Enterprise\OneDrive\Desktop\code analyzer\backend\.env")  # Load environment variables from .env file if present

# Root of the backend project (the "backend/" folder itself)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where extracted/uploaded projects live during analysis
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

# MVP scope: React projects only. No .ts/.tsx/.py/.java etc.
ALLOWED_EXTENSIONS = {".jsx", ".js", ".css"}

# Folders we never want to scan into — huge, irrelevant, or noisy
IGNORED_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    "coverage",
    "__pycache__",
    ".vscode",
    ".idea",
}

# Make sure the workspace folder exists as soon as the app starts
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# ---- LLM settings (Phase 5+) ----
# Provider-agnostic: works with any OpenAI-compatible chat completions API
# (Groq, OpenAI itself, Together, Fireworks, a local Ollama's /v1 endpoint,
# etc.) since they all speak the same request/response shape at
# POST {LLM_BASE_URL}/chat/completions.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")

# Embeddings (used only for the optional RAG retrieval layer in
# vector_store.py) still default to a local Ollama instance, since Groq
# and most fast-inference providers don't serve an embeddings endpoint.
# This is OPTIONAL — if unreachable, main.py already catches the failure
# and RAG retrieval is silently skipped; explanations/chat still work off
# the Phase 4 structured context alone, just without the extra loosely-
# related retrieved chunks. Point OLLAMA_BASE_URL elsewhere (or leave
# Ollama uninstalled) and nothing breaks.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
