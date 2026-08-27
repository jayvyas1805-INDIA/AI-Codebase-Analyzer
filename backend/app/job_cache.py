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
    ):
        self.issues = issues
        self.css_results = css_results
        self.jsx_results = jsx_results
        self.collection = None  # built lazily on first /api/explain call for this job
        self.chat_history: Dict[str, List[dict]] = {}  # issue_id -> [{"role", "content"}, ...]


_JOBS: Dict[str, JobData] = {}


def save_job(
    job_id: str,
    issues: List[Issue],
    css_results: List[CSSFileParseResult],
    jsx_results: List[JSXFileParseResult],
) -> None:
    _JOBS[job_id] = JobData(issues, css_results, jsx_results)


def get_job(job_id: str) -> Optional[JobData]:
    return _JOBS.get(job_id)
