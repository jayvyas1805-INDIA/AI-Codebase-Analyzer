"""
Standalone AI context builder test — no server, no Ollama required.
Run: python test_ai_context_builder.py

Builds the full pipeline on sample_multiapp_project, then prints the exact
context package that would be sent to the LLM for two issues:
  - '.panel'       (confirmed_conflict, admin-only)
  - '.btn-primary'  (isolated_duplicate, admin vs customer)

This is the evidence spec section 20's chat example needs: a user asking
"why isn't the OTHER `.btn-primary` a conflict?" should be answerable
purely from this context, with no LLM call at all. The assertions check
that the context actually contains that answer.
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware
from app.job_cache import JobData
from app.ai_context_builder import build_issue_context

PROJECT = "sample_multiapp_project"


def build_job():
    scan_result = scan_project(PROJECT, job_id="local-test")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, PROJECT)
    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)
    return JobData(issues, css_results, jsx_results, codebase_map, reachability_graph)


if __name__ == "__main__":
    job = build_job()

    panel_issue = next(i for i in job.issues if i.class_name == "panel")
    btn_issue = next(i for i in job.issues if i.class_name == "btn-primary")

    print("=" * 70)
    print("CONTEXT FOR '.panel' (confirmed_conflict)")
    print("=" * 70)
    panel_context = build_issue_context(panel_issue, job)
    print(panel_context)

    print("\n" + "=" * 70)
    print("CONTEXT FOR '.btn-primary' (isolated_duplicate)")
    print("=" * 70)
    btn_context = build_issue_context(btn_issue, job)
    print(btn_context)

    print("\n" + "=" * 70)
    print("Assertions")
    print("=" * 70)

    # The isolated_duplicate context must explicitly surface the OTHER
    # definition (customer's) and explain why it's not part of this finding
    # — this is exactly what spec section 20's chat example needs answered.
    assert "customer" in btn_context, "btn-primary context should mention the customer application"
    assert "NOT the same reaching-application set" in btn_context or "no static import evidence" in btn_context or "isolated" in btn_context.lower(), \
        "btn-primary context should explain the isolation reasoning"
    print("btn-primary context surfaces the customer-side definition and isolation reasoning. PASS")

    # The confirmed_conflict context must show BOTH admin files, their
    # shared application, and the actual conflicting declarations.
    assert "admin/src/styles/global.css" in panel_context
    assert "admin/src/components/Dashboard/dashboard.css" in panel_context
    assert "padding" in panel_context and "color" in panel_context
    print("panel context surfaces both conflicting definitions and their declarations. PASS")

    # Analyzer evidence section must be present and match Phase 3's own conclusion.
    assert "conflict_category: confirmed_conflict" in panel_context
    assert "conflict_category: isolated_duplicate" in btn_context
    print("Analyzer evidence sections match Phase 3's classification. PASS")

    print("\nAll checks PASSED.")
