"""
Thin lookup wrapper around Phase 2's ReachabilityGraph.

Keeps scope_aware_conflicts.py free of graph-traversal details — it just
asks "which apps can reach this CSS file?" / "which apps can reach this
JSX file?" / "was this app's reachability real import evidence or a
folder-based guess?" and gets back plain sets/bools.

IMPORTANT FIX: apps_for() now falls back to the Phase 1 folder-based
application assignment whenever the import graph has NO entry for a file
(i.e. it's "unreached" — the import graph couldn't trace it, whether from
path aliases, CSS @import, non-standard entry points, or a parse gap).
Previously an unresolved file fell back to an EMPTY reach set, which
meant it could never cluster with anything — including other files in
its own, same, single application. On real codebases (where the import
graph frequently can't trace every file), that silently turned nearly
every real conflict into a false "isolated_duplicate", which is exactly
backwards: uncertainty about reachability should fall back to the
coarser-but-still-meaningful folder boundary, not to "assume no
interaction is possible." Genuine isolation should only be reported when
we have confirmed evidence of SEPARATE application boundaries — not
whenever import-graph tracing merely fails.
"""
from typing import Dict, Optional, Set

from .models import CodebaseMap, ReachabilityGraph

# Sentinel used when a file can't be resolved to ANY application — neither
# the import graph nor Phase 1's folder-based detection has an opinion.
# Deliberately NOT an empty set: two unresolved files sharing this sentinel
# still correctly cluster together as "the same (unknown) context" via
# _cluster_by_reach's set-intersection logic. An empty set can never
# intersect with anything (including another empty set), which silently
# made usage-confirmation impossible for any project where app-detection
# fails — turning genuine same-app conflicts into permanently-unconfirmed
# ones. method_for_apps() correctly reports this sentinel as NOT real
# import-graph evidence, so it still falls back on single_app_certain
# rather than being mistaken for confirmed multi-app tracing.
UNRESOLVED_APP = "__unresolved_app__"


class ReachabilityLookup:
    def __init__(self, graph: ReachabilityGraph, codebase_map: Optional[CodebaseMap] = None):
        self._graph = graph
        self._codebase_map = codebase_map
        self._css_to_apps: Dict[str, Set[str]] = {
            css_path: set(apps) for css_path, apps in graph.css_reachable_from.items()
        }
        self._jsx_to_apps: Dict[str, Set[str]] = {}
        self._app_method: Dict[str, str] = {}
        for app in graph.applications:
            self._app_method[app.application_name] = app.reachability_method
            for jsx_file in app.reachable_jsx_files:
                self._jsx_to_apps.setdefault(jsx_file, set()).add(app.application_name)

        # Folder-based fallback index (Phase 1), used only when the import
        # graph has no opinion at all about a file.
        self._folder_app_for_file: Dict[str, str] = {}
        if codebase_map is not None:
            for app in codebase_map.applications:
                for f in app.jsx_files + app.js_files + app.css_files:
                    self._folder_app_for_file[f] = app.name

    def apps_for(self, css_file_path: str) -> Set[str]:
        """
        Which application(s) can reach this CSS file. Real import-graph
        evidence wins when present. If the file is completely unreached by
        the import graph, fall back to its Phase 1 folder-assigned
        application — an unresolved import chain is not evidence of
        isolation, just evidence our static tracing has a gap.
        """
        if css_file_path in self._css_to_apps:
            return self._css_to_apps[css_file_path]
        folder_app = self._folder_app_for_file.get(css_file_path)
        return {folder_app} if folder_app else {UNRESOLVED_APP}

    def jsx_reachable_apps(self, jsx_file_path: str) -> Set[str]:
        """Which application(s) can reach this JSX file (same fallback logic)."""
        if jsx_file_path in self._jsx_to_apps:
            return self._jsx_to_apps[jsx_file_path]
        folder_app = self._folder_app_for_file.get(jsx_file_path)
        return {folder_app} if folder_app else {UNRESOLVED_APP}

    def method_for_apps(self, app_names: Set[str]):
        """
        For each app name, True if its reachability came from real import-
        graph evidence rather than a folder-based fallback. Returns a list
        so callers can do all(...)/any(...) directly.
        """
        return [self._app_method.get(name) == "import_graph" for name in app_names]