"""
SQLite persistence for scan results (Phase D, slice 1: persistence).

WHAT THIS SOLVES
------------------
Uploaded projects already extract to a DURABLE folder
(WORKSPACE_DIR/{job_id}/source/...), not a temp dir — so the actual source
files already survive a backend restart. What didn't survive was the
EXPENSIVE part: the parsed CSS/JSX results, the codebase map, the
reachability graph, and the classified issue list, which previously lived
only in job_cache.py's in-memory dict. A restart meant re-uploading and
re-scanning from scratch even though nothing on disk had changed.

WHAT THIS DOES NOT (YET) SOLVE — DELIBERATE V1 SCOPE
--------------------------------------------------------
Cached AI explanations (issue.ai_explanation), chat history, and the
fix-planner's last_plan/last_patch/last_validation/last_fix_result are
NOT persisted here. Those are mutated in place at ~10 call sites across
main.py and chat_commands.py; wiring persistence into every one of them
is a bigger, separate change. They're also cheap to regenerate (one LLM
call, or one deterministic fix-plan computation) compared to a full
project re-scan, which is the expensive operation this slice targets.
After a restart, a previously-explained issue will just get re-explained
on the next /api/explain call rather than serving a stale cached answer —
a reasonable v1 boundary, not an oversight.

WHY SQLITE VIA STDLIB, NOT AN ORM
------------------------------------
One table, five JSON blob columns, no relations to query — introducing
SQLAlchemy for this would be more ceremony than the problem needs right
now. If this grows into something with real relational queries (e.g.
"find all issues with severity=high across all jobs"), that's the trigger
to introduce an ORM and/or Postgres, not before. Swapping to Postgres
later means replacing THIS module's connection logic — job_cache.py's
public save_job()/get_job() API doesn't change.
"""
import json
import sqlite3
from typing import List, Optional

from .config import DB_PATH
from .models import Issue, CSSFileParseResult, JSXFileParseResult, CodebaseMap, ReachabilityGraph


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")  # safe for uvicorn --reload's file-watcher process churn
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                root_path TEXT NOT NULL,
                issues_json TEXT NOT NULL,
                css_results_json TEXT NOT NULL,
                jsx_results_json TEXT NOT NULL,
                codebase_map_json TEXT,
                reachability_graph_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def persist_scan(
    job_id: str,
    root_path: str,
    issues: List[Issue],
    css_results: List[CSSFileParseResult],
    jsx_results: List[JSXFileParseResult],
    codebase_map: Optional[CodebaseMap],
    reachability_graph: Optional[ReachabilityGraph],
) -> None:
    """Write-through snapshot, called once per scan (see job_cache.save_job).
    Uses INSERT OR REPLACE so re-scanning the same job_id (shouldn't
    normally happen — job_ids are freshly generated per upload — but is
    safe either way) just overwrites the old snapshot."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs
                (job_id, root_path, issues_json, css_results_json, jsx_results_json,
                 codebase_map_json, reachability_graph_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                root_path or "",
                json.dumps([i.model_dump(mode="json") for i in issues]),
                json.dumps([c.model_dump(mode="json") for c in css_results]),
                json.dumps([j.model_dump(mode="json") for j in jsx_results]),
                codebase_map.model_dump_json() if codebase_map else None,
                reachability_graph.model_dump_json() if reachability_graph else None,
            ),
        )


class PersistedScan:
    """Plain container for what load_scan() reconstructs — job_cache.py
    wraps this into a full JobData (with fresh, empty chat_history/
    last_plan/etc.) rather than this module knowing about JobData at all,
    keeping the dependency direction one-way (job_cache imports db, not
    the reverse)."""
    def __init__(self, root_path, issues, css_results, jsx_results, codebase_map, reachability_graph):
        self.root_path = root_path
        self.issues = issues
        self.css_results = css_results
        self.jsx_results = jsx_results
        self.codebase_map = codebase_map
        self.reachability_graph = reachability_graph


def load_scan(job_id: str) -> Optional[PersistedScan]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT root_path, issues_json, css_results_json, jsx_results_json,
                   codebase_map_json, reachability_graph_json
            FROM jobs WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

    if row is None:
        return None

    root_path, issues_json, css_json, jsx_json, map_json, graph_json = row
    return PersistedScan(
        root_path=root_path,
        issues=[Issue.model_validate(d) for d in json.loads(issues_json)],
        css_results=[CSSFileParseResult.model_validate(d) for d in json.loads(css_json)],
        jsx_results=[JSXFileParseResult.model_validate(d) for d in json.loads(jsx_json)],
        codebase_map=CodebaseMap.model_validate_json(map_json) if map_json else None,
        reachability_graph=ReachabilityGraph.model_validate_json(graph_json) if graph_json else None,
    )
