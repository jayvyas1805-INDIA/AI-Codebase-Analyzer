"""
Scope-Aware Conflict Classification (new phase, replaces the naive
name-only conflict logic for the "same class name in 2+ files" case).

Spec ref: sections 7 (context-aware conflict detection, the Level 1-6
hierarchy), 8 (conflict categories), 9 (false positive prevention).

WHY THIS EXISTS
----------------
issue_detector.py's existing `_classify_definitions()` treats "same class
name in 2+ files" as automatically comparable — that's exactly the false
positive the whole spec is written to prevent (admin `.button` vs customer
`.button`). This module is the fix: it only compares declarations between
files whose REACHING APPLICATIONS actually overlap (built in Phase 2's
import_graph.py), and it reports genuinely non-overlapping files as an
explicit "isolated_duplicate" finding instead of silently dropping them
or, worse, flagging them as a conflict.

issue_detector.py is left completely untouched — this is an additive
module. main.py decides which one runs (see the wiring change there).

ALGORITHM (mirrors spec section 7's levels)
--------------------------------------------
For each class name with base-scope (non-@media) definitions in 2+ files:

  Level 1 (same selector) — already true by construction (same class name).

  Level 2/3 (scope + reachability) — for every pair of files defining the
  class, check whether their REACHING-APPLICATION sets (from the Phase 2
  graph) intersect. Union-find the files into clusters using that
  pairwise test: two files only end up in the same cluster if there's a
  chain of real reachability overlap between them. Files in different
  clusters cannot affect the same rendering context, by the available
  static evidence — that's Level 3 answered.

  Level 4 (property conflict) — within each cluster (2+ files that DO
  share reach), compare declarations exactly like the old logic did:
  which properties are shared, and of those, which disagree.

  Level 6 (React impact) — before calling something a CONFIRMED conflict,
  check whether the class is actually used as a className in a component
  that's reachable within the overlapping application(s). Without that,
  it's downgraded to "potential" — the CSS could interact, but nothing
  currently renders it, so calling it confirmed would overstate certainty.

  Level 5 (cascade interaction: specificity/order) is intentionally NOT
  attempted here — the existing CSS parser only records simple class
  selectors, so specificity/order comparison isn't reliable evidence yet.
  Conflicts that would need it are conservatively kept at "potential"
  rather than "confirmed".

Clusters that never overlap with any other cluster produce one
`isolated_duplicate` issue per class name, naming every non-interacting
file — mirroring the spec's section 9 example output exactly.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .models import CSSClassDefinitionRef, Issue
from .relationship_model import RelationshipModel
from .reachability_lookup import ReachabilityLookup


def _cluster_by_reach(
    files: List[str], reach: ReachabilityLookup
) -> List[List[str]]:
    """
    Union-find: two files land in the same cluster only if their reaching-
    application sets intersect (directly, or transitively through a chain
    of other files). Files with NO reaching applications (unreached CSS,
    and no folder-based fallback either) never join any cluster with
    anyone — no evidence, no assumed link.

    PERFORMANCE NOTE: this used to do an O(files^2) pairwise intersection
    check per class name. On a real codebase, a common utility class name
    (.container, .flex, .wrapper, etc.) can be defined in hundreds of
    files, and that quadratic blowup repeats for every such class — this
    was the actual cause of the scan-speed regression on large projects.
    Fixed here by unioning each file against a single "representative"
    file per application name it's reachable from, rather than comparing
    every file to every other file. Two files sharing an application
    still end up in the same connected component (transitively, via that
    shared representative), but the work is O(files * apps_per_file)
    instead of O(files^2).
    """
    parent = {f: f for f in files}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    representative_for_app: Dict[str, str] = {}
    for f in files:
        for app_name in reach.apps_for(f):
            if app_name in representative_for_app:
                union(f, representative_for_app[app_name])
            else:
                representative_for_app[app_name] = f

    groups: Dict[str, List[str]] = defaultdict(list)
    for f in files:
        groups[find(f)].append(f)
    return list(groups.values())


def _compare_declarations(
    defs_subset: List[CSSClassDefinitionRef],
) -> Tuple[Set[str], Set[str]]:
    """Returns (shared_properties, conflicting_properties) — same logic
    as the original issue_detector, scoped to one cluster's definitions."""
    property_values: Dict[str, Set[str]] = {}
    property_def_count: Dict[str, int] = {}

    for d in defs_subset:
        props_in_this_def = set()
        for decl in d.declarations:
            props_in_this_def.add(decl.property)
            property_values.setdefault(decl.property, set()).add(decl.value)
        for p in props_in_this_def:
            property_def_count[p] = property_def_count.get(p, 0) + 1

    shared_properties = {p for p, count in property_def_count.items() if count >= 2}
    conflicting_properties = {p for p in shared_properties if len(property_values[p]) > 1}
    return shared_properties, conflicting_properties


def _has_confirmed_usage(
    class_name: str, cluster_apps: Set[str], model: RelationshipModel, reach: ReachabilityLookup
) -> bool:
    """Level 6: is this class used as a className in a JSX file that's
    actually reachable from one of the overlapping applications?"""
    usages = model.jsx_usages.get(class_name, [])
    for usage in usages:
        if not usage.is_fully_static:
            continue  # can't confirm a dynamically-applied class statically
        if reach.jsx_reachable_apps(usage.file_path) & cluster_apps:
            return True
    return False


def _classify_cluster(
    class_name: str,
    cluster_files: List[str],
    definitions_by_file: Dict[str, List[CSSClassDefinitionRef]],
    model: RelationshipModel,
    reach: ReachabilityLookup,
) -> Tuple[str, str, str, str]:
    """
    Returns (issue_type, severity, confidence, conflict_category) for a
    cluster of 2+ files that DO share reachable application(s).
    """
    cluster_defs = [d for f in cluster_files for d in definitions_by_file[f]]
    shared_properties, conflicting_properties = _compare_declarations(cluster_defs)

    cluster_apps: Set[str] = set()
    for f in cluster_files:
        cluster_apps |= reach.apps_for(f)

    # IMPORTANT: only require real import-graph tracing (not a folder-based
    # fallback) as extra assurance when the cluster spans MULTIPLE distinct
    # applications — that's the case with genuine ambiguity about whether
    # two apps' bundles really interact. When every file in the cluster
    # belongs to the SAME single application, folder-based reachability
    # already settles the question by construction (there's only one
    # bundle to begin with) — downgrading confidence there just because the
    # import graph happened to miss tracing an import (path aliases, CSS
    # @import, non-standard entry points — all common on real codebases)
    # was hiding genuine same-app conflicts as "potential" instead of
    # "confirmed", which is the opposite of what the evidence supports.
    single_app_certain = len(cluster_apps) <= 1
    all_import_graph = all(reach.method_for_apps(cluster_apps))

    if not shared_properties or not conflicting_properties:
        # Identical, or non-overlapping properties — nothing to fight over.
        return "duplicate_class", "low", "high", "duplicate_definition"

    usage_confirmed = _has_confirmed_usage(class_name, cluster_apps, model, reach)

    if conflicting_properties == shared_properties and usage_confirmed and (single_app_certain or all_import_graph):
        return "css_conflict", "high", "high", "confirmed_conflict"

    # Either only partially conflicting, or fully conflicting but missing
    # usage confirmation / resting on a folder-fallback reachability guess
    # across GENUINELY MULTIPLE applications — real interaction can't be
    # fully confirmed there, so this stays "potential".
    severity = "medium" if conflicting_properties == shared_properties else "medium"
    confidence = "medium" if (usage_confirmed and all_import_graph) else "low"
    return "partial_overlap_class", severity, confidence, "potential_conflict"


def detect_scope_aware_conflicts(
    model: RelationshipModel, reach: ReachabilityLookup, id_gen
) -> List[Issue]:
    issues: List[Issue] = []

    for class_name, definitions in model.css_classes.items():
        base_defs = [d for d in definitions if d.media_context is None]
        files = sorted({d.file_path for d in base_defs})
        if len(files) < 2:
            continue  # only one file defines it — nothing to compare

        definitions_by_file: Dict[str, List[CSSClassDefinitionRef]] = defaultdict(list)
        for d in base_defs:
            definitions_by_file[d.file_path].append(d)

        clusters = _cluster_by_reach(files, reach)

        # --- one issue per cluster that actually shares reach (2+ files) ---
        for cluster_files in clusters:
            if len(cluster_files) < 2:
                continue
            issue_type, severity, confidence, category = _classify_cluster(
                class_name, cluster_files, definitions_by_file, model, reach
            )
            cluster_apps = sorted(set().union(*(reach.apps_for(f) for f in cluster_files)))
            cluster_defs = [d for f in cluster_files for d in definitions_by_file[f]]

            scope_analysis = (
                f"'.{class_name}' is defined in {', '.join(cluster_files)}, all reachable "
                f"from application(s) {cluster_apps or ['(unresolved reach)']} — "
                f"static import evidence shows these CAN affect the same rendering context."
            )

            if category == "confirmed_conflict":
                message = (
                    f"'.{class_name}' is defined differently in {', '.join(cluster_files)} — "
                    f"every shared CSS property has a different value, both definitions are "
                    f"reachable from {cluster_apps}, and a matching JSX usage was confirmed. "
                    f"Whichever file loads last will silently win."
                )
            elif category == "potential_conflict":
                message = (
                    f"'.{class_name}' is defined in {', '.join(cluster_files)} with conflicting "
                    f"properties, and both are reachable from {cluster_apps} — but interaction "
                    f"could not be fully confirmed (no static JSX usage match, or reachability "
                    f"relied on a folder-based fallback rather than a real import chain). "
                    f"Worth a manual check."
                )
            else:  # duplicate_definition
                message = (
                    f"'.{class_name}' is defined identically (or with non-overlapping "
                    f"properties) in {', '.join(cluster_files)}, and both share reach from "
                    f"{cluster_apps}. Likely safe to consolidate."
                )

            issues.append(
                Issue(
                    id=id_gen(),
                    issue_type=issue_type,
                    severity=severity,
                    class_name=class_name,
                    message=message,
                    confidence=confidence,
                    css_definitions=cluster_defs,
                    jsx_usages=model.jsx_usages.get(class_name, []),
                    conflict_category=category,
                    reaching_applications=cluster_apps,
                    scope_analysis=scope_analysis,
                )
            )

        # --- one isolated_duplicate issue if there's real isolation to report ---
        if len(clusters) >= 2:
            all_files_by_cluster = [sorted(c) for c in clusters]
            per_cluster_apps = [sorted(set().union(*(reach.apps_for(f) for f in c)) or {"(none)"}) for c in clusters]
            scope_analysis = (
                f"'.{class_name}' also appears in "
                f"{'; '.join(f'{files} (apps: {apps})' for files, apps in zip(all_files_by_cluster, per_cluster_apps))} "
                f"— no static import evidence shows these groups can affect the same rendering "
                f"context, so they are treated as independent."
            )
            issues.append(
                Issue(
                    id=id_gen(),
                    issue_type="isolated_duplicate",
                    severity="info",
                    class_name=class_name,
                    message=(
                        f"'.{class_name}' is defined in multiple places that do NOT share a "
                        f"reachable application context: {'; '.join(str(c) for c in all_files_by_cluster)}. "
                        f"This is NOT a conflict — each group is isolated by static import evidence."
                    ),
                    confidence="high",
                    css_definitions=[d for f in files for d in definitions_by_file[f]],
                    jsx_usages=model.jsx_usages.get(class_name, []),
                    conflict_category="isolated_duplicate",
                    reaching_applications=[],
                    scope_analysis=scope_analysis,
                )
            )

    return issues
