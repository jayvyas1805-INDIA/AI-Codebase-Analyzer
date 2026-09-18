"""
LLM-Assisted Class Naming for rename_scoped_class fixes (Track 3).

WHY THIS IS THE ONLY PLACE AN LLM TOUCHES THE FIX PIPELINE
-------------------------------------------------------------
fix_planner.py already decides WHAT to do (rename vs. consolidate) and
WHICH file to touch, entirely deterministically — see that module's
docstring for why: those are judgment calls with real evidence behind
them (blast radius), and getting them wrong risks breaking working code.

NAMING CONVENTION: filename_classname
----------------------------------------
Every renamed class is scoped to the file it lives in by prefixing the
original class name with a sanitized, snake_case version of that file's
name, e.g. ".panel" in "Dashboard.css" -> ".dashboard_panel". This makes
conflicts self-explanatory at a glance (you can tell WHERE a class came
from just by reading it) and, because it always incorporates the
original class name unchanged, it can never collide with an unrelated
class in the same file.

The LLM's job here is narrow and low-stakes: turn a messy real-world file
name (mixed case, spaces, numbers, punctuation) into a clean snake_case
slug — something a hardcoded heuristic can do but sometimes does
awkwardly (e.g. "OrderSummaryV2.css" -> "order_summary_v2" vs. a naive
lowercase() giving "ordersummaryv2"). It is NEVER allowed to invent a
different naming scheme, drop the original class name, or change which
file/line gets touched; the final name is only ever accepted if it is
`<slug>_<original_class_name>`. Anything else is rejected outright.

INVARIANT PRESERVED: the LLM only ever proposes a STRING, never a file, a
line number, or a diff. patch_generator.py still generates the actual
patch, and still runs whatever name comes back through the SAME
collision-avoidance suffixing (`_dedupe_name`) regardless of whether the
name came from here or the mechanical fallback — so uniqueness is
guaranteed deterministically either way. If the LLM is unavailable,
misconfigured, times out, or returns something that doesn't follow the
filename_classname convention, this fails SOFTLY back to None — renaming
still works with zero LLM involvement, exactly like before this module
existed, using the same convention computed mechanically instead.
"""
import re
from typing import Optional

from .ai_context_builder import build_issue_context
from .llm_client import call_llm_chat

# snake_case, must start with a letter — a valid, boring, safe CSS
# identifier. Deliberately stricter than CSS actually allows (no leading
# digits/hyphens, no camelCase) so every accepted suggestion reads
# consistently with the filename_classname convention used everywhere else.
VALID_CLASS_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
MAX_NAME_LENGTH = 60


def _to_snake_case(s: str) -> str:
    """'SidebarPanel' -> 'sidebar_panel', not 'sidebarpanel' — a plain
    .lower() would silently destroy word boundaries. Also normalizes any
    non-alphanumeric run (spaces, dashes, dots, version markers, etc.)
    into a single underscore, so real-world file names slug cleanly."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    return s.lower().strip("_")


def _file_stem_slug(css_file_path: str) -> str:
    """'admin/src/components/OrderSummaryV2.css' -> 'order_summary_v2'

    Splits on both '/' and '\\' for the same reason _component_stem() in
    fix_planner.py does — see that docstring. _to_snake_case() below would
    eventually turn a stray backslash into an underscore too, but doing it
    here keeps this function's contract explicit rather than relying on
    that as an incidental side effect.
    """
    base = re.split(r"[\\/]", css_file_path)[-1]
    stem = base.rsplit(".", 1)[0]
    return _to_snake_case(stem)


def suggest_class_name(issue, plan, job) -> Optional[str]:
    """
    Returns a validated `<file_slug>_<class_name>` string, or None if the
    LLM is unavailable/misconfigured or its response didn't follow the
    filename_classname convention. Callers MUST fall back to the existing
    mechanical name (patch_generator.py's _unique_new_name) when this
    returns None — see module docstring for why that fallback is safe.
    """
    target_file = plan.target_file
    mechanical_slug = _file_stem_slug(target_file)
    expected_suffix = f"_{issue.class_name}"

    system_prompt = (
        "You clean up file names into snake_case slugs for a CSS class-"
        "naming tool. Given a file path and a CSS class name, respond with "
        "ONLY the new class name in the exact form "
        f"'<slug>{expected_suffix}' — the sanitized, lowercase, "
        "snake_case slug of the file's name, an underscore, then the "
        "original class name UNCHANGED. Nothing else: no quotes, no "
        "explanation, no trailing punctuation. Example: for file "
        "'OrderSummaryV2.css' and class 'title', respond exactly "
        "'order_summary_v2_title'."
    )
    context = build_issue_context(issue, job)
    prompt = (
        f"{context}\n\n"
        f"The fix plan is renaming the class '.{issue.class_name}' in "
        f"'{target_file}' (the smaller-blast-radius side of this "
        f"conflict, per the ANALYZER EVIDENCE above) to "
        f"'<slug>{expected_suffix}'. Give the slugified file name for "
        f"'{target_file}', combined with the class name as instructed."
    )
    raw = call_llm_chat(prompt, system=system_prompt)

    if raw.startswith("["):
        # llm_client.py's soft-failure convention (unavailable/timeout/
        # HTTP error all come back as a bracketed message, never raise) —
        # fall back rather than treat the error text itself as a name.
        return None

    candidate = raw.strip().strip('"').strip("'").strip(".")
    if not candidate:
        return None
    # Defensive: take only the first line/token in case the model added
    # any explanation despite the system prompt telling it not to.
    candidate = candidate.splitlines()[0].strip().split()[0]
    candidate = _to_snake_case(candidate)

    if not candidate or len(candidate) > MAX_NAME_LENGTH or not VALID_CLASS_NAME.match(candidate):
        return None

    # Hard enforcement of the filename_classname convention: the LLM may
    # only have slugified the filename part. If it dropped, altered, or
    # forgot the original class name suffix, its answer is untrustworthy
    # for THIS convention (even if it's a "valid" class name on its own) —
    # reject rather than silently accept a different scheme.
    if not candidate.endswith(expected_suffix) or candidate == expected_suffix.lstrip("_"):
        return None
    slug_part = candidate[: -len(expected_suffix)]
    if not slug_part:
        return None

    return candidate


def mechanical_class_name(css_file_path: str, class_name: str) -> str:
    """The deterministic filename_classname fallback, also used directly
    by patch_generator.py when no LLM candidate is available."""
    return f"{_file_stem_slug(css_file_path)}_{class_name}"
