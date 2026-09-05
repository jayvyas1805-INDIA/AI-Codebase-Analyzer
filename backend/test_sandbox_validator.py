"""
Standalone sandbox validation test — no server, no Ollama.
Run: python test_sandbox_validator.py

Validates the two real patches from Phase 5 against sample_multiapp_project,
by ACTUALLY applying them to a throwaway sandbox copy and re-running the
full pipeline — never touching the real fixture on disk.

  1. '.panel' fix (rename global.css's copy) -> must PASS: the confirmed
     conflict for '.panel' should be gone, and no new conflict should
     appear anywhere else.
  2. '.card' fix (remove the redundant global.css copy) -> must PASS:
     same expectations.
  3. Sanity check: validating a deliberately BROKEN patch (nonsense file
     path) must FAIL cleanly rather than crash.
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware
from app.job_cache import JobData
from app.fix_planner import plan_fix
from app.patch_generator import generate_patch
from app.sandbox_validator import validate_patch_in_sandbox
from app.models import Patch, PatchFile, PatchFileChange

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
    return JobData(issues, css_results, jsx_results, codebase_map, reachability_graph, scan_result.root_path)


if __name__ == "__main__":
    job = build_job()

    panel_issue = next(i for i in job.issues if i.class_name == "panel" and i.conflict_category == "confirmed_conflict")
    card_issue = next(i for i in job.issues if i.class_name == "card")

    print("=" * 70)
    print("1) Validate the '.panel' rename fix")
    print("=" * 70)
    panel_plan = plan_fix(panel_issue, job)
    panel_patch = generate_patch(panel_issue, panel_plan, job)
    panel_validation = validate_patch_in_sandbox(panel_issue, panel_patch, job)
    print(f"passed: {panel_validation.passed}")
    print(f"original_issue_resolved: {panel_validation.original_issue_resolved}")
    print(f"new_conflicts_introduced: {panel_validation.new_conflicts_introduced}")
    print(f"before_summary: {panel_validation.before_summary}")
    print(f"after_summary: {panel_validation.after_summary}")
    for n in panel_validation.notes:
        print(f"  note: {n}")
    assert panel_validation.passed, "panel fix should pass sandbox validation"
    assert panel_validation.original_issue_resolved
    assert panel_validation.new_conflicts_introduced == 0
    print("PASS\n")

    print("=" * 70)
    print("2) Validate the '.card' consolidate fix")
    print("=" * 70)
    card_plan = plan_fix(card_issue, job)
    card_patch = generate_patch(card_issue, card_plan, job)
    card_validation = validate_patch_in_sandbox(card_issue, card_patch, job)
    print(f"passed: {card_validation.passed}")
    print(f"before_summary: {card_validation.before_summary}")
    print(f"after_summary: {card_validation.after_summary}")
    assert card_validation.passed, "card fix should pass sandbox validation"
    print("PASS\n")

    print("=" * 70)
    print("3) A deliberately broken patch must fail cleanly, not crash")
    print("=" * 70)
    broken_patch = Patch(
        issue_id=panel_issue.id,
        strategy="rename_scoped_class",
        description="broken on purpose",
        files=[
            PatchFile(
                path="admin/src/styles/global.css",
                changes=[PatchFileChange(start_line=9999, end_line=9999, replacement="whatever", original="")],
            )
        ],
    )
    broken_validation = validate_patch_in_sandbox(panel_issue, broken_patch, job)
    print(f"passed: {broken_validation.passed}")
    print(f"notes: {broken_validation.notes}")
    assert broken_validation.passed is False, "an out-of-range patch must fail validation, not crash"
    print("PASS: broken patch failed cleanly instead of crashing.\n")

    print("All Phase 6a sandbox validation checks PASSED.")
