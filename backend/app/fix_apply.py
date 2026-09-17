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
from typing import Dict, List, Tuple

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


# ---- Bulk fix (new) ----
# Same idea as above, but for downloading ALL successfully-fixed issues
# from a job at once (see fix_loop.py's attempt_validated_fix_all() and
# main.py's /api/fix-all/{job_id}/download) instead of one .zip per issue.

def _merge_patch_changes(patches) -> Tuple[Dict[str, list], List[str]]:
    """
    Collects every PatchFileChange from every patch, grouped by file path,
    and returns (merged_changes, conflict_notes).

    Each patch's line numbers were computed against the ORIGINAL file
    (patch_generator.py always reads from job.root_path fresh), so changes
    from DIFFERENT patches touching the SAME file can be safely combined
    into one bottom-up splice pass over that file's original lines —
    exactly like a single patch's own changes already are (see
    _apply_patch_to_disk above) — as long as their line ranges don't
    overlap each other.

    Two issues' fixes overlapping on the exact same line(s) should be rare
    (fix_planner.py plans one class name's rename per issue, and
    patch_generator.py already refuses to touch a line with more than one
    match), but this is the bulk path applying MANY patches unattended, so
    it never guesses: any change whose line range overlaps one already
    accepted for that file is dropped and reported in conflict_notes
    rather than risking a corrupted file. The rest of that same patch
    still applies fine — only the overlapping line is skipped.
    """
    per_file: Dict[str, list] = {}
    for patch in patches:
        for pf in patch.files:
            per_file.setdefault(pf.path, []).extend(pf.changes)

    merged: Dict[str, list] = {}
    conflicts: List[str] = []
    for path, changes in per_file.items():
        # Earliest start_line first, so we can detect overlaps in one pass.
        ordered = sorted(changes, key=lambda c: c.start_line)
        accepted = []
        last_end = 0
        for change in ordered:
            if change.start_line <= last_end:
                conflicts.append(
                    f"{path}:{change.start_line}-{change.end_line} overlaps another "
                    f"fix's change in this bulk run — skipped to avoid corrupting the file. "
                    f"Fix this one individually instead."
                )
                continue
            accepted.append(change)
            last_end = change.end_line
        if accepted:
            merged[path] = accepted

    return merged, conflicts


def apply_patches_to_project_copy(job, patches) -> Tuple[str, List[str]]:
    """
    Like apply_patch_to_project_copy() above, but for many patches at
    once — one fresh copy of the project, every patch's changes applied
    to it in a single pass per file. Returns (project_copy_path, conflict_notes).
    """
    if not job.root_path or not os.path.isdir(job.root_path):
        raise ValueError(
            "Original project source is unavailable for this job — cannot build a "
            "fixed-project download. (Was the job's workspace cleaned up?)"
        )
    if not patches:
        raise ValueError("No successful patches were given — nothing to apply or download.")

    merged, conflicts = _merge_patch_changes(patches)
    if not merged:
        raise ValueError("None of the given patches had any applicable file changes.")

    tmp_dir = tempfile.mkdtemp(prefix="fixed_project_all_", dir=WORKSPACE_DIR)
    project_copy = os.path.join(tmp_dir, "project")
    shutil.copytree(job.root_path, project_copy)

    for rel_path, changes in merged.items():
        abs_path = os.path.join(project_copy, rel_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for change in sorted(changes, key=lambda c: -c.start_line):
            new_lines = [change.replacement + "\n"] if change.replacement else []
            lines[change.start_line - 1: change.end_line] = new_lines
        with open(abs_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    return project_copy, conflicts


def build_bulk_fixed_project_zip(job, patches, job_id: str) -> Tuple[str, List[str]]:
    """
    Applies every successful patch from a bulk fix run to ONE fresh copy
    of the project and zips it. Returns (zip_path, conflict_notes) — any
    entries in conflict_notes describe changes that were skipped because
    two issues' fixes overlapped on the same line(s); everything else in
    the zip was applied.
    """
    project_copy, conflicts = apply_patches_to_project_copy(job, patches)
    try:
        zip_path = os.path.join(WORKSPACE_DIR, job_id, "fixed_project_all.zip")
        zip_directory(project_copy, zip_path)
        return zip_path, conflicts
    finally:
        shutil.rmtree(os.path.dirname(project_copy), ignore_errors=True)
