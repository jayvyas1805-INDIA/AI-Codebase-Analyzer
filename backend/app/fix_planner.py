"""
Fix Planner (new phase, consumes Phase 3's classified Issue + Phase 4's
context-building helpers).

Spec ref: sections 14 (AI fix planner), 15 (minimize blast radius).

WHY THIS IS DETERMINISTIC, NOT LLM-DRIVEN
-------------------------------------------
"Which file should we rename, and how many components does that touch?"
is a question the static analyzer already has hard evidence for — it's
not a judgment call that benefits from an LLM's fuzziness, and getting it
wrong here means generating a patch that breaks working code. Per spec
section 23 ("never blindly trust raw LLM responses"), anything that
decides WHAT gets changed is computed here in plain Python from data
already gathered in earlier phases. The LLM's job (Phase 4's
explanation, and later chat) is to describe and justify this plan in
words — never to invent the plan itself.

STRATEGY SELECTION
--------------------
- issue.conflict_category not in {"confirmed_conflict", "potential_conflict",
  "duplicate_definition"} -> NOT plannable. In particular, "isolated_duplicate"
  is explicitly refused here, per spec section 14's own warning: "Do not
  modify isolated styles merely because they share a class name."

- "duplicate_definition" (identical/non-conflicting properties in an
  overlapping scope) -> consolidate: delete the redundant rule from
  whichever file has the SMALLER blast radius, keep the other untouched.
  No JSX changes needed since the class name doesn't change.

- "confirmed_conflict" / "potential_conflict" -> rename_scoped_class:
  among the files in conflict, the one with the SMALLER blast radius
  (fewest JSX usages that would be affected) gets its selector — and
  every JSX usage that depends on it — renamed to a component-scoped
  name. The file with the larger blast radius is left untouched, since
  touching it would affect more code (spec section 15's Option A vs B
  example, generalized).

BLAST RADIUS
-------------
For a given CSS file, blast radius = number of JSX class-name usages of
this exact class name found in files that actually import that CSS file
(Phase 4's `_importers_of` helper, reused here). If no importer is found
at all (folder-only reachability), we fall back to counting usages across
every JSX file in the same reaching application, but downgrade risk to
"medium" minimum for that reason.
"""
from typing import List, Optional, Tuple

from .models import CSSClassDefinitionRef, FixOption, FixPlan, Issue
from .ai_context_builder import _importers_of, _file_to_application

NOT_PLANNABLE_CATEGORIES = {"isolated_duplicate", "unused_css", None}


def _component_stem(css_file_path: str) -> str:
    """'admin/src/components/Dashboard/dashboard.css' -> 'dashboard'"""
    base = css_file_path.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0].lower()


def _blast_radius(
    css_file_path: str, class_name: str, issue: Issue, job
) -> Tuple[int, List[str], str]:
    """Returns (count, affected_jsx_files, method)."""
    importers = _importers_of(css_file_path, job.jsx_results)
    matching_usages = [u for u in issue.jsx_usages if u.file_path in importers]

    if importers:
        return len(matching_usages), sorted({u.file_path for u in matching_usages}), "import_graph"

    # No direct importer found — fall back to "same application" as a
    # conservative upper-bound estimate, and say so explicitly.
    app_name = _file_to_application(css_file_path, job.codebase_map)
    same_app_usages = [
        u for u in issue.jsx_usages
        if _file_to_application(u.file_path, job.codebase_map) == app_name
    ]
    return len(same_app_usages), sorted({u.file_path for u in same_app_usages}), "folder_fallback"


def _defs_by_file(issue: Issue) -> dict:
    grouped: dict = {}
    for d in issue.css_definitions:
        grouped.setdefault(d.file_path, []).append(d)
    return grouped


def plan_fix(issue: Issue, job) -> FixPlan:
    if issue.conflict_category in NOT_PLANNABLE_CATEGORIES:
        reason = (
            "Isolated duplicates are explicitly excluded from auto-fixing per the "
            "spec's own guardrail: 'Do not modify isolated styles merely because "
            "they share a class name.' No cross-scope interaction was established, "
            "so there is nothing to fix."
            if issue.conflict_category == "isolated_duplicate"
            else "This issue type is not a fixable CSS/JSX conflict."
        )
        return FixPlan(
            issue_id=issue.id,
            class_name=issue.class_name,
            plannable=False,
            reason_if_not_plannable=reason,
        )

    grouped = _defs_by_file(issue)
    files = sorted(grouped.keys())
    if len(files) < 2:
        return FixPlan(
            issue_id=issue.id,
            class_name=issue.class_name,
            plannable=False,
            reason_if_not_plannable="Fewer than two files involved — nothing to reconcile.",
        )

    blast_by_file = {}
    method_by_file = {}
    files_by_file = {}
    for f in files:
        count, affected_files, method = _blast_radius(f, issue.class_name, issue, job)
        blast_by_file[f] = count
        method_by_file[f] = method
        files_by_file[f] = affected_files

    options: List[FixOption] = []

    if issue.conflict_category == "duplicate_definition":
        # Keep the file with the LARGER blast radius (more depends on it
        # staying put); delete the redundant rule from the other file(s).
        keeper = max(files, key=lambda f: blast_by_file[f])
        for f in files:
            if f == keeper:
                continue
            options.append(
                FixOption(
                    strategy="consolidate_duplicate",
                    description=(
                        f"Remove the redundant '.{issue.class_name}' rule from '{f}' "
                        f"(identical/non-conflicting properties already defined via '{keeper}')."
                    ),
                    blast_radius=0,
                    risk="low",
                    affected_files=[f],
                )
            )
        chosen = options[0] if options else None
        return FixPlan(
            issue_id=issue.id,
            class_name=issue.class_name,
            plannable=True,
            chosen_strategy=chosen.strategy if chosen else None,
            target_file=chosen.affected_files[0] if chosen else None,
            risk=chosen.risk if chosen else None,
            blast_radius=chosen.blast_radius if chosen else None,
            rationale=(
                f"'{keeper}' has the larger effective blast radius "
                f"({blast_by_file[keeper]} JSX usage(s)), so it's kept untouched; "
                f"redundant rule(s) elsewhere are removed instead."
            ),
            options_considered=options,
        )

    # confirmed_conflict / potential_conflict -> rename the smaller side.
    for f in files:
        options.append(
            FixOption(
                strategy="rename_scoped_class",
                description=(
                    f"Rename '.{issue.class_name}' in '{f}' to a component-scoped name "
                    f"and update its {blast_by_file[f]} JSX usage(s) accordingly."
                ),
                blast_radius=blast_by_file[f],
                risk=(
                    "low" if blast_by_file[f] <= 3 and method_by_file[f] == "import_graph"
                    else "medium" if blast_by_file[f] <= 10
                    else "high"
                ),
                affected_files=[f] + files_by_file[f],
            )
        )

    chosen = min(options, key=lambda o: o.blast_radius)
    other_files = [f for f in files if f != _strategy_target_file(chosen, files)]

    rationale = (
        f"Renaming in '{_strategy_target_file(chosen, files)}' affects the fewest JSX usages "
        f"({chosen.blast_radius}), versus {[blast_by_file[f] for f in other_files]} for the "
        f"alternative(s) — smallest safe modification per the spec's blast-radius principle."
    )
    if any(method_by_file[f] == "folder_fallback" for f in files):
        rationale += (
            " Note: blast radius for at least one file was estimated via folder-based "
            "fallback (no direct import evidence was found), so treat this estimate as an "
            "upper bound, not a precise count."
        )

    return FixPlan(
        issue_id=issue.id,
        class_name=issue.class_name,
        plannable=True,
        chosen_strategy=chosen.strategy,
        target_file=chosen.affected_files[0],
        risk=chosen.risk,
        blast_radius=chosen.blast_radius,
        rationale=rationale,
        options_considered=options,
    )


def _strategy_target_file(option: FixOption, files: List[str]) -> str:
    # affected_files[0] is always the CSS file being renamed for rename_scoped_class
    return option.affected_files[0] if option.affected_files else files[0]
