"""
Regression test for db.py + job_cache.py persistence.

Runs the save step and the load step as two SEPARATE subprocesses (not
just two function calls in the same test) — the whole point being tested
is "does data survive when the in-memory dict is genuinely gone," and a
single process's dict would still have the data in memory regardless of
whether SQLite worked, silently passing a test that doesn't prove anything.

Run: python test_persistence.py
"""
import os
import subprocess
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyzer.db")
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(DB_PATH + suffix):
        os.remove(DB_PATH + suffix)

SAVE_SCRIPT = """
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware
from app.job_cache import save_job

scan_result = scan_project("sample_project", job_id="persist-test")
css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
jsx_results = parse_jsx_files(jsx_files_to_parse, "sample_project")
model = build_relationship_model(css_results, jsx_results)
codebase_map = build_codebase_map(scan_result)
reachability_graph = build_reachability_graph(codebase_map, jsx_results)
issues = detect_issues_scope_aware(model, reachability_graph, codebase_map, jsx_results)
save_job("persist-test", issues, css_results, jsx_results, codebase_map, reachability_graph, scan_result.root_path)
print(len(issues))
"""

LOAD_SCRIPT = """
from app.job_cache import get_job, _JOBS
assert "persist-test" not in _JOBS, "test invalid: job already in memory in a supposedly fresh process"
job = get_job("persist-test")
assert job is not None, "job not found after simulated restart"
assert job.root_path == "sample_project", job.root_path
assert len(job.css_results) > 0
assert len(job.jsx_results) > 0
assert job.codebase_map is not None
assert job.reachability_graph is not None
print(len(job.issues))
"""

print("=" * 60)
print("Process 1 (save) -> Process 2 (fresh interpreter, load)")
print("=" * 60)

save_result = subprocess.run([sys.executable, "-c", SAVE_SCRIPT], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
assert save_result.returncode == 0, f"save subprocess failed:\n{save_result.stderr}"
saved_count = int(save_result.stdout.strip())
print(f"Process 1 saved {saved_count} issues.")

load_result = subprocess.run([sys.executable, "-c", LOAD_SCRIPT], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
assert load_result.returncode == 0, f"load subprocess failed:\n{load_result.stderr}"
loaded_count = int(load_result.stdout.strip())
print(f"Process 2 (fresh interpreter) recovered {loaded_count} issues.")

assert loaded_count == saved_count, f"issue count mismatch: saved {saved_count}, loaded {loaded_count}"
print()
print("PASS — scan results survive a genuinely separate process (simulated backend restart).")
