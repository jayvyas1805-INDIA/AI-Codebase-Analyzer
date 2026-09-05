"""
Regression test for the two bugs reported: (1) O(files^2) clustering
blowup on common utility class names in large projects, and (2) real
same-app conflicts getting silently misreported as isolated_duplicate
when import-graph tracing is incomplete (path aliases, etc. — simulated
here by simply never importing the Widget*.jsx files from App.js/index.js).

Run: python generate_big_fixture.py && python test_large_project_regression.py
"""
import time

from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware

PROJECT = "big_fixture_project"

if __name__ == "__main__":
    t0 = time.time()

    scan_result = scan_project(PROJECT, job_id="perf-test")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, PROJECT)
    t_parse = time.time()

    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    t_reach = time.time()

    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)
    t_detect = time.time()

    print(f"Files: {len(css_results)} CSS, {len(jsx_results)} JSX/JS")
    print(f"Parse time:      {t_parse - t0:.3f}s")
    print(f"Reachability:    {t_reach - t_parse:.3f}s")
    print(f"Conflict detect: {t_detect - t_reach:.3f}s")
    print(f"TOTAL:           {t_detect - t0:.3f}s")
    print(f"Total issues found: {len(issues)}")

    # --- Correctness: the real HeaderA/HeaderB conflict must NOT be lost ---
    header_issues = [i for i in issues if i.class_name == "header-bg"]
    print(f"\n'.header-bg' issues found: {[(i.conflict_category, i.severity) for i in header_issues]}")
    assert any(i.conflict_category == "confirmed_conflict" for i in header_issues), (
        "REGRESSION: the real HeaderA/HeaderB conflict was misclassified as isolated "
        "instead of confirmed — reachability fallback is not working."
    )
    print("PASS: real same-app conflict correctly detected as confirmed_conflict, "
          "even though the import graph never traced these files from an entry point.")

    high_severity = [i for i in issues if i.severity == "high"]
    print(f"\nHigh-severity issues: {len(high_severity)} (must be > 0)")
    assert len(high_severity) > 0, "REGRESSION: 0 high-severity issues on a project with a real conflict."
    print("PASS: high-severity issues are non-zero.")

    # --- Speed: this used to be O(n^2) on the 300 '.container' definitions ---
    print(f"\nTotal detection time: {t_detect - t_reach:.3f}s (expect well under 5s even for 300 duplicate files)")
    assert (t_detect - t_reach) < 5.0, (
        f"REGRESSION: conflict detection took {t_detect - t_reach:.3f}s - the O(n^2) "
        f"clustering bug may have come back."
    )
    print("PASS: detection stayed fast despite 300 files sharing one class name.")

    print("\nAll large-project regression checks PASSED.")
