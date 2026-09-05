"""
Standalone scope-aware conflict detection test — no server required.
Run: python test_scope_aware_conflicts.py

Exercises the full new pipeline against sample_multiapp_project and checks
three scenarios explicitly:

  1. '.btn-primary' — defined once in admin's dashboard.css, once in
     customer's dashboard.css. Each is ONLY reachable from its own app.
     Expect: classified as ISOLATED DUPLICATE, not a conflict.

  2. '.panel' — defined in admin/src/styles/global.css AND
     admin/src/components/Dashboard/dashboard.css, both reachable from
     the SAME app (admin), with every shared property (padding, color)
     disagreeing, and confirmed JSX usage (Dashboard.jsx uses
     className="panel"). Expect: CONFIRMED CONFLICT.

  3. Also confirms the single-app fixture (sample_project) still runs
     through the scope-aware path without crashing (no package.json means
     everything falls into one application, so nothing should ever be
     isolated there — same behavior as before, just via the new code path).
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware


def run_pipeline(project_path):
    scan_result = scan_project(project_path, job_id="local-test")

    css_results = [
        parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files
    ]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, project_path)

    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)
    return issues


if __name__ == "__main__":
    print("=" * 60)
    print("Multi-app fixture: sample_multiapp_project")
    print("=" * 60)
    issues = run_pipeline("sample_multiapp_project")

    for issue in issues:
        print(f"\n[{issue.class_name}]  category={issue.conflict_category}  "
              f"type={issue.issue_type}  severity={issue.severity}  confidence={issue.confidence}")
        print(f"  reaching_applications: {issue.reaching_applications}")
        print(f"  message: {issue.message}")

    btn_primary_issues = [i for i in issues if i.class_name == "btn-primary"]
    panel_issues = [i for i in issues if i.class_name == "panel"]

    print("\n--- Scenario checks ---")
    assert len(btn_primary_issues) == 1, f"expected 1 issue for btn-primary, got {len(btn_primary_issues)}"
    assert btn_primary_issues[0].conflict_category == "isolated_duplicate", (
        f"btn-primary should be isolated_duplicate, got {btn_primary_issues[0].conflict_category}"
    )
    print("btn-primary correctly classified as isolated_duplicate (NOT a conflict). PASS")

    assert len(panel_issues) == 1, f"expected 1 issue for panel, got {len(panel_issues)}"
    assert panel_issues[0].conflict_category == "confirmed_conflict", (
        f"panel should be confirmed_conflict, got {panel_issues[0].conflict_category}"
    )
    assert panel_issues[0].reaching_applications == ["admin"], (
        f"panel should be scoped to admin only, got {panel_issues[0].reaching_applications}"
    )
    print("panel correctly classified as confirmed_conflict, scoped to ['admin']. PASS")

    print("\n" + "=" * 60)
    print("Single-app fixture regression check: sample_project")
    print("=" * 60)
    regression_issues = run_pipeline("sample_project")
    print(f"{len(regression_issues)} issues found, no crash. PASS")
    for issue in regression_issues:
        print(f"  [{issue.class_name}] {issue.issue_type} / {issue.conflict_category}")

    print("\nAll checks PASSED.")
