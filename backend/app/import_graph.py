"""
Import / Reachability Graph (new phase, sits between the Phase 6 Codebase
Mapper and Phase 4's issue detector).

Spec ref: sections 5 (CSS scope and reachability) and 6 (import graph).

WHY THIS EXISTS
----------------
Phase 6 (codebase_mapper.py) only knows which FOLDER a file sits in. That's
a good first signal but it's not the real question. The real question is:
"starting from an application's actual entry point, does the JS import
graph ever pull this CSS file in?" Two files can sit in totally separate
folders and still interact (a shared/common.css imported by both admin and
customer), and two files can sit in the same folder tree without one ever
being imported by the other.

This module builds that answer using ONLY static import evidence already
extracted by the existing JSX parser (Phase 3) — it invents nothing.

ALGORITHM
---------
1. Build a plain adjacency list: for every JSX/JS file, which local
   (non-external) files does it import — both component imports and CSS
   imports — using ImportStatement.resolved_path.
2. For each application (from the codebase map), starting at its detected
   entry point(s), do a breadth-first walk over that adjacency list. Every
   JSX/JS file visited is "reachable"; every CSS file directly imported by
   a visited file is "reachable CSS" for that application.
3. If an application has NO detected entry point (codebase_mapper couldn't
   find App.jsx/index.js/etc.), we can't walk anything — fall back to
   treating every file the mapper already assigned to that application's
   folder as reachable, and mark this explicitly as the lower-confidence
   "folder_fallback_no_entry_point" method rather than silently pretending
   it's as solid as real import evidence.
4. Invert the per-application reachable-CSS sets into a single
   css_reachable_from: css_path -> [application names] index. This is the
   lookup the next phase (scope-aware conflict detection) needs: two
   definitions of the same class only need real interaction analysis if
   their files' reaching-application sets overlap.
5. CSS files that no application's walk ever reached are reported as
   unreached_css_files — candidates for the existing unimported_css_file
   issue type, now with actual reachability evidence behind them instead
   of just "nothing imports it that we noticed".
"""
from collections import deque
from typing import Dict, List, Set

from .models import (
    ApplicationReachability,
    CodebaseMap,
    JSXFileParseResult,
    ReachabilityGraph,
)


def _build_adjacency(
    jsx_results: List[JSXFileParseResult],
) -> Dict[str, Dict[str, List[str]]]:
    """
    file_path -> {"components": [resolved_path, ...], "css": [resolved_path, ...]}
    Only local (non-external) imports are included — external npm packages
    can't tell us anything about which CSS in THIS project is reachable.
    """
    adjacency: Dict[str, Dict[str, List[str]]] = {}
    for result in jsx_results:
        edges = {"components": [], "css": []}
        for imp in result.imports:
            if imp.is_external or imp.resolved_path is None:
                continue
            if imp.is_css_import:
                edges["css"].append(imp.resolved_path)
            else:
                edges["components"].append(imp.resolved_path)
        adjacency[result.file_path] = edges
    return adjacency


def _walk_from_entry_points(
    entry_points: List[str], adjacency: Dict[str, Dict[str, List[str]]]
):
    """
    BFS over the component-import graph starting at the given entry
    points. Returns (reached_components: set, reached_css: set,
    unresolved: set) — unresolved holds import targets that don't
    correspond to any file we actually parsed (broken import, or an
    extension/resolution edge case), surfaced rather than silently dropped.
    """
    reached_components: Set[str] = set()
    reached_css: Set[str] = set()
    unresolved: Set[str] = set()

    queue = deque(e for e in entry_points if e in adjacency)
    for e in entry_points:
        if e in adjacency:
            reached_components.add(e)

    while queue:
        current = queue.popleft()
        edges = adjacency.get(current, {"components": [], "css": []})

        for css_target in edges["css"]:
            reached_css.add(css_target)

        for comp_target in edges["components"]:
            if comp_target not in adjacency:
                # Points at something we didn't parse (not .jsx/.js, or
                # genuinely missing on disk — jsx_parser already best-guessed
                # a path even when the file wasn't found).
                unresolved.add(comp_target)
                continue
            if comp_target not in reached_components:
                reached_components.add(comp_target)
                queue.append(comp_target)

    return reached_components, reached_css, unresolved


def build_reachability_graph(
    codebase_map: CodebaseMap, jsx_results: List[JSXFileParseResult]
) -> ReachabilityGraph:
    adjacency = _build_adjacency(jsx_results)

    app_results: List[ApplicationReachability] = []
    css_reachable_from: Dict[str, List[str]] = {}
    warnings: List[str] = []

    for app in codebase_map.applications:
        if app.entry_points:
            reached_components, reached_css, unresolved = _walk_from_entry_points(
                app.entry_points, adjacency
            )
            method = "import_graph"

            if not reached_components and not reached_css:
                # Entry point existed but the walk found nothing — most
                # likely the entry file itself failed to parse. Don't
                # silently report an empty (and misleadingly confident)
                # graph; fall back instead.
                method = "folder_fallback_no_entry_point"
                reached_components = set(app.jsx_files) | set(app.js_files)
                reached_css = set(app.css_files)
                warnings.append(
                    f"Application '{app.name}': entry point(s) {app.entry_points} "
                    f"produced no resolvable import graph (parse error?) — falling "
                    f"back to folder-based reachability for this application."
                )
        else:
            method = "folder_fallback_no_entry_point"
            reached_components = set(app.jsx_files) | set(app.js_files)
            reached_css = set(app.css_files)
            unresolved = set()
            warnings.append(
                f"Application '{app.name}': no entry point detected — falling back "
                f"to folder-based reachability. Conflict findings for this "
                f"application carry lower confidence than import-graph-backed ones."
            )

        app_results.append(
            ApplicationReachability(
                application_name=app.name,
                application_root=app.root_path,
                entry_points_used=app.entry_points,
                reachable_jsx_files=sorted(f for f in reached_components if f.endswith((".jsx",))),
                reachable_js_files=sorted(f for f in reached_components if f.endswith(".js")),
                reachable_css_files=sorted(reached_css),
                reachability_method=method,
                unresolved_imports=sorted(unresolved),
            )
        )

        for css_path in reached_css:
            css_reachable_from.setdefault(css_path, []).append(app.name)

    # Shared files (outside every application boundary) are, by definition,
    # not reached by any application's folder-based fallback — but they
    # CAN still show up in css_reachable_from if the import graph actually
    # walked into them from an app's entry point (e.g. shared/common.css
    # imported by admin/src/App.jsx). That's exactly the case the spec
    # wants surfaced as real interaction evidence, so we deliberately do
    # NOT add shared files here separately — the walk above already
    # credits whichever app's entry point actually imports them.

    all_css_files = (
        {c for app in codebase_map.applications for c in app.css_files}
        | set(codebase_map.shared_css_files)
    )
    unreached = sorted(all_css_files - set(css_reachable_from.keys()))

    if unreached:
        warnings.append(
            f"{len(unreached)} CSS file(s) are not reachable from any detected "
            f"application entry point via static import evidence."
        )

    for css_path, apps in css_reachable_from.items():
        css_reachable_from[css_path] = sorted(set(apps))

    return ReachabilityGraph(
        applications=app_results,
        css_reachable_from=css_reachable_from,
        unreached_css_files=unreached,
        warnings=warnings,
    )
