"""
Handles turning an uploaded .zip into a safely-extracted folder on disk.
"""
import os
import uuid
import zipfile
from typing import Tuple

from .config import WORKSPACE_DIR, MAX_UNCOMPRESSED_SIZE_MB


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
    Extracts a zip file, guarding against two classes of malicious zip:

    1. "Zip slip": internal filenames containing "../" sequences designed
       to write files OUTSIDE the intended folder. Every entry's resolved
       path is checked to stay inside extract_to/source before extracting
       anything.
    2. "Zip bomb": a small COMPRESSED file that decompresses to an
       enormous size, exhausting disk space. zipfile's own directory
       listing (ZipInfo.file_size, the DECLARED uncompressed size) is
       summed and checked against MAX_UNCOMPRESSED_SIZE_MB BEFORE any
       extraction happens — so a bomb is rejected in milliseconds, not
       after it's already filled the disk. (This trusts the zip's
       declared sizes rather than re-verifying by decompressing, which is
       the same tradeoff most zip-bomb defenses make — an attacker could
       lie about file_size, but a corrupted/truncated result from that is
       caught by CRC validation during the real extractall() below rather
       than silently accepted.)

    Returns the path that should be treated as the project's root folder
    (handles the common case where the zip contains one top-level folder,
    e.g. "my-app/", so we scan inside it rather than one level too high).
    """
    source_dir = os.path.join(extract_to, "source")
    os.makedirs(source_dir, exist_ok=True)
    source_dir_abs = os.path.abspath(source_dir)

    with zipfile.ZipFile(zip_path, "r") as zf:
        total_uncompressed = sum(member.file_size for member in zf.infolist())
        max_bytes = MAX_UNCOMPRESSED_SIZE_MB * 1024 * 1024
        if total_uncompressed > max_bytes:
            raise ValueError(
                f"Zip rejected: would extract to "
                f"{total_uncompressed / (1024 * 1024):.1f} MB, exceeding the "
                f"{MAX_UNCOMPRESSED_SIZE_MB} MB limit. If this is a legitimate "
                f"large project, raise MAX_UNCOMPRESSED_SIZE_MB."
            )

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