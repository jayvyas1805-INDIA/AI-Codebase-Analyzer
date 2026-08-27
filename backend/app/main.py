"""
FastAPI entry point.

/api/scan runs Phases 1-4 (scan -> parse -> relationship model -> issue
detection) and returns immediately — this is all fast, local, deterministic
work. AI explanations are NOT generated here anymore (Phase 5 used to do
this eagerly, one issue at a time, which made big projects painfully slow
to even see results for).

/api/explain/{job_id}/{issue_id} generates the AI explanation for ONE issue,
on demand, called by the frontend when the user actually clicks into that
issue. Results are cached in memory per job, so re-clicking an already-
explained issue is instant.

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
from .chat import continue_chat
from .job_cache import save_job, get_job
from .models import FullAnalysisResult, Issue, ChatRequest, ChatResponse, ChatMessage

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

    # Cache everything this job needs for on-demand explanation later.
    save_job(job_id, issues, css_results, jsx_results)

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


@app.post("/api/explain/{job_id}/{issue_id}", response_model=Issue)
def explain_issue_endpoint(job_id: str, issue_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    if issue.ai_explanation is not None:
        return issue  # already generated earlier — instant, no LLM call

    if job.collection is None:
        try:
            job.collection = build_context_collection(job.css_results, job.jsx_results)
        except Exception:
            job.collection = None  # explain_issue() handles collection=None gracefully

    result = explain_issue(issue, job.collection)
    issue.ai_explanation = result["explanation"]
    issue.ai_recommendation = result["recommendation"]
    return issue


@app.post("/api/chat/{job_id}/{issue_id}", response_model=ChatResponse)
def chat_endpoint(job_id: str, issue_id: str, body: ChatRequest):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    if job.collection is None:
        try:
            job.collection = build_context_collection(job.css_results, job.jsx_results)
        except Exception:
            job.collection = None

    history = job.chat_history.setdefault(issue_id, [])
    reply = continue_chat(issue, job.collection, history, body.message)

    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(reply=reply, history=[ChatMessage(**m) for m in history])
