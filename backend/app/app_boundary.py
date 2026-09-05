"""
Application / Project Boundary Detection (Phase 8).

A single uploaded zip may contain multiple independent React applications
(a monorepo: admin/, customer/, landing-page/, each with their own
package.json). Treating the whole zip as one flat app is exactly what
causes false-positive conflicts — the same class name existing in two
unrelated apps is not automatically a real conflict.

This module answers ONE question: which files belong to which application?
It uses package.json LOCATION as the boundary signal, per the spec — each
package.json marks the root of one independent app. Files that sit outside
every app-rooted folder (e.g. a top-level "shared/" directory alongside
"admin/" and "customer/") are tagged as belonging to a synthetic "shared"
pseudo-application.

IMPORTANT — this module does NOT decide reachability or conflicts. It only
answers "which app owns this file". Whether a "shared" file (or even a
file from a DIFFERENT real app) can actually affect a given component is
determined later by the import/reachability graph (Phase 9), because a
relative import can technically cross folder boundaries regardless of
which app "owns" the file.
"""
import json
import os
from typing import Dict, List, Optional

from .models import Application, SHARED_APP_NAME


def detect_applications(
    project_root_abs: str, package_json_relative_paths: List[str]
) -> List[Application]:
    """
    Returns one Application per package.json found, PLUS a synthetic
    "shared" pseudo-application (name=SHARED_APP_NAME) representing files
    that don't belong to any app-rooted folder.

    If NO package.json exists anywhere (a plain single-app project, like
    our original sample_project fixture), returns a single Application
    covering the whole project — this keeps non-monorepo projects working
    exactly as before, with no behavior change.
    """
    if not package_json_relative_paths:
        return [Application(name="app", root_path="", package_json_path=None)]

    applications: List[Application] = []
    for pkg_path in sorted(package_json_relative_paths):
        pkg_path_norm = pkg_path.replace(os.sep, "/")
        root_path = os.path.dirname(pkg_path_norm)
        name = _read_package_name(os.path.join(project_root_abs, pkg_path)) or (
            os.path.basename(root_path) if root_path else "root"
        )
        applications.append(
            Application(name=name, root_path=root_path, package_json_path=pkg_path_norm)
        )

    applications.append(Application(name=SHARED_APP_NAME, root_path="", package_json_path=None))
    return applications


def _read_package_name(package_json_abs_path: str) -> Optional[str]:
    try:
        with open(package_json_abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("name")
        return name if isinstance(name, str) and name.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def assign_file_to_application(
    relative_file_path: str, applications: List[Application]
) -> Application:
    """
    Finds the NEAREST ancestor application root for a file — the app whose
    root_path is the longest matching prefix of the file's directory. This
    correctly handles nested package.json files (a workspace root plus
    per-app package.json inside it): a file under "admin/src/" matches
    "admin" (more specific) over "" (the workspace root), even if both
    are registered applications.

    Falls back to the shared pseudo-app if no real app root matches.
    """
    file_dir = os.path.dirname(relative_file_path).replace(os.sep, "/")

    best_match: Optional[Application] = None
    best_match_len = -1

    for app in applications:
        if app.name == SHARED_APP_NAME:
            continue

        root = app.root_path
        if root == "":
            matches = True
            match_len = 0
        else:
            matches = file_dir == root or file_dir.startswith(root + "/")
            match_len = len(root)

        if matches and match_len > best_match_len:
            best_match = app
            best_match_len = match_len

    if best_match is not None:
        return best_match

    shared = next((a for a in applications if a.name == SHARED_APP_NAME), None)
    return shared if shared is not None else applications[0]


def build_file_application_map(
    relative_file_paths: List[str], applications: List[Application]
) -> Dict[str, Application]:
    """Convenience: assigns every given file path to its owning Application in one pass."""
    return {path: assign_file_to_application(path, applications) for path in relative_file_paths}
