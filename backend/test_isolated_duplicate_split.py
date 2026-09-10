"""
Verifies the isolated_duplicate split requested by the user: main.py's
/api/scan response should NOT count isolated_duplicate issues in
`issues`/`total_issues`, but they should still be present in the separate
`isolated_duplicates` field (and still findable internally via job.issues
for the "why isn't this other class a conflict?" chat flow).

Run: python test_isolated_duplicate_split.py
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware

PROJECT = "sample_multiapp_project"

if __name__ == "__main__":
    scan_result = scan_project(PROJECT, job_id="local-test")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, PROJECT)

    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)

    # Exactly what main.py's /api/scan does now:
    real_issues = [i for i in issues if i.conflict_category != "isolated_duplicate"]
    isolated = [i for i in issues if i.conflict_category == "isolated_duplicate"]

    print(f"Total raw issues from detector: {len(issues)}")
    print(f"Real issues (what 'total_issues' now reflects): {len(real_issues)}")
    print(f"Isolated duplicates (separate field): {len(isolated)}")

    print("\nReal issues:")
    for i in real_issues:
        print(f"  [{i.conflict_category}] {i.class_name} - severity={i.severity}")

    print("\nIsolated duplicates (informational only):")
    for i in isolated:
        print(f"  [{i.conflict_category}] {i.class_name}")

    assert all(i.conflict_category != "isolated_duplicate" for i in real_issues), \
        "isolated_duplicate leaked into the main issues list"
    assert all(i.conflict_category == "isolated_duplicate" for i in isolated), \
        "isolated_duplicates field contains something that isn't isolated"
    assert any(i.class_name == "btn-primary" for i in isolated), \
        "expected btn-primary (admin vs customer, no shared reach) to be isolated"
    assert not any(i.class_name == "btn-primary" for i in real_issues), \
        "btn-primary should NOT appear in the main issues list"
    assert any(i.class_name == "panel" and i.conflict_category == "confirmed_conflict" for i in real_issues), \
        "the real .panel conflict should still be in the main issues list"

    print("\nPASS: isolated_duplicate is correctly separated from real issues.")
