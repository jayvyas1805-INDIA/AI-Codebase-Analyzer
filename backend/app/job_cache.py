"""
Simple in-memory store so /api/explain/{job_id}/{issue_id} can reuse a job's
already-parsed CSS/JSX data (to lazily build the vector store) and update an
issue's ai_explanation in place, without re-parsing or re-scanning anything.

NOTE: this is per-process memory. Fine for local dev with a single uvicorn
worker (the default). It resets on server restart, and won't work if you
later run multiple worker processes — acceptable tradeoff for an MVP.
"""
from typing import Dict, List, Optional

from .models import Issue, CSSFileParseResult, JSXFileParseResult


class JobData:
    def __init__(
        self,
        issues: List[Issue],
        css_results: List[CSSFileParseResult],
        jsx_results: List[JSXFileParseResult],
        codebase_map=None,
        reachability_graph=None,
        root_path: str = None,
    ):
        self.issues = issues
        self.css_results = css_results
        self.jsx_results = jsx_results
        self.codebase_map = codebase_map            # Phase 1 — needed by the AI context builder
        self.reachability_graph = reachability_graph  # Phase 2 — needed by the AI context builder
        self.root_path = root_path                    # Phase 5 — needed to read/patch real source files
        self.collection = None  # built lazily on first /api/explain call for this job
        self.chat_history: Dict[str, List[dict]] = {}  # issue_id -> [{"role", "content"}, ...]
        # Phase 7 — remembers the most recent plan/patch/validation per issue,
        # so chat commands like "Validate the fix." can refer back to
        # whatever "Generate a fix." just produced, within the same session.
        self.last_plan: Dict[str, object] = {}
        self.last_patch: Dict[str, object] = {}
        self.last_validation: Dict[str, object] = {}
        self.last_fix_result: Dict[str, object] = {}


_JOBS: Dict[str, JobData] = {}


def save_job(
    job_id: str,
    issues: List[Issue],
    css_results: List[CSSFileParseResult],
    jsx_results: List[JSXFileParseResult],
    codebase_map=None,
    reachability_graph=None,
    root_path: str = None,
) -> None:
    _JOBS[job_id] = JobData(issues, css_results, jsx_results, codebase_map, reachability_graph, root_path)


def get_job(job_id: str) -> Optional[JobData]:
    return _JOBS.get(job_id)
