"""
Standalone import/reachability graph test — no server required.
Run: python test_import_graph.py

Tests against sample_multiapp_project, which is set up to exercise BOTH
scenarios the spec cares about:
  1. admin/.../dashboard.css .btn-primary   vs   customer/.../dashboard.css
     .btn-primary — same class name, but each is ONLY imported by its own
     app's Dashboard.jsx. Expect: NOT the same reaching-application set
     (isolated candidate).
  2. shared/common.css .container — imported by BOTH admin/src/App.jsx and
     customer/src/App.jsx. Expect: reachable from BOTH "admin" and
     "customer" (real cross-app interaction evidence).
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph

PROJECT = "sample_multiapp_project"

if __name__ == "__main__":
    scan_result = scan_project(PROJECT, job_id="local-test")
    codebase_map = build_codebase_map(scan_result)

    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, PROJECT)

    graph = build_reachability_graph(codebase_map, jsx_results)

    for app in graph.applications:
        print(f"\n[{app.application_name}]  method={app.reachability_method}")
        print(f"  entry_points_used: {app.entry_points_used}")
        print(f"  reachable_jsx_files: {app.reachable_jsx_files}")
        print(f"  reachable_css_files: {app.reachable_css_files}")
        if app.unresolved_imports:
            print(f"  unresolved_imports: {app.unresolved_imports}")

    print(f"\ncss_reachable_from:")
    for css_path, apps in sorted(graph.css_reachable_from.items()):
        print(f"  {css_path}: {apps}")

    print(f"\nunreached_css_files: {graph.unreached_css_files}")

    if graph.warnings:
        print("\nWarnings:")
        for w in graph.warnings:
            print(f"  ! {w}")

    # Sanity assertions matching the two scenarios described above.
    admin_css = graph.css_reachable_from.get("admin/src/components/Dashboard/dashboard.css", [])
    customer_css = graph.css_reachable_from.get("customer/src/components/Dashboard/dashboard.css", [])
    shared_css = graph.css_reachable_from.get("shared/common.css", [])

    print("\n--- Scenario checks ---")
    print(f"admin dashboard.css reachable from: {admin_css}  (expect ONLY ['admin'])")
    print(f"customer dashboard.css reachable from: {customer_css}  (expect ONLY ['customer'])")
    print(f"shared/common.css reachable from: {shared_css}  (expect ['admin', 'customer'])")

    assert admin_css == ["admin"], "admin dashboard.css should be isolated to admin"
    assert customer_css == ["customer"], "customer dashboard.css should be isolated to customer"
    assert shared_css == ["admin", "customer"], "shared/common.css should be reachable from both"
    print("\nAll scenario checks PASSED.")
