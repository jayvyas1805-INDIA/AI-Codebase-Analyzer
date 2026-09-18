"""
Iterative Fix Loop (new phase, ties fix_planner + patch_generator +
sandbox_validator together).

Spec ref: section 19 (iterative fix loop — "Limit retries to 2-3
attempts. Never allow infinite loops. If all attempts fail: 'AI could not
generate a validated fix.' Show the validation evidence to the user.").

WHY RETRIES TRY DIFFERENT FILES, NOT AN LLM "IMPROVED" PATCH
--------------------------------------------------------------
fix_planner.py already deterministically ranks every candidate file by
blast radius. If the lowest-blast-radius option fails sandbox validation
for some reason (e.g. its rename collides with something), the next
cheapest, still-plausible option is the smallest-blast-radius file we
haven't tried yet — not a re-guess from an LLM. This keeps the same
"never blindly trust generative guessing for what changes" posture as
fix_planner.py and patch_generator.py.

MAX_ATTEMPTS = 3, matching the spec's own "2-3 attempts" ceiling exactly.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from .models import BulkFixIssueResult, BulkFixResult, FixAttempt, FixPlan, FixResult, Issue
from .patch_generator import generate_patch
from .sandbox_validator import validate_patch_in_sandbox
from .fix_planner import plan_fix

MAX_ATTEMPTS = 3

# Sandbox validation used to be the expensive step in a bulk run — a full
# copytree of the project plus a full re-parse/re-analysis pass PER
# ATTEMPT. sandbox_validator.py's incremental path (see its module
# docstring) cut that down to just the file(s) a patch actually touches,
# and skips the Node subprocess entirely when a patch touches no JSX —
# which is the common case for a 0-blast-radius CSS rename. With that
# per-attempt cost down, a single fix is now mostly waiting on an LLM
# response and quick local file I/O rather than a full project
# re-analysis, so more of them can genuinely run at once without
# thrashing the machine. Scales with CPU count (each worker can still
# spawn a short-lived Node process when a patch does touch JSX), capped
# at 12 so a huge/weak box doesn't get pushed into swapping.
DEFAULT_BULK_WORKERS = min(12, max(6, (os.cpu_count() or 4) * 2))


def attempt_validated_fix(issue: Issue, job) -> FixResult:
    base_plan = plan_fix(issue, job)

    if not base_plan.plannable:
        return FixResult(
            issue_id=issue.id,
            success=False,
            attempts=[],
            final_message=base_plan.reason_if_not_plannable or "This issue cannot be auto-fixed.",
        )

    # Try candidate options smallest-blast-radius-first, capped at MAX_ATTEMPTS.
    candidates = sorted(base_plan.options_considered, key=lambda o: o.blast_radius)[:MAX_ATTEMPTS]

    attempts: List[FixAttempt] = []
    for attempt_number, option in enumerate(candidates, start=1):
        candidate_plan = FixPlan(
            issue_id=base_plan.issue_id,
            class_name=base_plan.class_name,
            plannable=True,
            chosen_strategy=option.strategy,
            target_file=option.affected_files[0],
            risk=option.risk,
            blast_radius=option.blast_radius,
            rationale=f"Attempt {attempt_number}/{len(candidates)}: {option.description}",
            options_considered=base_plan.options_considered,
        )

        patch = generate_patch(issue, candidate_plan, job)
        validation = validate_patch_in_sandbox(issue, patch, job)

        attempts.append(
            FixAttempt(
                attempt_number=attempt_number,
                strategy=option.strategy,
                target_file=option.affected_files[0],
                patch=patch,
                validation=validation,
            )
        )

        if validation.passed:
            return FixResult(
                issue_id=issue.id,
                success=True,
                attempts=attempts,
                final_message=(
                    f"Validated fix found on attempt {attempt_number}/{len(candidates)}: "
                    f"{option.description}"
                ),
            )

    return FixResult(
        issue_id=issue.id,
        success=False,
        attempts=attempts,
        final_message=(
            f"AI could not generate a validated fix after {len(attempts)} attempt(s). "
            f"See each attempt's validation evidence for why it was rejected."
        ),
    )


def _process_one_issue_for_bulk(issue: Issue, job) -> BulkFixIssueResult:
    """
    One issue's plan -> patch -> sandbox-validate loop, exactly like the
    sequential bulk-fix path did — this is what a worker thread runs.
    Safe to call from multiple threads concurrently: each issue only ever
    writes to its OWN issue.id key in job.last_plan/last_patch/
    last_validation/last_fix_result (different threads never touch the
    same key), and job.root_path is only ever READ — every sandbox
    validation works on its own throwaway tempdir copy, never on shared
    state, so there's nothing for two threads to collide on.
    """
    plan = plan_fix(issue, job)
    job.last_plan[issue.id] = plan

    if not plan.plannable:
        return BulkFixIssueResult(
            issue_id=issue.id,
            class_name=issue.class_name,
            plannable=False,
            success=False,
            message=plan.reason_if_not_plannable or "This issue type cannot be auto-fixed.",
        )

    fix_result = attempt_validated_fix(issue, job)
    job.last_fix_result[issue.id] = fix_result
    if fix_result.attempts:
        job.last_patch[issue.id] = fix_result.attempts[-1].patch
        job.last_validation[issue.id] = fix_result.attempts[-1].validation

    return BulkFixIssueResult(
        issue_id=issue.id,
        class_name=issue.class_name,
        plannable=True,
        success=fix_result.success,
        message=fix_result.final_message,
    )


def attempt_validated_fix_all(
    job,
    job_id: str,
    max_workers: int = DEFAULT_BULK_WORKERS,
    progress: Optional[dict] = None,
) -> BulkFixResult:
    """
    Runs attempt_validated_fix() above for EVERY issue in the job, up to
    `max_workers` at once, instead of requiring a manual "Fix" click per
    issue (or waiting on them strictly one-after-another) — the whole
    point when a project surfaces hundreds of findings at once.

    Each issue is still planned, patched, and sandbox-validated exactly
    like the single-issue path (nothing here loosens that safety net —
    see sandbox_validator.py and fix_planner.py's docstrings for why that
    matters, and _process_one_issue_for_bulk's docstring for why running
    this concurrently is safe). Parallelism only changes HOW MANY issues
    are in flight at once, never what a single issue's fix must pass.

    Caches job.last_plan / last_patch / last_validation / last_fix_result
    per issue exactly like the sequential version did, so a following
    /api/fix-all/{job_id}/download call (or even a single-issue
    /api/fix/{job_id}/{issue_id} call afterwards) can reuse this work
    instead of redoing it.

    If `progress` is given (a plain dict), it's updated after every issue
    finishes with the running totals: "processed", "fixed", "failed",
    "skipped". main.py's /api/fix-all/{job_id}/start hands this same dict
    to GET /api/fix-all/{job_id}/progress, so the frontend can poll real
    state — "312 of 528 done" — instead of staring at a single button for
    however long the whole run takes.
    """
    results: List[BulkFixIssueResult] = []
    fixed = failed = skipped = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_issue = {pool.submit(_process_one_issue_for_bulk, issue, job): issue for issue in job.issues}

        for future in as_completed(future_to_issue):
            issue = future_to_issue[future]
            try:
                result = future.result()
            except Exception as e:
                # A crash fixing ONE issue (e.g. a transient sandbox I/O
                # error) must never take the whole bulk run down with it —
                # record it as a failure for that issue and keep going.
                result = BulkFixIssueResult(
                    issue_id=issue.id,
                    class_name=issue.class_name,
                    plannable=True,
                    success=False,
                    message=f"Unexpected error while fixing this issue: {e}",
                )

            with lock:
                results.append(result)
                if not result.plannable:
                    skipped += 1
                elif result.success:
                    fixed += 1
                else:
                    failed += 1

                if progress is not None:
                    progress["processed"] = len(results)
                    progress["fixed"] = fixed
                    progress["failed"] = failed
                    progress["skipped"] = skipped

    return BulkFixResult(
        job_id=job_id,
        total_issues=len(job.issues),
        plannable_issues=fixed + failed,
        fixed_count=fixed,
        failed_count=failed,
        skipped_count=skipped,
        results=results,
    )
