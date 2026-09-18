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


def _incremental_pipeline_is_viable(patch: Patch, job) -> bool:
    """
    Cheap, side-effect-free check for whether _run_incremental_pipeline()
    can safely handle this patch (every file it touches was part of the
    original scan) — used by validate_patch_in_sandbox() BEFORE copying
    anything, purely to decide how much of the project needs to exist on
    disk in the sandbox at all (see _copy_changed_files_only() below).
    _run_incremental_pipeline() re-derives this exact same answer itself
    once it actually runs, so the two can never disagree — this is only
    here so the copy strategy can be chosen up front.
    """
    if job.codebase_map is None:
        return False
    changed_paths = {pf.path for pf in patch.files}
    known_paths = {r.file_path for r in job.css_results} | {r.file_path for r in job.jsx_results}
    return changed_paths.issubset(known_paths)


def _copy_changed_files_only(source_root: str, dest_root: str, relative_paths: Set[str]) -> None:
    """
    The fast-path counterpart to shutil.copytree(): copies ONLY the files
    a patch is about to edit, preserving their relative directory
    structure, instead of the entire project. _apply_patch_to_disk() only
    ever writes to these same paths, and _run_incremental_pipeline() only
    ever reads sandbox files at these same paths (everything else comes
    from job's cached parse results) — so this is all the sandbox needs
    to exist on disk for the fast path. On a large project this avoids by
    far the biggest remaining I/O cost per fix attempt: copying every
    file in the project just to edit one or two of them.
    """
    os.makedirs(dest_root, exist_ok=True)
    for rel_path in relative_paths:
        src = os.path.join(source_root, rel_path)
        dst = os.path.join(dest_root, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def _run_full_pipeline(root_path: str) -> List[Issue]:
    """Same sequence as /api/scan in main.py, run against a sandbox copy.
    Uses the batched JSX parser (single Node process for all files) —
    same reasoning as main.py: sandbox validation re-runs the ENTIRE
    pipeline, so a per-file subprocess loop here would make every single
    fix attempt on a large project slow, not just the initial scan.

    Used only as a defensive fallback now — see
    _run_incremental_pipeline() below, which is what sandbox validation
    actually calls."""
    scan_result = scan_project(root_path, job_id="sandbox-validation")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, root_path)
    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    return detect_issues_scope_aware(model, reachability_graph, codebase_map)


def _run_incremental_pipeline(sandbox_root: str, patch: Patch, job) -> List[Issue]:
    """
    Same end result as _run_full_pipeline(), much cheaper — this is what
    actually makes repeated sandbox validation (up to MAX_ATTEMPTS times
    PER issue, across potentially hundreds of issues in a bulk fix) fast
    enough to matter.

    WHY THIS IS SAFE, NOT JUST FASTER
    -----------------------------------
    A patch only ever edits the CONTENT of existing files — patch_generator.py
    never adds, deletes, or renames a file. That means the sandbox copy is
    byte-identical to job.root_path except for the exact lines patch.files
    changes. So for every file the patch did NOT touch, re-parsing it here
    would reproduce EXACTLY the same CSSFileParseResult/JSXFileParseResult
    already sitting in job.css_results/job.jsx_results from the original
    scan — parsing is a pure function of file content, and that content
    hasn't changed. Re-deriving an identical answer at real cost (JSX
    parsing spawns a Node subprocess — the single most expensive step in
    the whole pipeline) is pure waste, not extra safety.

    So this only re-parses the specific files patch.files names, splices
    those results into a COPY of job's cached lists AT THE SAME LIST
    POSITION (list order encodes cascade/load order, which conflict
    resolution depends on — see relationship_model.py — so this never
    reorders anything, only replaces individual entries in place), and
    rebuilds the relationship model / reachability graph / issue
    detection (all pure, in-memory, no I/O) from that mix.

    job.codebase_map is reused as-is with no recomputation at all: it
    only depends on the project's file/directory STRUCTURE (package.json
    locations, src/ layout — see codebase_mapper.py), never file content,
    and a patch never changes that structure.

    If a patch's file path isn't found in job's cached css/jsx results —
    which should never happen given patch_generator.py's guarantees, but
    "should never happen" isn't "cannot happen" — this falls back to the
    full from-scratch _run_full_pipeline() rather than risk silently
    working from stale/incomplete data. Speed is only worth it while the
    answer is still exactly as correct as the slow path.
    """
    changed_paths = {pf.path for pf in patch.files}

    css_by_path = {r.file_path: r for r in job.css_results}
    jsx_by_path = {r.file_path: r for r in job.jsx_results}

    changed_css = [p for p in changed_paths if p in css_by_path]
    changed_jsx = [p for p in changed_paths if p in jsx_by_path]

    if job.codebase_map is None or len(changed_css) + len(changed_jsx) != len(changed_paths):
        return _run_full_pipeline(sandbox_root)

    css_results = list(job.css_results)
    for path in changed_css:
        idx = next(i for i, r in enumerate(css_results) if r.file_path == path)
        css_results[idx] = parse_css_file(os.path.join(sandbox_root, path), path)

    if changed_jsx:
        to_reparse = [(os.path.join(sandbox_root, p), p) for p in changed_jsx]
        reparsed = {r.file_path: r for r in parse_jsx_files(to_reparse, sandbox_root)}
        jsx_results = [reparsed.get(r.file_path, r) for r in job.jsx_results]
    else:
        # The common case for a CSS-only rename (fix_planner.py prefers
        # the 0-blast-radius option, which touches no JSX at all): skip
        # the Node subprocess entirely — nothing about any JSX file
        # changed, so job.jsx_results is still exactly correct.
        jsx_results = list(job.jsx_results)

    model = build_relationship_model(css_results, jsx_results)
    reachability_graph = build_reachability_graph(job.codebase_map, jsx_results)
    return detect_issues_scope_aware(model, reachability_graph, job.codebase_map)


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
    # IMPORTANT: this folder's name must match job.root_path's own
    # basename, not a fixed literal name. codebase_mapper.py's single-app
    # fallback (used whenever a project has no package.json / per-app
    # src/ boundaries — i.e. most simple, non-monorepo projects) derives
    # the application's NAME from the root folder's basename. job.issues
    # (the "before" state, computed once at /api/scan time from
    # job.root_path) and every sandbox validation's "after" state need to
    # agree on that name, or _conflict_signatures() below — which keys on
    # (class_name, category, reaching_applications) — will see a fake
    # "new" conflict on EVERY validation, just because "source" (or
    # whatever the upload's folder was called) doesn't equal a hardcoded
    # "project", and reject otherwise-perfectly-good fixes as a result.
    sandbox_basename = os.path.basename(os.path.normpath(job.root_path)) or "project"
    sandbox_root = os.path.join(tmp_dir, sandbox_basename)
    try:
        changed_paths = {pf.path for pf in patch.files}
        if _incremental_pipeline_is_viable(patch, job):
            # Fast path: only the files being edited need to exist in the
            # sandbox at all — everything else is answered from job's
            # already-cached parse results (see _run_incremental_pipeline).
            _copy_changed_files_only(job.root_path, sandbox_root, changed_paths)
        else:
            # Defensive fallback: something about this patch means we
            # can't trust the incremental shortcut (e.g. it references a
            # file outside the original scan), so give it the whole
            # project on disk and let _run_incremental_pipeline fall
            # through to the full from-scratch pipeline itself.
            shutil.copytree(job.root_path, sandbox_root)
        _apply_patch_to_disk(sandbox_root, patch)
        after_issues = _run_incremental_pipeline(sandbox_root, patch, job)
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
