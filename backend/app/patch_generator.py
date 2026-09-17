"""
Patch Generator (new phase, consumes fix_planner.py's FixPlan).

Spec ref: section 16 (patch generation — "generate an actual patch
instead of only describing a fix... never rewrite an entire file when a
small patch is sufficient") and section 23 (validate structured output
before trusting it).

HOW IT WORKS
-------------
For each line it needs to change, this module:
  1. Reads the REAL line from the original source file on disk (using
     job.root_path, cached from the scan).
  2. Finds the class-name token on that line with a word-boundary-safe
     regex (so renaming "btn" never accidentally matches "btn-primary").
  3. Only proceeds if EXACTLY ONE match is found on that line. If zero or
     more than one match turns up, it refuses to guess — that line is
     added to `manual_review_needed` instead of being silently patched
     wrong.
  4. Produces a start_line/end_line/replacement change, exactly matching
     the {"path", "changes": [{"start_line", "end_line", "replacement"}]}
     structure from spec section 16's own patch example.

Two strategies are implemented, matching fix_planner.py's two plannable
categories:
  - "rename_scoped_class": rewrite the CSS selector line for the target
    file's definition(s), and every JSX line that references that exact
    class name in one of that file's importers.
  - "consolidate_duplicate": delete the redundant CSS rule block entirely
    from the file that has the smaller blast radius. No JSX changes
    needed since the class name itself doesn't change.

Nothing here ever rewrites a whole file — only the specific lines a rule
or usage actually occupies.
"""
import os
import re
from typing import Dict, List, Tuple

from .models import FixPlan, Issue, Patch, PatchFile, PatchFileChange


def _read_lines(root_path: str, rel_path: str) -> List[str]:
    abs_path = os.path.join(root_path, rel_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.readlines()


def _word_bounded_pattern(token: str, css_selector: bool) -> re.Pattern:
    prefix = r'(?<![\w-])\.' if css_selector else r'(?<![\w-])'
    return re.compile(prefix + re.escape(token) + r'(?![\w-])')


def _existing_class_names(job) -> set:
    existing = set()
    for css_result in job.css_results:
        for rule in css_result.rules:
            existing.update(rule.class_names)
    return existing


def _dedupe_name(candidate: str, job) -> str:
    """Suffixes `candidate` with -2, -3, ... until it doesn't collide with
    any existing class name in the project. Used for BOTH the mechanical
    fallback name and any LLM-suggested name (see ai_rename_suggester.py),
    so uniqueness is guaranteed deterministically regardless of source —
    the LLM is never trusted to have checked this itself."""
    existing = _existing_class_names(job)
    if candidate not in existing:
        return candidate
    i = 2
    while f"{candidate}-{i}" in existing:
        i += 1
    return f"{candidate}-{i}"


def _unique_new_name(stem: str, class_name: str, job) -> str:
    # filename_classname convention (see ai_rename_suggester.py's module
    # docstring) — "stem" is already the lowercased file stem computed by
    # fix_planner._component_stem, so this mirrors
    # ai_rename_suggester.mechanical_class_name exactly for the mechanical
    # (no-LLM / rejected-LLM-suggestion) path.
    return _dedupe_name(f"{stem}_{class_name}", job)


def _find_rule_block_end(lines: List[str], start_line: int) -> int:
    """Given the 1-indexed line a CSS rule's selector starts on, find the
    1-indexed line its closing '}' is on, by brace-depth counting."""
    depth = 0
    found_open = False
    idx = start_line - 1
    while idx < len(lines):
        depth += lines[idx].count("{")
        if "{" in lines[idx]:
            found_open = True
        depth -= lines[idx].count("}")
        if found_open and depth <= 0:
            return idx + 1
        idx += 1
    return start_line  # fallback: single-line rule, malformed, or EOF


def _generate_rename(issue: Issue, plan: FixPlan, job) -> Tuple[Dict[str, PatchFile], List[str], str]:
    from .fix_planner import _component_stem  # local import avoids a circular top-level import
    from .ai_rename_suggester import suggest_class_name  # local import, same reason

    manual_review: List[str] = []
    files_map: Dict[str, PatchFile] = {}

    chosen_option = next(
        (o for o in plan.options_considered if o.affected_files and o.affected_files[0] == plan.target_file),
        None,
    )
    target_css_file = plan.target_file
    stem = _component_stem(target_css_file)

    # Try an LLM-suggested descriptive name first (see ai_rename_suggester.py
    # for why this is the one place in the pipeline that's LLM-assisted).
    # Both paths go through the SAME _dedupe_name collision-avoidance, so
    # uniqueness is guaranteed deterministically no matter which one wins.
    llm_candidate = suggest_class_name(issue, plan, job)
    if llm_candidate:
        new_name = _dedupe_name(llm_candidate, job)
        naming_note = "AI-suggested name, based on what the component actually does"
    else:
        new_name = _unique_new_name(stem, issue.class_name, job)
        naming_note = "mechanically generated from the file name (no LLM configured, or its suggestion was rejected)"

    css_pattern = _word_bounded_pattern(issue.class_name, css_selector=True)
    css_lines = _read_lines(job.root_path, target_css_file)
    target_defs = [d for d in issue.css_definitions if d.file_path == target_css_file]

    css_changes: List[PatchFileChange] = []
    for d in target_defs:
        line_idx = d.line_number - 1
        if line_idx >= len(css_lines):
            manual_review.append(f"{target_css_file}:{d.line_number} is out of range — skipped.")
            continue
        original_line = css_lines[line_idx]
        matches = css_pattern.findall(original_line)
        if len(matches) != 1:
            manual_review.append(
                f"{target_css_file}:{d.line_number} has {len(matches)} occurrence(s) of "
                f"'.{issue.class_name}' on this line — skipped, needs manual review."
            )
            continue
        new_line = css_pattern.sub(
            lambda match: f".{new_name}",
            original_line
        )
        css_changes.append(
            PatchFileChange(
                start_line=d.line_number,
                end_line=d.line_number,
                replacement=new_line.rstrip("\n"),
                original=original_line.rstrip("\n"),
            )
        )
    if css_changes:
        files_map[target_css_file] = PatchFile(path=target_css_file, changes=css_changes)

    affected_jsx_files = set((chosen_option.affected_files[1:] if chosen_option else []))
    usage_pattern = _word_bounded_pattern(issue.class_name, css_selector=False)
    for u in issue.jsx_usages:
        if u.file_path not in affected_jsx_files:
            continue
        jsx_lines = _read_lines(job.root_path, u.file_path)
        line_idx = u.line_number - 1
        if line_idx >= len(jsx_lines):
            manual_review.append(f"{u.file_path}:{u.line_number} is out of range — skipped.")
            continue
        original_line = jsx_lines[line_idx]
        matches = usage_pattern.findall(original_line)
        if len(matches) != 1:
            manual_review.append(
                f"{u.file_path}:{u.line_number} has {len(matches)} occurrence(s) of "
                f"'{issue.class_name}' on this line — skipped, needs manual review."
            )
            continue
        new_line = usage_pattern.sub(
            lambda match: new_name,
            original_line
        )
        change = PatchFileChange(
            start_line=u.line_number,
            end_line=u.line_number,
            replacement=new_line.rstrip("\n"),
            original=original_line.rstrip("\n"),
        )
        if u.file_path in files_map:
            files_map[u.file_path].changes.append(change)
        else:
            files_map[u.file_path] = PatchFile(path=u.file_path, changes=[change])

    description = (
        f"Renamed '.{issue.class_name}' to '.{new_name}' ({naming_note}) in "
        f"'{target_css_file}' and updated its JSX usage(s) to match — the file "
        f"with the smaller blast radius ({plan.blast_radius} usage(s)) was "
        f"chosen, per the fix plan."
    )
    return files_map, manual_review, description


def _generate_consolidate(issue: Issue, plan: FixPlan, job) -> Tuple[Dict[str, PatchFile], List[str], str]:
    manual_review: List[str] = []
    files_map: Dict[str, PatchFile] = {}

    target_file = plan.target_file
    defs_to_remove = [d for d in issue.css_definitions if d.file_path == target_file]
    lines = _read_lines(job.root_path, target_file)

    changes: List[PatchFileChange] = []
    for d in defs_to_remove:
        end_line = _find_rule_block_end(lines, d.line_number)
        removed_text = "".join(lines[d.line_number - 1: end_line])
        changes.append(
            PatchFileChange(
                start_line=d.line_number,
                end_line=end_line,
                replacement="",
                original=removed_text.rstrip("\n"),
            )
        )
    if changes:
        files_map[target_file] = PatchFile(path=target_file, changes=changes)
    else:
        manual_review.append(f"No removable rule found in '{target_file}' for '.{issue.class_name}'.")

    description = f"Removed the redundant '.{issue.class_name}' rule from '{target_file}'."
    return files_map, manual_review, description


def generate_patch(issue: Issue, plan: FixPlan, job) -> Patch:
    if not plan.plannable:
        return Patch(
            issue_id=issue.id,
            strategy="none",
            description=plan.reason_if_not_plannable or "Not plannable.",
            valid=False,
            validation_errors=["Fix plan marked this issue as not plannable."],
        )

    if not job.root_path:
        return Patch(
            issue_id=issue.id,
            strategy=plan.chosen_strategy or "unknown",
            description="Cannot generate a patch: the original project source path is unavailable for this job.",
            valid=False,
            validation_errors=["job.root_path is missing — was the job's workspace cleaned up?"],
        )

    if plan.chosen_strategy == "rename_scoped_class":
        files_map, manual_review, description = _generate_rename(issue, plan, job)
    elif plan.chosen_strategy == "consolidate_duplicate":
        files_map, manual_review, description = _generate_consolidate(issue, plan, job)
    else:
        return Patch(
            issue_id=issue.id,
            strategy=plan.chosen_strategy or "unknown",
            description="Unrecognized fix strategy.",
            valid=False,
            validation_errors=[f"No patch generator implemented for strategy '{plan.chosen_strategy}'."],
        )

    patch = Patch(
        issue_id=issue.id,
        strategy=plan.chosen_strategy,
        description=description,
        files=list(files_map.values()),
        manual_review_needed=manual_review,
    )
    patch.valid, patch.validation_errors = validate_patch(patch, job)
    return patch


def validate_patch(patch: Patch, job) -> Tuple[bool, List[str]]:
    """
    Spec section 23: never blindly trust generated output. Checks every
    file the patch touches is a file the analyzer actually parsed (no
    hallucinated paths), and every line range is well-formed.
    """
    errors: List[str] = []
    known_files = {r.file_path for r in job.css_results} | {r.file_path for r in job.jsx_results}

    if not patch.files:
        errors.append("Patch produced no file changes at all.")

    for pf in patch.files:
        if pf.path not in known_files:
            errors.append(f"Patch references a file the analyzer never parsed: '{pf.path}'.")
        if not pf.changes:
            errors.append(f"'{pf.path}' has zero changes listed.")
        for c in pf.changes:
            if c.start_line < 1 or c.end_line < c.start_line:
                errors.append(f"Invalid line range in '{pf.path}': {c.start_line}-{c.end_line}.")

    return (len(errors) == 0, errors)