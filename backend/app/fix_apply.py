"""
Turns a validated Patch (see patch_generator.py / fix_loop.py) into a
downloadable .zip of the FIXED project.

WHY THIS IS SEPARATE FROM sandbox_validator.py
-------------------------------------------------
sandbox_validator.py already applies a patch to a throwaway temp copy to
re-run the analyzer and check the fix actually works — but it deletes
that copy (`shutil.rmtree(tmp_dir, ...)` in its `finally` block) the
moment validation finishes, and it never touches the real upload. That's
correct for validation (spec section 24: the frontend must get explicit
user approval before anything real changes), but it means a passing
/api/fix response, on its own, never hands the user anything they can
actually download and use — the "fixed" project only ever existed for a
few milliseconds in a temp folder.

This module is the explicit, opt-in next step: given a job and a patch
that has ALREADY passed sandbox validation (the caller's job — see
main.py's /api/fix/{job_id}/{issue_id}/download), it:
  1. Copies the ORIGINAL uploaded project (job.root_path) into a fresh
     folder — the real upload on disk is still never mutated in place.
  2. Applies the patch's line-level changes to that copy, the same
     bottom-up line-splice sandbox_validator.py uses (so line numbers
     from earlier changes in the same file stay valid).
  3. Zips the result (via zip_handler.zip_directory) and returns the
     .zip's path for main.py to stream back as a file download.

Nothing here plans a fix or decides what changes — that's still entirely
fix_planner.py + patch_generator.py's job. This module only ever applies
a patch that already exists.
"""
import os
import shutil
import tempfile

from .config import WORKSPACE_DIR
from .zip_handler import zip_directory


def _apply_patch_to_disk(project_root: str, patch) -> None:
    """Same bottom-up line-splice sandbox_validator.py uses, so identical
    behavior whether a patch is being test-applied in a sandbox or
    actually applied here for download."""
    for pf in patch.files:
        abs_path = os.path.join(project_root, pf.path)
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for change in sorted(pf.changes, key=lambda c: -c.start_line):
            new_lines = [change.replacement + "\n"] if change.replacement else []
            lines[change.start_line - 1: change.end_line] = new_lines
        with open(abs_path, "w", encoding="utf-8") as f:
            f.writelines(lines)


def apply_patch_to_project_copy(job, patch) -> str:
    """
    Copies job.root_path into a fresh temp folder and applies `patch` to
    that copy. Returns the copy's root path. Raises ValueError if the
    original project source isn't available (e.g. workspace was cleaned
    up) or the patch has no file changes to apply.
    """
    if not job.root_path or not os.path.isdir(job.root_path):
        raise ValueError(
            "Original project source is unavailable for this job — cannot build a "
            "fixed-project download. (Was the job's workspace cleaned up?)"
        )
    if not patch.files:
        raise ValueError("This patch has no file changes — nothing to apply or download.")

    tmp_dir = tempfile.mkdtemp(prefix="fixed_project_", dir=WORKSPACE_DIR)
    project_copy = os.path.join(tmp_dir, "project")
    shutil.copytree(job.root_path, project_copy)
    _apply_patch_to_disk(project_copy, patch)
    return project_copy


def build_fixed_project_zip(job, patch, issue_id: str, job_id: str) -> str:
    """
    Applies `patch` to a fresh copy of the project and zips it. The zip
    is written under the job's own workspace folder (WORKSPACE_DIR/{job_id}/),
    so it's cleaned up the same way the rest of that job's workspace is.
    Returns the zip's absolute path.
    """
    project_copy = apply_patch_to_project_copy(job, patch)
    try:
        zip_path = os.path.join(WORKSPACE_DIR, job_id, f"fixed_{issue_id}.zip")
        zip_directory(project_copy, zip_path)
        return zip_path
    finally:
        # The loose copy on disk is only an intermediate step — once it's
        # zipped, only the .zip needs to stick around for the download.
        shutil.rmtree(os.path.dirname(project_copy), ignore_errors=True)
