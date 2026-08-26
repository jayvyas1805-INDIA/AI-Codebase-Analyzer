"""
The Project Scanner (Phase 1).

Its ONLY job right now: walk a folder, find every .jsx/.js/.css file,
skip irrelevant folders, and return a structured inventory.

It does NOT read file contents, parse CSS/JSX, or detect issues —
that's later phases. Keeping this phase "dumb" on purpose makes it easy
to test in isolation.
"""
import os
from typing import List

from .config import ALLOWED_EXTENSIONS, IGNORED_DIRS
from .models import ScannedFile, ScanResult


def scan_project(root_path: str, job_id: str) -> ScanResult:
    if not os.path.isdir(root_path):
        raise ValueError(f"Path does not exist or is not a directory: {root_path}")

    jsx_files: List[ScannedFile] = []
    js_files: List[ScannedFile] = []
    css_files: List[ScannedFile] = []
    warnings: List[str] = []

    for current_dir, dirnames, filenames in os.walk(root_path):
        # Mutating dirnames in-place is how os.walk lets you prune branches —
        # this stops it from ever descending into node_modules, .git, etc.
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue

            abs_path = os.path.join(current_dir, filename)
            rel_path = os.path.relpath(abs_path, root_path)
            size = os.path.getsize(abs_path)

            scanned = ScannedFile(
                relative_path=rel_path,
                absolute_path=abs_path,
                file_type=ext.lstrip("."),
                size_bytes=size,
            )

            if ext == ".jsx":
                jsx_files.append(scanned)
            elif ext == ".js":
                js_files.append(scanned)
            elif ext == ".css":
                css_files.append(scanned)

    total = len(jsx_files) + len(js_files) + len(css_files)

    if total == 0:
        warnings.append("No .jsx, .js, or .css files found. Is this a valid React project?")
    if len(css_files) == 0:
        warnings.append("No CSS files found — conflict detection will have nothing to analyze.")
    if len(jsx_files) == 0:
        warnings.append("No .jsx files found — this may not be a component-based React project.")

    return ScanResult(
        job_id=job_id,
        root_path=root_path,
        total_files_scanned=total,
        jsx_files=jsx_files,
        js_files=js_files,
        css_files=css_files,
        warnings=warnings,
    )
