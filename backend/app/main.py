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
import threading

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .zip_handler import create_job_workspace, safe_extract_zip
from .scanner import scan_project
from .codebase_mapper import build_codebase_map
from .import_graph import build_reachability_graph
from .css_parser import parse_css_file
from .jsx_parser import parse_jsx_files
from .relationship_model import build_relationship_model
from .issue_detector import detect_issues_scope_aware
from .vector_store import build_context_collection
from .rag import explain_issue
from .chat import continue_chat
from .chat_commands import handle_chat_message
from .fix_planner import plan_fix
from .patch_generator import generate_patch
from .sandbox_validator import validate_patch_in_sandbox
from .fix_loop import attempt_validated_fix, attempt_validated_fix_all
from .fix_apply import build_fixed_project_zip, build_bulk_fixed_project_zip
from .job_cache import save_job, get_job
from .rate_limit import rate_limit_scan, rate_limit_llm
from .config import CORS_ALLOWED_ORIGINS, MAX_UPLOAD_SIZE_MB
from .models import FullAnalysisResult, Issue, ChatRequest, ChatResponse, ChatMessage, FixPlan, Patch, ValidationResult, FixResult, BulkFixResult, BulkFixProgress

app = FastAPI(title="React Codebase Analyzer")

# Real allowlist, not "*" — see config.py's CORS_ALLOWED_ORIGINS. Defaults
# to the Vite dev server's usual ports, so local dev is unaffected; set
# the CORS_ALLOWED_ORIGINS env var before deploying anywhere else.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "analyzer"}


@app.post("/api/scan", response_model=FullAnalysisResult)
async def scan_upload(
    file: UploadFile = File(...),
    include_low: bool = False,
    _rl: None = Depends(rate_limit_scan),
):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")

    job_id, job_dir = create_job_workspace()
    zip_path = os.path.join(job_dir, "upload.zip")

    # Stream to disk in chunks and abort as soon as the size cap is
    # crossed, rather than buffering the whole file first and checking
    # after — the whole point of a size limit is to bound how much gets
    # written/held in memory in the first place.
    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    written = 0
    with open(zip_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                f.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the {MAX_UPLOAD_SIZE_MB} MB limit.",
                )
            f.write(chunk)

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

    # Batched into a single Node process call for the whole project — see
    # jsx_parser.py's docstring for why per-file subprocess calls used to
    # dominate scan time on large projects.
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, source_root)
    jsx_parse_errors = []
    for result in jsx_results:
        jsx_parse_errors.extend(f"{result.file_path}: {e}" for e in result.parse_errors)

    model = build_relationship_model(css_results, jsx_results)

    # Phase 1: figure out which application each file belongs to.
    codebase_map = build_codebase_map(scan_result)

    # Phase 2: given that map, walk the actual import graph from each
    # application's entry point to see which CSS files it can really reach.
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)

    # Phase 3: classify conflicts using that reachability evidence instead
    # of name-only matching — same class name in 2+ files is now only a
    # candidate, not proof, per the spec's core design principle.
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map, jsx_results)

    # Cache everything this job needs for on-demand explanation later.
    # NOTE: job.issues keeps the FULL combined list (including isolated
    # duplicates) — chat/explain/fix all look issues up by id, and the
    # "why isn't this other class a conflict?" chat flow specifically
    # needs isolated_duplicate issues to still be findable internally,
    # even though they're excluded from the main response below.
    save_job(job_id, issues, css_results, jsx_results, codebase_map, reachability_graph, scan_result.root_path)

    # Split isolated_duplicate out of the main issues list/count — it's
    # not a problem, it's the analyzer's proof that a same-named class
    # ISN'T one. Keeping it mixed into "issues"/"total_issues" made real
    # findings harder to see and made severity counts misleading.
    real_issues = [i for i in issues if i.conflict_category != "isolated_duplicate"]
    isolated = [i for i in issues if i.conflict_category == "isolated_duplicate"]

    # Low-severity findings are real, not noise to throw away — but they're
    # noisy to LOOK at by default, so they're split out of `issues`/
    # `total_issues` the same way isolated_duplicate is above, unless the
    # caller explicitly opts in with include_low=true. Either way, job.issues
    # (cached via save_job above, BEFORE this split) still holds the full,
    # unfiltered list — so /api/explain and /api/chat can still look up a
    # low-severity issue by id even when it's hidden from this response.
    if include_low:
        low_severity: list = []
    else:
        low_severity = [i for i in real_issues if i.severity == "low"]
        real_issues = [i for i in real_issues if i.severity != "low"]

    return FullAnalysisResult(
        job_id=job_id,
        total_css_files_parsed=len(css_results),
        total_jsx_files_parsed=len(jsx_results),
        project_has_dynamic_classnames=model.project_has_dynamic_classnames,
        css_parse_errors=css_parse_errors,
        jsx_parse_errors=jsx_parse_errors,
        issues=real_issues,
        total_issues=len(real_issues),
        isolated_duplicates=isolated,
        low_severity_issues=low_severity,
        codebase_map=codebase_map,
        reachability_graph=reachability_graph,
    )


@app.post("/api/explain/{job_id}/{issue_id}", response_model=Issue)
def explain_issue_endpoint(job_id: str, issue_id: str, _rl: None = Depends(rate_limit_llm)):
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

    result = explain_issue(issue, job, job.collection)
    issue.ai_explanation = result["explanation"]
    issue.ai_recommendation = result["recommendation"]
    return issue


@app.post("/api/chat/{job_id}/{issue_id}", response_model=ChatResponse)
def chat_endpoint(job_id: str, issue_id: str, body: ChatRequest, _rl: None = Depends(rate_limit_llm)):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    history = job.chat_history.setdefault(issue_id, [])

    # Phase 7: try the deterministic command router first (spec section 21
    # — "Generate a fix.", "Validate the fix.", "Fix it.", etc. must run
    # REAL backend logic, never an LLM's guess at what a patch contains).
    # Only genuinely open-ended questions fall through to continue_chat().
    command_reply = handle_chat_message(issue, job, body.message)
    if command_reply is not None:
        reply = command_reply
    else:
        if job.collection is None:
            try:
                job.collection = build_context_collection(job.css_results, job.jsx_results)
            except Exception:
                job.collection = None
        reply = continue_chat(issue, job, job.collection, history, body.message)

    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": reply})

    return ChatResponse(reply=reply, history=[ChatMessage(**m) for m in history])


@app.post("/api/plan-fix/{job_id}/{issue_id}", response_model=FixPlan)
def plan_fix_endpoint(job_id: str, issue_id: str, _rl: None = Depends(rate_limit_scan)):
    """
    Phase 5 (spec section 14): deterministic fix plan for one issue —
    which strategy, which file gets changed, and why (blast radius).
    Never touches isolated_duplicate findings; see fix_planner.py.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    return plan_fix(issue, job)


@app.post("/api/generate-patch/{job_id}/{issue_id}", response_model=Patch)
def generate_patch_endpoint(job_id: str, issue_id: str, _rl: None = Depends(rate_limit_llm)):
    """
    Phase 5 (spec section 16): line-level patch for one issue, computed
    from the fix plan above. Never applied automatically — the frontend
    shows the diff and the user must explicitly approve it (spec section
    24: "require explicit user approval before applying a validated patch").

    Rate-limited on the LLM tier: for rename_scoped_class fixes, this
    calls ai_rename_suggester.py to propose a descriptive class name —
    see that module for why an LLM is involved here specifically, and why
    it's safe (the suggestion is validated/deduplicated, never trusted as
    a raw file edit).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    plan = plan_fix(issue, job)
    return generate_patch(issue, plan, job)


@app.post("/api/validate-patch/{job_id}/{issue_id}", response_model=ValidationResult)
def validate_patch_endpoint(job_id: str, issue_id: str, _rl: None = Depends(rate_limit_scan)):
    """
    Phase 6 (spec section 17): apply the current plan's patch to a
    throwaway sandbox copy, re-run the full analyzer, and report whether
    the original issue actually resolved with no new conflicts elsewhere.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    plan = plan_fix(issue, job)
    patch = generate_patch(issue, plan, job)
    return validate_patch_in_sandbox(issue, patch, job)


@app.post("/api/fix/{job_id}/{issue_id}", response_model=FixResult)
def fix_endpoint(job_id: str, issue_id: str, _rl: None = Depends(rate_limit_llm)):
    """
    Phase 6 (spec section 19): the full iterative loop — plan, patch,
    validate; on failure, retry with the next-cheapest candidate, up to 3
    attempts total. Never applies anything to the real project; the
    frontend must still get explicit user approval before doing that
    (spec section 24).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    result = attempt_validated_fix(issue, job)

    # Cache the result on the job (same convention chat_commands.py's
    # "Fix it" handler already uses) so a follow-up call to
    # /api/fix/{job_id}/{issue_id}/download doesn't have to redo the
    # plan-patch-validate loop from scratch.
    job.last_fix_result[issue_id] = result
    if result.attempts:
        job.last_patch[issue_id] = result.attempts[-1].patch
        job.last_validation[issue_id] = result.attempts[-1].validation

    return result


@app.post("/api/fix/{job_id}/{issue_id}/download")
def download_fixed_project(job_id: str, issue_id: str, _rl: None = Depends(rate_limit_llm)):
    """
    Packages the project as a downloadable .zip with the validated fix for
    `issue_id` actually applied to the files on disk.

    This is the one place in the API that produces real file changes the
    user can keep — everywhere else (/api/fix, /api/validate-patch, chat)
    only ever plans/previews/sandbox-tests a fix, per spec section 24
    ("never applies anything to the real project without explicit user
    approval"). Calling THIS endpoint (e.g. clicking a "Download fixed
    project" button, after reviewing the fix) is that approval.

    If /api/fix hasn't been called yet for this issue (so there's no
    cached job.last_fix_result to reuse), this runs the full
    plan-patch-validate loop itself first — so this endpoint always
    "just works" standalone, even if the fix step's own response never
    handed back a zip.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    issue = next((i for i in job.issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found for this job.")

    fix_result = job.last_fix_result.get(issue_id)
    if fix_result is None:
        fix_result = attempt_validated_fix(issue, job)
        job.last_fix_result[issue_id] = fix_result
        if fix_result.attempts:
            job.last_patch[issue_id] = fix_result.attempts[-1].patch
            job.last_validation[issue_id] = fix_result.attempts[-1].validation

    if not fix_result.success or not fix_result.attempts:
        raise HTTPException(
            status_code=422,
            detail=f"No validated fix is available to package for download: {fix_result.final_message}",
        )

    patch = fix_result.attempts[-1].patch
    try:
        zip_path = build_fixed_project_zip(job, patch, issue_id, job_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"fixed_project_{issue_id}.zip",
    )


@app.post("/api/fix-all/{job_id}", response_model=BulkFixResult)
def fix_all_endpoint(job_id: str, _rl: None = Depends(rate_limit_llm)):
    """
    Runs the full plan -> patch -> sandbox-validate loop for EVERY issue
    in the job in one call (in parallel — see fix_loop.py's
    attempt_validated_fix_all), instead of requiring one manual "Fix"
    click per issue — the point when a project surfaces hundreds of
    findings. This call BLOCKS until every issue is done; for a project
    with a lot of issues, prefer /api/fix-all/{job_id}/start +
    /api/fix-all/{job_id}/progress instead, so the frontend can show
    live progress rather than one long silent wait.

    Nothing is applied to the real project here either (same "explicit
    approval before real changes" rule as /api/fix) — this only plans,
    patches, and sandbox-validates every issue and reports which ones got
    a validated fix. Call /api/fix-all/{job_id}/download afterwards (or
    directly — it runs this loop itself if it hasn't run yet) to get a
    single .zip with every successful fix actually applied.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    result = attempt_validated_fix_all(job, job_id)
    job.last_bulk_fix_result = result
    return result


@app.post("/api/fix-all/{job_id}/start", response_model=BulkFixProgress)
def fix_all_start_endpoint(job_id: str, _rl: None = Depends(rate_limit_llm)):
    """
    Kicks off the same bulk fix loop as POST /api/fix-all/{job_id}, but in
    a background thread, and returns immediately with "status": "running"
    instead of blocking until every issue is done. Poll
    GET /api/fix-all/{job_id}/progress afterwards for live counts.

    If a bulk run is already in progress for this job, returns its
    current progress instead of starting a second one — only one bulk fix
    runs per job at a time, so two "Fix all" clicks in a row (or a page
    refresh + re-click) can't spawn overlapping runs.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    if job.bulk_fix_progress["status"] == "running":
        return BulkFixProgress(**job.bulk_fix_progress)

    job.bulk_fix_progress.update(
        {
            "status": "running",
            "total": len(job.issues),
            "processed": 0,
            "fixed": 0,
            "failed": 0,
            "skipped": 0,
            "error": None,
        }
    )

    def _run_in_background():
        try:
            result = attempt_validated_fix_all(job, job_id, progress=job.bulk_fix_progress)
            job.last_bulk_fix_result = result
            job.bulk_fix_progress["status"] = "done"
        except Exception as e:
            # A crash here must still leave the job in a state the
            # frontend can show and recover from, not a stuck spinner.
            job.bulk_fix_progress["status"] = "error"
            job.bulk_fix_progress["error"] = str(e)

    threading.Thread(target=_run_in_background, daemon=True).start()

    return BulkFixProgress(**job.bulk_fix_progress)


@app.get("/api/fix-all/{job_id}/progress", response_model=BulkFixProgress)
def fix_all_progress_endpoint(job_id: str):
    """
    Polled by the frontend (every ~1s while a bulk fix is running) to
    show live progress instead of a single opaque wait. Once "status" is
    "done", the full BulkFixResult is included as "result" so the
    frontend doesn't need a separate call to get the final breakdown.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    payload = dict(job.bulk_fix_progress)
    if payload.get("status") == "done" and job.last_bulk_fix_result is not None:
        payload["result"] = job.last_bulk_fix_result
    return BulkFixProgress(**payload)


@app.post("/api/fix-all/{job_id}/download")
def download_all_fixed_project(job_id: str, _rl: None = Depends(rate_limit_llm)):
    """
    Packages the project as a downloadable .zip with EVERY issue that got
    a validated fix applied at once, in a single pass over the original
    source (see fix_apply.build_bulk_fixed_project_zip for how changes
    from different issues' patches are safely combined file-by-file).

    If /api/fix-all hasn't been called yet for this job, this runs the
    full bulk fix loop itself first, so it always works standalone.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found. Jobs only live in memory — re-upload and re-scan if the server restarted.",
        )

    bulk_result = job.last_bulk_fix_result
    if bulk_result is None:
        bulk_result = attempt_validated_fix_all(job, job_id)
        job.last_bulk_fix_result = bulk_result

    successful_patches = [
        job.last_patch[r.issue_id]
        for r in bulk_result.results
        if r.success and r.issue_id in job.last_patch
    ]
    if not successful_patches:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No issues were successfully auto-fixed, so there's nothing to download. "
                f"({bulk_result.fixed_count} fixed, {bulk_result.failed_count} failed, "
                f"{bulk_result.skipped_count} not auto-fixable, out of {bulk_result.total_issues} total.)"
            ),
        )

    try:
        zip_path, conflicts = build_bulk_fixed_project_zip(job, successful_patches, job_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    headers = {"X-Fixed-Count": str(len(successful_patches))}
    if conflicts:
        # Surfaced as a header rather than failing the download outright —
        # everything else in the zip still applied cleanly; only the
        # specific overlapping lines listed here were skipped.
        headers["X-Fix-Conflicts"] = str(len(conflicts))

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"fixed_project_all_{job_id}.zip",
        headers=headers,
    )