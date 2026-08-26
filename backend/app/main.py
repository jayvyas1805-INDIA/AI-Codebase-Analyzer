"""
FastAPI entry point.

/api/scan now runs the FULL pipeline (Phases 1-4):
  scan -> parse CSS -> parse JSX/JS -> build relationship model -> detect issues
and returns a FullAnalysisResult with all found issues.

Run with: uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/docs for interactive API docs.
"""
import os
import shutil

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .zip_handler import create_job_workspace, safe_extract_zip
from .scanner import scan_project
from .css_parser import parse_css_file
from .jsx_parser import parse_jsx_file
from .relationship_model import build_relationship_model
from .issue_detector import detect_issues
from .vector_store import build_context_collection
from .rag import explain_issue
from .models import FullAnalysisResult

app = FastAPI(title="React Codebase Analyzer")

# Wide open for local dev so the Vite frontend (different port) can call this.
# Tighten allow_origins to your actual frontend URL before deploying anywhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "analyzer"}


@app.post("/api/scan", response_model=FullAnalysisResult)
async def scan_upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")

    job_id, job_dir = create_job_workspace()
    zip_path = os.path.join(job_dir, "upload.zip")

    with open(zip_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        source_root = safe_extract_zip(zip_path, job_dir)
        scan_result = scan_project(source_root, job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    css_parse_errors = []
    css_results = []
    for f in scan_result.css_files:
        result = parse_css_file(f.absolute_path, f.relative_path)
        css_results.append(result)
        css_parse_errors.extend(f"{result.file_path}: {e}" for e in result.parse_errors)

    jsx_parse_errors = []
    jsx_results = []
    for f in scan_result.jsx_files + scan_result.js_files:
        result = parse_jsx_file(f.absolute_path, f.relative_path, source_root)
        jsx_results.append(result)
        jsx_parse_errors.extend(f"{result.file_path}: {e}" for e in result.parse_errors)

    model = build_relationship_model(css_results, jsx_results)
    issues = detect_issues(model)

    # Phase 5: RAG + LLM explanation. Degrades gracefully — if Ollama isn't
    # running yet, issues are still returned, just without ai_explanation.
    try:
        collection = build_context_collection(css_results, jsx_results)
    except Exception:
        collection = None

    for issue in issues:
        issue.ai_explanation = explain_issue(issue, collection)

    return FullAnalysisResult(
        job_id=job_id,
        total_css_files_parsed=len(css_results),
        total_jsx_files_parsed=len(jsx_results),
        project_has_dynamic_classnames=model.project_has_dynamic_classnames,
        css_parse_errors=css_parse_errors,
        jsx_parse_errors=jsx_parse_errors,
        issues=issues,
        total_issues=len(issues),
    )
