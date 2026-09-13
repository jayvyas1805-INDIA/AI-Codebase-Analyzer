"""
In-memory store (fronting a SQLite-backed persistence layer, see db.py) so
/api/explain/{job_id}/{issue_id} can reuse a job's already-parsed CSS/JSX
data (to lazily build the vector store) and update an issue's
ai_explanation in place, without re-parsing or re-scanning anything.

PERSISTENCE (see db.py's docstring for the full rationale): save_job()
writes through to SQLite, and get_job() falls back to loading from SQLite
on a cache miss — so a backend restart no longer forces a full re-scan,
just a rebuild of THIS in-memory dict from what's already in the DB. The
in-memory dict is still the source of truth for chat_history / last_plan /
last_patch / last_validation / last_fix_result / ai_explanation / the
vector store `collection` — none of that is persisted (v1 scope, see
db.py). Losing those on restart is expected: they're cheap to regenerate
(one LLM call or one deterministic fix-plan computation), unlike the full
scan this module now protects against having to redo.
"""
from typing import Dict, List, Optional

from . import db
from .models import Issue, CSSFileParseResult, JSXFileParseResult

db.init_db()


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
    db.persist_scan(job_id, root_path, issues, css_results, jsx_results, codebase_map, reachability_graph)


def get_job(job_id: str) -> Optional[JobData]:
    if job_id in _JOBS:
        return _JOBS[job_id]

    # Cache miss — either a bad job_id, or a backend restart since this
    # job was scanned. Try SQLite before giving up.
    persisted = db.load_scan(job_id)
    if persisted is None:
        return None

    job = JobData(
        persisted.issues, persisted.css_results, persisted.jsx_results,
        persisted.codebase_map, persisted.reachability_graph, persisted.root_path,
    )
    _JOBS[job_id] = job  # repopulate the in-memory cache so this only happens once per job per process
    return job