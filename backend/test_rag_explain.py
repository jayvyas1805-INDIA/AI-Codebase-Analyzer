"""
Standalone RAG + LLM explanation test.
Requires Ollama running locally with the models pulled (see README).
If Ollama isn't running, this still runs — you'll see graceful
"AI explanation unavailable" messages instead of a crash.

Run: python test_rag_explain.py
"""
import os
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_file
from app.relationship_model import build_relationship_model
from app.issue_detector import detect_issues
from app.vector_store import build_context_collection
from app.rag import explain_issue

PROJECT_ROOT_ABS = os.path.abspath("sample_project")

if __name__ == "__main__":
    scan_result = scan_project(PROJECT_ROOT_ABS, job_id="local-test")

    css_results = [
        parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files
    ]
    jsx_results = [
        parse_jsx_file(f.absolute_path, f.relative_path, PROJECT_ROOT_ABS)
        for f in scan_result.jsx_files + scan_result.js_files
    ]

    model = build_relationship_model(css_results, jsx_results)
    issues = detect_issues(model)

    try:
        collection = build_context_collection(css_results, jsx_results)
        print("Vector store built successfully (Ollama embeddings reachable).\n")
    except Exception as e:
        collection = None
        print(f"Could not build vector store ({e}). Continuing without RAG context.\n")

    for issue in issues:
        print(f"=== {issue.issue_type}: {issue.class_name} ===")
        result = explain_issue(issue, collection)
        print("EXPLANATION:", result["explanation"])
        print("RECOMMENDATION:", result["recommendation"])
        print()
