"""
Codebase Mapper (new Phase, sits between Phase 1 Scanner and Phase 4
Relationship Model).

Spec ref: sections 3 (codebase structure awareness) and 4 (application /
project boundary detection).

WHY THIS EXISTS
----------------
The current issue_detector.py treats every class name as living in one
global namespace across the whole ZIP. That's exactly the false-positive
trap the spec calls out: `.button` in admin/styles.css and `.button` in
customer/styles.css get flagged as the same conflict even though they can
never reach the same rendered page.

This module's ONLY job is to answer: "which application does each file
belong to?" It does NOT decide whether two applications' CSS can interact
(that needs the import graph — a later phase) and it does NOT touch
issue_detector.py yet. It is purely evidence-gathering, built on top of
the existing ScanResult, so nothing already working is disturbed.

DETECTION STRATEGY (in priority order, first one that finds anything wins)
----------------------------------------------------------------------
1. package.json boundaries — the strongest signal. Every directory that
   contains a package.json is treated as an application root. This
   correctly handles the admin/ customer/ landing-page/ example from the
   spec, and ordinary monorepos.
2. src/ heuristic fallback — if no package.json exists anywhere (common
   for a ZIP of just source files), treat every top-level directory that
   contains a src/ folder as an application root.
3. Single-app fallback — if neither signal produces anything, the whole
   uploaded project is treated as one application ("root"). This keeps
   existing single-app projects (like the current sample_project fixture)
   working exactly as before.

Files that don't fall under ANY detected boundary (e.g. a top-level
shared/common.css sitting next to admin/ and customer/) are NOT assigned
to any application — they're reported separately as "shared" files, since
the spec is explicit that shared-scope vs per-app-scope are different
things and must not be silently merged.
"""
import os
from typing import Dict, List, Optional

from .config import IGNORED_DIRS
from .models import Application, CodebaseMap, ScanResult

ENTRY_POINT_NAMES = {
    "App.jsx", "App.js", "index.js", "index.jsx", "main.js", "main.jsx",
}


def _find_package_json_dirs(root_path: str) -> List[str]:
    """
    Walk the project (same ignore rules as the scanner) looking for
    package.json files. Returns relative directory paths ("" for the
    project root itself), sorted shallowest-first.
    """
    found: List[str] = []
    for current_dir, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        if "package.json" in filenames:
            rel = os.path.relpath(current_dir, root_path)
            found.append("" if rel == "." else rel.replace(os.sep, "/"))
    # Shallowest first so nested/monorepo boundaries are processed in a
    # predictable, human-readable order.
    found.sort(key=lambda p: (p.count("/"), p))
    return found


def _find_src_dirs(root_path: str) -> List[str]:
    """
    Fallback: top-level directories that directly contain a 'src' folder.
    Only looks one level deep on purpose — this is a heuristic of last
    resort, not a general project-structure crawler.
    """
    found: List[str] = []
    try:
        top_level = sorted(os.listdir(root_path))
    except OSError:
        return found

    for name in top_level:
        if name in IGNORED_DIRS or name.startswith("."):
            continue
        candidate = os.path.join(root_path, name)
        if os.path.isdir(candidate) and os.path.isdir(os.path.join(candidate, "src")):
            found.append(name)
    return found


def _normalize(rel_path: str) -> str:
    return rel_path.replace(os.sep, "/")


def _best_matching_root(file_rel_path: str, boundary_roots: List[str]) -> Optional[str]:
    """
    Finds the boundary a file belongs to: the LONGEST matching path
    prefix wins, so nested boundaries (a monorepo app inside another)
    resolve to the most specific one rather than the outermost.
    "" (project root as its own boundary) matches everything, so it's
    only picked when nothing more specific does.
    """
    file_rel_path = _normalize(file_rel_path)
    best: Optional[str] = None
    for root in boundary_roots:
        if root == "":
            candidate_match = True  # root boundary matches every file
        else:
            candidate_match = file_rel_path == root or file_rel_path.startswith(root + "/")
        if candidate_match:
            if best is None or len(root) > len(best):
                best = root
    return best


def _detect_entry_points(root_path: str, app_root: str) -> List[str]:
    entry_points: List[str] = []
    search_dirs = [
        os.path.join(root_path, app_root) if app_root else root_path,
    ]
    src_dir = os.path.join(root_path, app_root, "src") if app_root else os.path.join(root_path, "src")
    search_dirs.append(src_dir)

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for name in ENTRY_POINT_NAMES:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                rel = _normalize(os.path.relpath(candidate, root_path))
                if rel not in entry_points:
                    entry_points.append(rel)
    return entry_points


def build_codebase_map(scan_result: ScanResult) -> CodebaseMap:
    root_path = scan_result.root_path
    warnings: List[str] = []

    boundary_roots = _find_package_json_dirs(root_path)
    method = "package_json"

    if not boundary_roots:
        src_dirs = _find_src_dirs(root_path)
        if src_dirs:
            boundary_roots = src_dirs
            method = "src_heuristic"
        else:
            boundary_roots = [""]
            method = "single_app_fallback"

    # Build empty Application shells first, so every boundary appears in
    # the result even if it ends up with zero matched files.
    apps_by_root: Dict[str, Application] = {}
    for root in boundary_roots:
        name = os.path.basename(root.rstrip("/")) if root else (
            os.path.basename(os.path.normpath(root_path)) or "root"
        )
        apps_by_root[root] = Application(
            name=name,
            root_path=root,
            has_package_json=(method == "package_json"),
            entry_points=_detect_entry_points(root_path, root),
        )

    shared_jsx: List[str] = []
    shared_js: List[str] = []
    shared_css: List[str] = []

    def assign(files, bucket_attr: str, shared_bucket: List[str]):
        for f in files:
            match = _best_matching_root(f.relative_path, boundary_roots)
            if match is None:
                shared_bucket.append(_normalize(f.relative_path))
            else:
                getattr(apps_by_root[match], bucket_attr).append(_normalize(f.relative_path))

    assign(scan_result.jsx_files, "jsx_files", shared_jsx)
    assign(scan_result.js_files, "js_files", shared_js)
    assign(scan_result.css_files, "css_files", shared_css)

    # FIX (real-world regression found via user testing): a package.json
    # sitting in a tooling-only subfolder (scripts/, functions/, cypress/,
    # storybook/ — all common in real repos) with ZERO css/jsx/js files
    # under it was becoming the ONLY "application" the mapper detected,
    # while the actual app's real source files had no boundary root that
    # matched them and fell into shared_*— where the reachability fallback
    # can't help them (it only indexes files that belong to a real
    # Application), silently resurrecting the "everything looks isolated"
    # bug via a different path. Two-part fix:
    #   1. Drop boundaries that matched zero files — they aren't real
    #      applications, just incidental tooling config.
    #   2. If real project files are STILL left unassigned after that
    #      (because no surviving boundary covers them), give them a
    #      catch-all root-level application instead of leaving them
    #      unassigned — every relevant file should belong to SOME
    #      application whenever boundaries were detected at all.
    non_empty_roots = {
        root for root, app in apps_by_root.items()
        if app.jsx_files or app.js_files or app.css_files
    }
    dropped_empty = [r for r in apps_by_root if r not in non_empty_roots]
    if dropped_empty and method != "single_app_fallback":
        for r in dropped_empty:
            del apps_by_root[r]
        warnings.append(
            f"Ignored {len(dropped_empty)} package.json-based boundary(ies) with no "
            f"CSS/JSX/JS files under them (likely tooling-only folders, e.g. "
            f"scripts/, functions/, cypress/): {dropped_empty}"
        )

    if not apps_by_root:
        # ALL detected package.json boundaries turned out to be empty
        # (tooling-only folders — scripts/, functions/, cypress/, etc.)
        # and NOTHING survived, meaning the real project files have no
        # boundary at all. This is different from the legitimate "shared/
        # folder alongside real app boundaries" case (e.g. spec's admin/
        # customer/shared example) — there, admin/customer DO have real
        # files, so this branch correctly does NOT fire, and shared files
        # stay as shared_* for the reachability graph to resolve via real
        # import evidence. This branch only fires when boundary detection
        # found nothing usable whatsoever, so SOMETHING must still catch
        # these files or they'd be permanently unreachable.
        catch_all_name = os.path.basename(os.path.normpath(root_path)) or "root"
        apps_by_root[""] = Application(
            name=catch_all_name,
            root_path="",
            has_package_json=False,
            entry_points=_detect_entry_points(root_path, ""),
            jsx_files=shared_jsx,
            js_files=shared_js,
            css_files=shared_css,
        )
        warnings.append(
            f"Every detected package.json boundary had zero relevant files — falling back to "
            f"a single catch-all '{catch_all_name}' application at the project root so these "
            f"files still have somewhere reachability analysis can anchor them."
        )
        shared_jsx, shared_js, shared_css = [], [], []

    applications = list(apps_by_root.values())

    if method == "single_app_fallback" and len(applications) == 1:
        warnings.append(
            "No package.json or src/ boundaries detected — treating the entire "
            "upload as a single application. Cross-folder duplicate classes will "
            "still be reported, but as isolated duplicates rather than conflicts "
            "unless import evidence shows they can interact."
        )
    elif len(applications) > 1:
        warnings.append(
            f"Detected {len(applications)} application boundaries "
            f"({', '.join(a.name for a in applications)}) via {method}. "
            f"Same-named CSS classes across these boundaries will only be "
            f"flagged as conflicts if import/reachability evidence shows they "
            f"can affect the same rendering context."
        )

    if shared_css or shared_jsx or shared_js:
        warnings.append(
            f"{len(shared_css)} CSS, {len(shared_jsx)} JSX, {len(shared_js)} JS "
            f"file(s) sit outside every detected application boundary and are "
            f"tracked separately as shared files."
        )

    return CodebaseMap(
        root_path=root_path,
        applications=applications,
        shared_jsx_files=shared_jsx,
        shared_js_files=shared_js,
        shared_css_files=shared_css,
        boundary_detection_method=method,
        warnings=warnings,
    )
