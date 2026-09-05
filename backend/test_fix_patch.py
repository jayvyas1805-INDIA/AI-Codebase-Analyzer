"""
Standalone fix planner + patch generator test — no server, no Ollama.
Run: python test_fix_patch.py

Exercises all three plannability paths on sample_multiapp_project:
  1. '.btn-primary' (isolated_duplicate) -> MUST be refused (plannable=False),
     per the spec's own guardrail against touching isolated styles.
  2. '.panel' (confirmed_conflict, admin-only) -> rename_scoped_class,
     choosing global.css (0 known usages) over dashboard.css (1 usage) —
     the smaller blast radius — and produces a patch renaming just that
     one CSS line, with zero JSX changes needed.
  3. '.card' (duplicate_definition, admin-only, identical properties) ->
     consolidate_duplicate, keeping dashboard.css (used) and removing the
     redundant rule from global.css (unused), patch deletes that block.

For every generated patch, the change is actually applied (to a throwaway
copy of the fixture, never the real one) and the resulting file is printed,
so you can see the real before/after — not just the line-diff structure.
"""
import shutil
import tempfile

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

PROJECT = "sample_multiapp_project"


def build_job(project_path):
    scan_result = scan_project(project_path, job_id="local-test")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, project_path)
    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)
    return JobData(issues, css_results, jsx_results, codebase_map, reachability_graph, scan_result.root_path)


def apply_patch_to_copy(patch, project_path):
    """Applies the patch to a throwaway temp copy and prints the result."""
    tmp_dir = tempfile.mkdtemp()
    copy_path = f"{tmp_dir}/project"
    shutil.copytree(project_path, copy_path)

    for pf in patch.files:
        abs_path = f"{copy_path}/{pf.path}"
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Apply changes bottom-up so earlier line numbers stay valid.
        for change in sorted(pf.changes, key=lambda c: -c.start_line):
            new_lines = [change.replacement + "\n"] if change.replacement else []
            lines[change.start_line - 1: change.end_line] = new_lines
        with open(abs_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"\n  --- {pf.path} (after patch) ---")
        with open(abs_path, "r", encoding="utf-8") as f:
            print("  " + f.read().replace("\n", "\n  "))

    shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    job = build_job(PROJECT)

    btn_issue = next(i for i in job.issues if i.class_name == "btn-primary")
    panel_issue = next(i for i in job.issues if i.class_name == "panel" and i.conflict_category == "confirmed_conflict")
    card_issue = next(i for i in job.issues if i.class_name == "card")

    print("=" * 70)
    print("1) '.btn-primary' (isolated_duplicate) — must be REFUSED")
    print("=" * 70)
    btn_plan = plan_fix(btn_issue, job)
    print(f"plannable={btn_plan.plannable}")
    print(f"reason: {btn_plan.reason_if_not_plannable}")
    assert btn_plan.plannable is False, "isolated_duplicate must never be plannable"
    print("PASS: isolated_duplicate correctly refused.\n")

    print("=" * 70)
    print("2) '.panel' (confirmed_conflict) — rename_scoped_class")
    print("=" * 70)
    panel_plan = plan_fix(panel_issue, job)
    print(f"chosen_strategy: {panel_plan.chosen_strategy}")
    print(f"target_file: {panel_plan.target_file}")
    print(f"blast_radius: {panel_plan.blast_radius}")
    print(f"risk: {panel_plan.risk}")
    print(f"rationale: {panel_plan.rationale}")
    for o in panel_plan.options_considered:
        print(f"  option: {o.strategy} on {o.affected_files[0]} -> blast_radius={o.blast_radius}, risk={o.risk}")

    assert panel_plan.target_file == "admin/src/styles/global.css", (
        f"expected global.css (0 usages) to be the rename target, got {panel_plan.target_file}"
    )
    assert panel_plan.blast_radius == 0
    print("PASS: chose global.css (0 usages) over dashboard.css (1 usage).\n")

    panel_patch = generate_patch(panel_issue, panel_plan, job)
    print(f"patch valid: {panel_patch.valid}  (errors: {panel_patch.validation_errors})")
    print(f"patch description: {panel_patch.description}")
    for pf in panel_patch.files:
        print(f"  file: {pf.path}")
        for c in pf.changes:
            print(f"    line {c.start_line}: '{c.original}'  ->  '{c.replacement}'")
    assert panel_patch.valid
    assert len(panel_patch.files) == 1, "renaming a 0-blast-radius file should touch only the CSS file, no JSX"
    apply_patch_to_copy(panel_patch, PROJECT)
    print("PASS: patch is valid and touches only the CSS definition.\n")

    print("=" * 70)
    print("3) '.card' (duplicate_definition) — consolidate_duplicate")
    print("=" * 70)
    card_plan = plan_fix(card_issue, job)
    print(f"chosen_strategy: {card_plan.chosen_strategy}")
    print(f"target_file: {card_plan.target_file}")
    print(f"rationale: {card_plan.rationale}")
    assert card_plan.chosen_strategy == "consolidate_duplicate"
    assert card_plan.target_file == "admin/src/styles/global.css", (
        f"expected the UNUSED global.css copy to be removed, got {card_plan.target_file}"
    )
    print("PASS: chose to remove the unused copy in global.css, keeping the used one in dashboard.css.\n")

    card_patch = generate_patch(card_issue, card_plan, job)
    print(f"patch valid: {card_patch.valid}")
    for pf in card_patch.files:
        for c in pf.changes:
            print(f"  {pf.path} lines {c.start_line}-{c.end_line} removed:\n    {c.original!r}")
    assert card_patch.valid
    apply_patch_to_copy(card_patch, PROJECT)
    print("PASS: redundant rule removed cleanly.\n")

    print("=" * 70)
    print("All Phase 5 checks PASSED.")
    print("=" * 70)
