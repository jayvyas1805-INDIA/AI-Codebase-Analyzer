"""
Chat Commands (new phase, sits in front of chat.py's free-form LLM chat).

Spec ref: sections 20 (issue-aware AI chat) and 21 (chat -> action).

WHY THIS EXISTS AS A SEPARATE ROUTER, NOT MORE LLM PROMPTING
----------------------------------------------------------------
Spec section 21 lists exact commands — "Generate a fix.", "Validate the
fix.", "Fix it." — that must trigger REAL backend work (a real patch, a
real sandbox run), not a plausible-sounding LLM description of one. The
local model this project uses (Ollama) is called here with plain prompts,
not a tool-calling API, so there's no reliable way to have it decide "call
plan_fix() now" and actually invoke real Python. Instead, this module
matches the message text directly against the spec's own command list and
dispatches straight to Phase 5/6's real functions. Only genuinely
open-ended questions ("why is this a conflict?", "why isn't this OTHER
class a conflict?") fall through to the free-form LLM chat in chat.py,
which already has the full Phase 4 context to answer them correctly.

This keeps the boundary spec section 12 draws intact: the LLM explains
and discusses; it never gets to be the source of truth for what a patch
contains or whether a fix validated.

COMMANDS HANDLED HERE (all deterministic, no LLM call)
---------------------------------------------------------
  "Which component is affected?"  -> lists JSX components/files from the issue
  "Show me the files involved."    -> lists every CSS/JSX file involved
  "What is the safest fix?"        -> runs fix_planner.plan_fix(), summarizes it
  "Generate a fix."                -> plan + patch, shows the line-level diff
  "Validate the fix."              -> sandbox-validates the last generated patch
  "Why did the fix fail?"          -> replays the last validation's notes
  "Fix it."                        -> the full plan->patch->validate->retry loop

Anything else (including "Explain this issue.", which the UI's own
[Analyze with AI] button already covers via /api/explain) returns None,
telling the caller to fall through to continue_chat().
"""
import re
from typing import Optional

from .fix_planner import plan_fix
from .patch_generator import generate_patch
from .sandbox_validator import validate_patch_in_sandbox
from .fix_loop import attempt_validated_fix
from .models import Patch


def detect_command(message: str) -> Optional[str]:
    text = message.strip().lower()

    if re.search(r"\bwhy\b.*\bfail", text):
        return "why_failed"
    if text in {"fix it", "fix it.", "fix this", "fix this."} or re.search(r"\bfix it\b", text):
        return "fix_it"
    if "validate" in text and "fix" in text:
        return "validate_fix"
    if "generate" in text and "fix" in text:
        return "generate_fix"
    if "safest" in text and "fix" in text:
        return "safest_fix"
    if re.search(r"which component|what component|affected component", text):
        return "which_component"
    if re.search(r"show.*files?|which files|what files", text):
        return "show_files"
    return None  # fall through to free-form LLM chat


def _format_diff(patch: Patch) -> str:
    if not patch.files:
        return "(no file changes)"
    lines = []
    for pf in patch.files:
        lines.append(f"\n`{pf.path}`:")
        for c in pf.changes:
            if c.replacement:
                lines.append(f"  line {c.start_line}: `{c.original}` -> `{c.replacement}`")
            else:
                lines.append(f"  lines {c.start_line}-{c.end_line} removed: `{c.original}`")
    if patch.manual_review_needed:
        lines.append("\nNeeds manual review (skipped automatically):")
        for note in patch.manual_review_needed:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _handle_which_component(issue, job) -> str:
    components = sorted({u.file_path for u in issue.jsx_usages})
    if not components:
        return "No JSX component in the scanned project uses this class as a static className."
    lines = [f"Component(s) affected by '.{issue.class_name}':"]
    for c in components:
        lines.append(f"  - {c}")
    return "\n".join(lines)


def _handle_show_files(issue, job) -> str:
    css_files = sorted({d.file_path for d in issue.css_definitions})
    jsx_files = sorted({u.file_path for u in issue.jsx_usages})
    lines = ["Files involved in this issue:"]
    if css_files:
        lines.append("  CSS:")
        lines.extend(f"    - {f}" for f in css_files)
    if jsx_files:
        lines.append("  JSX:")
        lines.extend(f"    - {f}" for f in jsx_files)
    if not css_files and not jsx_files:
        lines.append("  (none recorded for this issue)")
    return "\n".join(lines)


def _handle_safest_fix(issue, job) -> str:
    plan = plan_fix(issue, job)
    job.last_plan[issue.id] = plan
    if not plan.plannable:
        return f"No fix is proposed here: {plan.reason_if_not_plannable}"
    lines = [
        f"Safest fix: {plan.chosen_strategy} on '{plan.target_file}' "
        f"(blast radius {plan.blast_radius}, risk {plan.risk}).",
        plan.rationale or "",
    ]
    if len(plan.options_considered) > 1:
        lines.append("\nOther options considered:")
        for o in plan.options_considered:
            if o.affected_files and o.affected_files[0] == plan.target_file:
                continue
            lines.append(f"  - {o.strategy} on '{o.affected_files[0]}' (blast radius {o.blast_radius}, risk {o.risk})")
    return "\n".join(lines)


def _handle_generate_fix(issue, job) -> str:
    plan = plan_fix(issue, job)
    job.last_plan[issue.id] = plan
    if not plan.plannable:
        return f"Can't generate a fix here: {plan.reason_if_not_plannable}"

    patch = generate_patch(issue, plan, job)
    job.last_patch[issue.id] = patch

    if not patch.valid:
        return (
            f"Patch generation failed validation before even reaching the sandbox: "
            f"{'; '.join(patch.validation_errors)}"
        )

    return (
        f"Proposed fix ({plan.chosen_strategy}, risk {plan.risk}, "
        f"blast radius {plan.blast_radius}):\n{_format_diff(patch)}\n\n"
        f"This has NOT been applied or validated yet — say \"Validate the fix\" "
        f"to sandbox-test it, or \"Fix it\" to run the full plan-patch-validate loop."
    )


def _handle_validate_fix(issue, job) -> str:
    patch = job.last_patch.get(issue.id)
    if patch is None:
        plan = plan_fix(issue, job)
        job.last_plan[issue.id] = plan
        if not plan.plannable:
            return f"Nothing to validate: {plan.reason_if_not_plannable}"
        patch = generate_patch(issue, plan, job)
        job.last_patch[issue.id] = patch

    if not patch.valid:
        return f"Can't validate — the patch itself is invalid: {'; '.join(patch.validation_errors)}"

    validation = validate_patch_in_sandbox(issue, patch, job)
    job.last_validation[issue.id] = validation

    status = "PASSED" if validation.passed else "FAILED"
    lines = [f"Sandbox validation: {status}"]
    lines.extend(f"  - {n}" for n in validation.notes)
    lines.append(
        f"  before: {validation.before_summary}  |  after: {validation.after_summary}"
    )
    if not validation.passed:
        lines.append(
            "This patch was NOT applied. Say \"Fix it\" to have the system try the "
            "next-safest alternative instead."
        )
    return "\n".join(lines)


def _handle_why_failed(issue, job) -> str:
    validation = job.last_validation.get(issue.id)
    fix_result = job.last_fix_result.get(issue.id)

    if fix_result is not None and not fix_result.success:
        lines = [fix_result.final_message, ""]
        for attempt in fix_result.attempts:
            lines.append(
                f"Attempt {attempt.attempt_number} ({attempt.strategy} on '{attempt.target_file}'): "
                f"{'PASSED' if attempt.validation.passed else 'FAILED'}"
            )
            lines.extend(f"  - {n}" for n in attempt.validation.notes)
        return "\n".join(lines)

    if validation is None:
        return "No fix has been validated yet for this issue — say \"Generate a fix\" or \"Fix it\" first."
    if validation.passed:
        return "The last validated fix actually PASSED — nothing failed. Say \"Fix it\" to see the applied result."
    return "The last validation failed for this reason:\n" + "\n".join(f"  - {n}" for n in validation.notes)


def _handle_fix_it(issue, job) -> str:
    result = attempt_validated_fix(issue, job)
    job.last_fix_result[issue.id] = result
    if result.attempts:
        job.last_patch[issue.id] = result.attempts[-1].patch
        job.last_validation[issue.id] = result.attempts[-1].validation

    lines = [result.final_message]
    if result.success:
        winning = next(a for a in result.attempts if a.validation.passed)
        lines.append(_format_diff(winning.patch))
        lines.append(
            "\nThis fix has been VALIDATED in a sandbox but NOT applied to your actual "
            "project — review the diff above and apply it yourself, or use the "
            "[Accept Fix] action in the UI if available."
        )
    else:
        lines.append("\nEvidence from each attempt:")
        for attempt in result.attempts:
            lines.append(f"  Attempt {attempt.attempt_number} ({attempt.strategy} on '{attempt.target_file}'):")
            lines.extend(f"    - {n}" for n in attempt.validation.notes)
    return "\n".join(lines)


_HANDLERS = {
    "which_component": _handle_which_component,
    "show_files": _handle_show_files,
    "safest_fix": _handle_safest_fix,
    "generate_fix": _handle_generate_fix,
    "validate_fix": _handle_validate_fix,
    "why_failed": _handle_why_failed,
    "fix_it": _handle_fix_it,
}


def handle_chat_message(issue, job, message: str) -> Optional[str]:
    """
    Returns a deterministic reply string if `message` matched one of the
    spec's action commands, or None if the caller should fall through to
    continue_chat() (free-form LLM discussion, grounded in Phase 4's
    context).
    """
    command = detect_command(message)
    if command is None:
        return None
    return _HANDLERS[command](issue, job)
