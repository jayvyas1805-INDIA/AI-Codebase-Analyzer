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
from typing import List

from .models import BulkFixIssueResult, BulkFixResult, FixAttempt, FixPlan, FixResult, Issue
from .patch_generator import generate_patch
from .sandbox_validator import validate_patch_in_sandbox
from .fix_planner import plan_fix

MAX_ATTEMPTS = 3


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


def attempt_validated_fix_all(job, job_id: str) -> BulkFixResult:
    """
    Runs attempt_validated_fix() above for EVERY issue in the job, one
    after another, instead of requiring a manual "Fix" click per issue —
    the whole point when a project surfaces hundreds of findings at once.

    Each issue is still planned, patched, and sandbox-validated exactly
    like the single-issue path (nothing here loosens that safety net —
    see sandbox_validator.py and fix_planner.py's docstrings for why that
    matters). This function only removes the need to trigger that loop
    one issue at a time; it does not skip any of its checks.

    Caches job.last_plan / last_patch / last_validation / last_fix_result
    per issue exactly like the single-issue endpoint and chat_commands.py's
    "Fix it" handler do, so a following /api/fix-all/{job_id}/download call
    (or even a single-issue /api/fix/{job_id}/{issue_id} call afterwards)
    can reuse this work instead of redoing it.

    Note this is inherently sequential — each issue may involve its own
    LLM call (ai_rename_suggester.py) and its own full re-analysis pass
    (sandbox_validator.py) — so for a project with hundreds of issues this
    can take a while. It still completes deterministically; there's no
    retry-forever risk since each issue is itself capped at MAX_ATTEMPTS.
    """
    results: List[BulkFixIssueResult] = []
    fixed = failed = skipped = 0

    for issue in job.issues:
        plan = plan_fix(issue, job)
        job.last_plan[issue.id] = plan

        if not plan.plannable:
            skipped += 1
            results.append(
                BulkFixIssueResult(
                    issue_id=issue.id,
                    class_name=issue.class_name,
                    plannable=False,
                    success=False,
                    message=plan.reason_if_not_plannable or "This issue type cannot be auto-fixed.",
                )
            )
            continue

        fix_result = attempt_validated_fix(issue, job)
        job.last_fix_result[issue.id] = fix_result
        if fix_result.attempts:
            job.last_patch[issue.id] = fix_result.attempts[-1].patch
            job.last_validation[issue.id] = fix_result.attempts[-1].validation

        if fix_result.success:
            fixed += 1
        else:
            failed += 1

        results.append(
            BulkFixIssueResult(
                issue_id=issue.id,
                class_name=issue.class_name,
                plannable=True,
                success=fix_result.success,
                message=fix_result.final_message,
            )
        )

    return BulkFixResult(
        job_id=job_id,
        total_issues=len(job.issues),
        plannable_issues=fixed + failed,
        fixed_count=fixed,
        failed_count=failed,
        skipped_count=skipped,
        results=results,
    )
