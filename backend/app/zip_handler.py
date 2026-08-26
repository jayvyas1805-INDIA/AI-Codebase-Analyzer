"""
Handles turning an uploaded .zip into a safely-extracted folder on disk.
"""
import os
import uuid
import zipfile
from typing import Tuple

from .config import WORKSPACE_DIR


def create_job_workspace() -> Tuple[str, str]:
    """
    Creates a unique folder for this upload so concurrent/repeated uploads
    never overwrite each other. Returns (job_id, job_dir).
    """
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(WORKSPACE_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_id, job_dir


def safe_extract_zip(zip_path: str, extract_to: str) -> str:
    """
    Extracts a zip file, guarding against "zip slip": a malicious zip whose
    internal filenames contain "../" sequences designed to write files
    OUTSIDE the intended folder. We check every entry's resolved path stays
    inside extract_to/source before extracting anything.

    Returns the path that should be treated as the project's root folder
    (handles the common case where the zip contains one top-level folder,
    e.g. "my-app/", so we scan inside it rather than one level too high).
    """
    source_dir = os.path.join(extract_to, "source")
    os.makedirs(source_dir, exist_ok=True)
    source_dir_abs = os.path.abspath(source_dir)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            member_path = os.path.normpath(os.path.join(source_dir_abs, member))
            if not member_path.startswith(source_dir_abs):
                raise ValueError(f"Unsafe zip entry rejected: {member}")
        zf.extractall(source_dir)

    entries = [e for e in os.listdir(source_dir) if not e.startswith("__MACOSX")]
    if len(entries) == 1:
        candidate = os.path.join(source_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate

    return source_dir
