"""
Static Analysis / Issue Detection (Phase 4b).

Reads the RelationshipModel (Phase 4a) and applies DETERMINISTIC rules only.
No LLM call happens in this file — per the project spec, the LLM's job
(a later phase) is only to EXPLAIN issues this module already found, never
to discover them itself.

Detects:
  1. Duplicate / partial-overlap / conflicting CSS class definitions
     (same class name, 2+ different files, base scope only — @media-scoped
     definitions are excluded from comparison since they only apply
     conditionally, not always)
  2. Unused CSS classes (defined, never used as a static className in JSX)
  3. Undefined CSS classes (used as a static className in JSX, no matching
     CSS rule anywhere in the project)
  4. Unimported CSS files (a CSS file was parsed but no JSX/JS file imports
     it — low severity/confidence since it could still be loaded another way)
"""
from typing import List, Optional, Tuple

from .models import Issue
from .relationship_model import RelationshipModel
from .reachability_lookup import ReachabilityLookup
from .scope_aware_conflicts import detect_scope_aware_conflicts
from .tailwind_conflicts import detect_tailwind_conflicts


def _classify_definitions(definitions) -> Optional[Tuple[str, str]]:
    """
    Compares declarations across BASE-SCOPE definitions (media_context=None)
    of the same class name, across DIFFERENT files. Returns
    (issue_type, severity), or None if there's nothing worth flagging
    (e.g. the class only exists in one file).
    """
    base_defs = [d for d in definitions if d.media_context is None]

    files_involved = {d.file_path for d in base_defs}
    if len(files_involved) < 2:
        return None  # only interesting when 2+ DIFFERENT files define it

    property_values: dict = {}     # property -> set of distinct values seen
    property_def_count: dict = {}  # property -> how many definitions contain it

    for d in base_defs:
        props_in_this_def = set()
        for decl in d.declarations:
            props_in_this_def.add(decl.property)
            property_values.setdefault(decl.property, set()).add(decl.value)
        for p in props_in_this_def:
            property_def_count[p] = property_def_count.get(p, 0) + 1

    shared_properties = {p for p, count in property_def_count.items() if count >= 2}
    conflicting_properties = {p for p in shared_properties if len(property_values[p]) > 1}

    if not shared_properties:
        # Same class name, but the two definitions don't even set the same
        # properties — additive rather than conflicting. Still worth a
        # low-severity heads-up so the person can decide whether to merge them.
        return ("duplicate_class", "low")
    if not conflicting_properties:
        return ("duplicate_class", "low")           # every shared property matches exactly
    if conflicting_properties == shared_properties:
        return ("css_conflict", "high")               # every shared property disagrees
    return ("partial_overlap_class", "medium")        # some agree, some disagree


def _detect_unused_classes(model: RelationshipModel, id_gen) -> List[Issue]:
    issues: List[Issue] = []
    unused_confidence = "low" if model.project_has_dynamic_classnames else "high"
    unused_severity = "low" if model.project_has_dynamic_classnames else "medium"

    for class_name, definitions in model.css_classes.items():
        if class_name in model.jsx_usages:
            continue
        note = (
            " Note: this project uses dynamic classNames elsewhere, so this "
            "could still be applied conditionally at runtime."
            if model.project_has_dynamic_classnames
            else ""
        )
        issues.append(
            Issue(
                id=id_gen(),
                issue_type="unused_css_class",
                severity=unused_severity,
                class_name=class_name,
                message=(
                    f"'.{class_name}' is defined in "
                    f"{', '.join(sorted({d.file_path for d in definitions}))} but never appears "
                    f"as a static className anywhere in the scanned JSX/JS files.{note}"
                ),
                confidence=unused_confidence,
                css_definitions=definitions,
                jsx_usages=[],
                conflict_category="unused_css",
            )
        )
    return issues


def _detect_undefined_classes(model: RelationshipModel, id_gen) -> List[Issue]:
    issues: List[Issue] = []
    for class_name, usages in model.jsx_usages.items():
        if class_name in model.css_classes:
            continue
        issues.append(
            Issue(
                id=id_gen(),
                issue_type="undefined_css_class",
                severity="medium",
                class_name=class_name,
                message=(
                    f"'{class_name}' is used as a className in "
                    f"{', '.join(sorted({u.file_path for u in usages}))} but no matching CSS "
                    f"rule was found anywhere in the project. Possible typo or missing style."
                ),
                confidence="high",
                css_definitions=[],
                jsx_usages=usages,
            )
        )
    return issues


def _detect_unimported_css(model: RelationshipModel, id_gen) -> List[Issue]:
    issues: List[Issue] = []
    for css_path in model.css_file_paths:
        if css_path in model.imported_css_paths:
            continue
        issues.append(
            Issue(
                id=id_gen(),
                issue_type="unimported_css_file",
                severity="low",
                class_name=css_path,
                message=(
                    f"'{css_path}' is never imported by any JSX/JS file in this project. "
                    f"Its styles may be unused, or it could be included some other way this "
                    f"tool doesn't check (e.g. a <link> tag in index.html)."
                ),
                confidence="low",
                css_definitions=[],
                jsx_usages=[],
            )
        )
    return issues


def detect_issues(model: RelationshipModel) -> List[Issue]:
    """
    ORIGINAL name-only conflict detection. Kept exactly as it was — this
    is what runs if no reachability graph is available for some reason
    (e.g. a project with zero detected JSX imports). Prefer
    detect_issues_scope_aware() whenever a ReachabilityGraph exists.
    """
    issues: List[Issue] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"issue-{counter:04d}"

    # --- 1. Duplicate / partial overlap / conflict (name-only, no scope awareness) ---
    for class_name, definitions in model.css_classes.items():
        result = _classify_definitions(definitions)
        if result is None:
            continue
        issue_type, severity = result
        base_defs = [d for d in definitions if d.media_context is None]
        files = sorted({d.file_path for d in base_defs})

        if issue_type == "css_conflict":
            message = (
                f"'.{class_name}' is defined differently in {', '.join(files)} — "
                f"every shared CSS property has a different value. Whichever file "
                f"loads last will silently win, which can cause unpredictable styling."
            )
        elif issue_type == "partial_overlap_class":
            message = (
                f"'.{class_name}' is defined in {', '.join(files)} with some matching "
                f"and some conflicting properties — worth a manual check."
            )
        else:
            message = (
                f"'.{class_name}' is defined identically (or non-overlapping) in "
                f"{', '.join(files)}. Likely low-risk, but consider consolidating."
            )

        issues.append(
            Issue(
                id=next_id(),
                issue_type=issue_type,
                severity=severity,
                class_name=class_name,
                message=message,
                confidence="high",
                css_definitions=base_defs,
                jsx_usages=model.jsx_usages.get(class_name, []),
            )
        )

    issues.extend(_detect_unused_classes(model, next_id))
    issues.extend(_detect_undefined_classes(model, next_id))
    issues.extend(_detect_unimported_css(model, next_id))
    return issues


def detect_issues_scope_aware(
    model: RelationshipModel, reachability_graph, codebase_map=None, jsx_results=None
) -> List[Issue]:
    """
    Phase 3 entry point. Same unused/undefined/unimported detection as
    before (those don't need cross-file scope awareness), but conflict/
    duplicate detection is replaced with scope_aware_conflicts.py's
    reachability-based classification — see that module's docstring for
    the full Confirmed/Potential/Isolated/Duplicate logic.

    codebase_map is passed through so ReachabilityLookup can fall back to
    folder-based application assignment when the import graph couldn't
    trace a file — see reachability_lookup.py's docstring for why that
    fallback matters (without it, real-world import patterns the graph
    can't trace get silently misreported as isolated).

    jsx_results (optional, but should always be passed by main.py) is
    needed SEPARATELY from `model` for Tailwind conflict detection — see
    tailwind_conflicts.py's docstring for why that check operates on raw
    per-usage class lists rather than RelationshipModel, which flattens
    usages by class name across the whole project and loses "which classes
    appeared together on one element." Kept optional here (default None ->
    skip Tailwind checks) so existing callers/tests that only pass a model
    don't break.
    """
    issues: List[Issue] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"issue-{counter:04d}"

    reach = ReachabilityLookup(reachability_graph, codebase_map)
    issues.extend(detect_scope_aware_conflicts(model, reach, next_id))
    issues.extend(_detect_unused_classes(model, next_id))
    issues.extend(_detect_undefined_classes(model, next_id))
    issues.extend(_detect_unimported_css(model, next_id))
    if jsx_results is not None:
        issues.extend(detect_tailwind_conflicts(jsx_results, next_id))
    return issues