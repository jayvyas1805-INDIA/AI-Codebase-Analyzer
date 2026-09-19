"""
Central place for constants used across the backend.
Keeping these here (instead of scattered in each file) means when you
later want to support .ts/.tsx or change ignored folders, you change one file.
"""
import os
from dotenv import load_dotenv

# Root of the backend project (the "backend/" folder itself) — computed
# BEFORE load_dotenv() so the .env lookup itself is portable, unlike a
# hardcoded absolute path (which only works on the machine/folder location
# it was written for).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))  # Load environment variables from .env file if present

# Where extracted/uploaded projects live during analysis
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

# SQLite database persisting scan results across backend restarts (see
# db.py). A file path, not a connection string — swapping to Postgres
# later means replacing db.py's connection logic, not this constant or
# job_cache.py's public save_job()/get_job() API.
DB_PATH = os.path.join(BASE_DIR, "analyzer.db")

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

# ---- API security (Phase D slice 2) ----
# Comma-separated list of allowed frontend origins, e.g.
# "http://localhost:5173,https://myapp.example.com". Defaults to the
# Vite dev server's usual ports so local dev keeps working unmodified —
# but this is a real allowlist now, not "*". Override via env var before
# deploying anywhere other than localhost.
CORS_ALLOWED_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "https://ai-codebase-analyzer-sandy.vercel.app,"
        "https://ai-codebase-analyzer-4iz2lpnt6-23bt04172-6828s-projects.vercel.app,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

# Reject uploads bigger than this before they're even fully written to
# disk (see main.py's streamed size check) — protects against someone
# uploading a multi-GB file and exhausting disk/memory.
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

# Reject a zip whose TOTAL uncompressed content would exceed this, checked
# from the zip's own directory listing BEFORE extracting anything — the
# classic "zip bomb" defense (a tiny compressed file that decompresses to
# gigabytes). See zip_handler.py.
MAX_UNCOMPRESSED_SIZE_MB = int(os.getenv("MAX_UNCOMPRESSED_SIZE_MB", "500"))

# Simple in-memory per-IP rate limiting (see rate_limit.py) — good enough
# for a single-process dev/small-deployment setup; the same multi-worker
# caveat as job_cache.py's in-memory dict applies (state isn't shared
# across worker processes). Two tiers: a looser one for /api/scan (cheap,
# local, no LLM call), a tighter one for anything that calls an LLM
# (explain/chat/fix) since those cost real money per request.
RATE_LIMIT_SCAN_PER_MINUTE = int(os.getenv("RATE_LIMIT_SCAN_PER_MINUTE", "10"))
RATE_LIMIT_LLM_PER_MINUTE = int(os.getenv("RATE_LIMIT_LLM_PER_MINUTE", "20"))