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
"""
from typing import List, Optional, Tuple

from .models import Issue
from .relationship_model import RelationshipModel


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


def detect_issues(model: RelationshipModel) -> List[Issue]:
    issues: List[Issue] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"issue-{counter:04d}"

    # --- 1. Duplicate / partial overlap / conflict ---
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

    # --- 2. Unused CSS classes ---
    # MVP simplification: if the project uses dynamic classNames ANYWHERE,
    # we can't be fully sure a class isn't applied conditionally at runtime,
    # so ALL unused-class findings for that project get lower confidence.
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
                id=next_id(),
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
            )
        )

    # --- 3. JSX classNames with no matching CSS definition ---
    for class_name, usages in model.jsx_usages.items():
        if class_name in model.css_classes:
            continue
        issues.append(
            Issue(
                id=next_id(),
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
