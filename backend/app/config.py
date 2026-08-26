"""
Central place for constants used across the backend.
Keeping these here (instead of scattered in each file) means when you
later want to support .ts/.tsx or change ignored folders, you change one file.
"""
import os

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

# ---- Phase 5: Ollama (local open-source LLM) settings ----
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CHAT_MODEL = "llama3.2"        # run: ollama pull llama3.2
OLLAMA_EMBED_MODEL = "nomic-embed-text"  # run: ollama pull nomic-embed-text
