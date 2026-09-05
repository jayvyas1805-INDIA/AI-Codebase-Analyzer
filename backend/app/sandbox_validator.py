"""
Sandbox Validation (new phase, consumes patch_generator.py's Patch).

Spec ref: sections 17 (sandbox validation), 18 (validation must respect
application boundaries).

WHY THIS EXISTS
----------------
A patch that "looks right" (valid line ranges, real files, word-bounded
rename) can still be wrong in ways only re-running the actual analyzer
would catch — the new class name could collide with something that
already exists elsewhere, or a rename could accidentally affect a
component nobody intended to touch. This module never trusts a generated
patch on the strength of its own construction logic: it applies the patch
to a THROWAWAY temp copy of the original project (the real upload is
never touched), re-runs the entire deterministic pipeline (scan -> parse
-> relationship model -> codebase map -> reachability graph -> scope-aware
issue detection) from scratch, and compares conflict findings before and
after.

WHAT "PASSED" MEANS
--------------------
1. original_issue_resolved: no confirmed/potential conflict for this
   exact class name remains after the patch.
2. new_conflicts_introduced == 0: no NEW (class_name, category,
   reaching_applications) combination appears for any OTHER class name.
   This is the concrete form of spec section 18's "no unrelated
   application was affected" — if a new conflict signature's reaching
   applications includes an app that had nothing to do with the original
   issue, that's flagged explicitly in unrelated_applications_affected.

Both conditions must hold for `passed=True`. Anything less means the
iterative fix loop (fix_loop.py) should try a different candidate rather
than accept this patch.
"""
import os
import shutil
import tempfile
from typing import List, Set, Tuple

from .scanner import scan_project
from .css_parser import parse_css_file
from .jsx_parser import parse_jsx_files
from .relationship_model import build_relationship_model
from .codebase_mapper import build_codebase_map
from .import_graph import build_reachability_graph
from .issue_detector import detect_issues_scope_aware
from .models import Issue, Patch, ValidationResult

_CONFLICT_CATEGORIES = ("confirmed_conflict", "potential_conflict")


def _apply_patch_to_disk(sandbox_root: str, patch: Patch) -> None:
    for pf in patch.files:
        abs_path = os.path.join(sandbox_root, pf.path)
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Apply bottom-up so earlier line numbers in the same file stay valid.
        for change in sorted(pf.changes, key=lambda c: -c.start_line):
            new_lines = [change.replacement + "\n"] if change.replacement else []
            lines[change.start_line - 1: change.end_line] = new_lines
        with open(abs_path, "w", encoding="utf-8") as f:
            f.writelines(lines)


def _run_full_pipeline(root_path: str) -> List[Issue]:
    """Same sequence as /api/scan in main.py, run against a sandbox copy.
    Uses the batched JSX parser (single Node process for all files) —
    same reasoning as main.py: sandbox validation re-runs the ENTIRE
    pipeline, so a per-file subprocess loop here would make every single
    fix attempt on a large project slow, not just the initial scan."""
    scan_result = scan_project(root_path, job_id="sandbox-validation")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, root_path)
    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    return detect_issues_scope_aware(model, reachability_graph, codebase_map)


def _conflict_signatures(issues: List[Issue]) -> Set[Tuple[str, str, Tuple[str, ...]]]:
    """(class_name, category, sorted reaching_applications) for every
    confirmed/potential conflict — the unit of comparison for before/after."""
    return {
        (i.class_name, i.conflict_category, tuple(sorted(i.reaching_applications)))
        for i in issues
        if i.conflict_category in _CONFLICT_CATEGORIES
    }


def _summary(sigs: Set[Tuple[str, str, Tuple[str, ...]]], total_issues: int) -> dict:
    return {
        "confirmed_conflicts": len([s for s in sigs if s[1] == "confirmed_conflict"]),
        "potential_conflicts": len([s for s in sigs if s[1] == "potential_conflict"]),
        "total_issues": total_issues,
    }


def validate_patch_in_sandbox(issue: Issue, patch: Patch, job) -> ValidationResult:
    if not patch.valid or not patch.files:
        return ValidationResult(
            passed=False,
            original_issue_resolved=False,
            new_conflicts_introduced=0,
            notes=["Patch was not valid or produced no file changes — nothing to sandbox-test."],
        )

    if not job.root_path or not os.path.isdir(job.root_path):
        return ValidationResult(
            passed=False,
            original_issue_resolved=False,
            new_conflicts_introduced=0,
            notes=["Original project source is unavailable for this job — cannot sandbox-validate. "
                   "(Was the job's workspace cleaned up?)"],
        )

    tmp_dir = tempfile.mkdtemp(prefix="ai_codebase_analyzer_sandbox_")
    sandbox_root = os.path.join(tmp_dir, "project")
    try:
        shutil.copytree(job.root_path, sandbox_root)
        _apply_patch_to_disk(sandbox_root, patch)
        after_issues = _run_full_pipeline(sandbox_root)
    except Exception as e:
        return ValidationResult(
            passed=False,
            original_issue_resolved=False,
            new_conflicts_introduced=0,
            notes=[f"Sandbox validation crashed while applying/re-analyzing the patch: {e}"],
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    before_sigs = _conflict_signatures(job.issues)
    after_sigs = _conflict_signatures(after_issues)

    resolved = not any(sig[0] == issue.class_name for sig in after_sigs)

    newly_appeared = after_sigs - before_sigs
    new_sigs_unrelated = {s for s in newly_appeared if s[0] != issue.class_name}
    unrelated_apps = sorted({app for s in new_sigs_unrelated for app in s[2]})

    notes = []
    notes.append(
        f"'.{issue.class_name}' {'no longer' if resolved else 'STILL'} appears as a "
        f"confirmed/potential conflict after the patch."
    )
    if new_sigs_unrelated:
        notes.append(
            f"{len(new_sigs_unrelated)} new conflict signature(s) appeared for OTHER class "
            f"names after the patch: {sorted(new_sigs_unrelated)}"
        )
    else:
        notes.append("No new conflicts appeared for any other class name.")

    return ValidationResult(
        passed=resolved and not new_sigs_unrelated,
        original_issue_resolved=resolved,
        new_conflicts_introduced=len(new_sigs_unrelated),
        unrelated_applications_affected=unrelated_apps,
        before_summary=_summary(before_sigs, len(job.issues)),
        after_summary=_summary(after_sigs, len(after_issues)),
        notes=notes,
    )
