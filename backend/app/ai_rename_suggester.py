"""
LLM-Assisted Class Naming for rename_scoped_class fixes (Track 3).

WHY THIS IS THE ONLY PLACE AN LLM TOUCHES THE FIX PIPELINE
-------------------------------------------------------------
fix_planner.py already decides WHAT to do (rename vs. consolidate) and
WHICH file to touch, entirely deterministically — see that module's
docstring for why: those are judgment calls with real evidence behind
them (blast radius), and getting them wrong risks breaking working code.

patch_generator.py's mechanical new name (`f"{component_stem}-{class_name}"`,
e.g. "dashboard-panel") is SAFE but often unhelpful — it tells you WHERE
the class came from, not WHAT it's for. Suggesting a genuinely descriptive
name (e.g. "sidebar-nav-panel" instead of "dashboard-panel") is exactly
the kind of judgment call an LLM is good at and a hardcoded heuristic
isn't. Crucially, naming is LOW-STAKES to get "wrong": worst case is an
ugly-but-still-valid, still-unique name — nothing breaks. That asymmetry
(vs. e.g. picking which VALUE wins a conflict, where a wrong guess breaks
the UI) is exactly why this is the one place in the fix pipeline that
gets an LLM in the loop, and nowhere else does.

INVARIANT PRESERVED: the LLM only ever proposes a STRING, never a file, a
line number, or a diff. patch_generator.py still generates the actual
patch, and still runs whatever name comes back through the SAME
collision-avoidance suffixing (`_dedupe_name`) regardless of whether the
name came from here or the mechanical fallback — so uniqueness is
guaranteed deterministically either way. If the LLM is unavailable,
misconfigured, times out, or returns something that doesn't look like a
valid CSS class name, this fails SOFTLY back to None — renaming still
works with zero LLM involvement, exactly like before this module existed.
"""
import re
from typing import Optional

from .ai_context_builder import build_issue_context
from .llm_client import call_llm_chat

# kebab-case, must start with a letter — a valid, boring, safe CSS
# identifier. Deliberately stricter than CSS actually allows (no leading
# digits/underscores, no camelCase) so every accepted suggestion reads
# consistently with the rest of a typical component-scoped naming style.
VALID_CLASS_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 40

SYSTEM_PROMPT = (
    "You suggest CSS class names. Given context about a CSS class-naming "
    "conflict, respond with ONLY a single new, descriptive, kebab-case CSS "
    "class name for the class being renamed — nothing else. No quotes, no "
    "explanation, no trailing punctuation. Base it on what the element or "
    "component actually is or does, not on the file it happens to be "
    "defined in. Example valid responses: sidebar-nav-panel, "
    "primary-cta-button, product-card-title."
)


def _to_kebab_case(s: str) -> str:
    """'SidebarPanel' -> 'sidebar-panel', not 'sidebarpanel' — a plain
    .lower() would silently destroy word boundaries a model sometimes
    returns despite the kebab-case instruction in SYSTEM_PROMPT."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", s)
    return s.lower()


def suggest_class_name(issue, plan, job) -> Optional[str]:
    """
    Returns a validated kebab-case class name string, or None if the LLM
    is unavailable/misconfigured or its response didn't look like a valid
    CSS class name. Callers MUST fall back to the existing mechanical name
    (patch_generator.py's _unique_new_name) when this returns None — see
    module docstring for why that fallback is safe and expected.
    """
    context = build_issue_context(issue, job)
    prompt = (
        f"{context}\n\n"
        f"The fix plan is renaming the class '.{issue.class_name}' in "
        f"'{plan.target_file}' (the smaller-blast-radius side of this "
        f"conflict, per the ANALYZER EVIDENCE above) to a new, unique, "
        f"component-scoped name. Suggest one."
    )
    raw = call_llm_chat(prompt, system=SYSTEM_PROMPT)

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
    candidate = _to_kebab_case(candidate)

    if not candidate or len(candidate) > MAX_NAME_LENGTH or not VALID_CLASS_NAME.match(candidate):
        return None

    return candidate
