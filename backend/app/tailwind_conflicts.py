"""
Tailwind Utility-Class Conflict Detector.

WHY THIS IS A SEPARATE MODULE, NOT AN EXTENSION OF scope_aware_conflicts.py

The reachability-based engine answers "can two DIFFERENT FILES' definitions
of the same class name reach the same element?" — a cross-file, name-based
question. Tailwind utility classes don't get redefined across files (there's
nothing to look up: `p-4` always means `padding: 1rem`, everywhere,
generated once). The bug that actually breaks UIs in a Tailwind project is
different in shape: two utilities on the SAME element, in the SAME
responsive/state variant scope, setting the SAME CSS property to different
values — e.g. className="p-4 p-2". Whichever rule the bundler emits later
in the compiled stylesheet wins, and that's invisible from reading the JSX.
That's a same-file, same-element analysis, so it works directly off each
JSXFileParseResult's raw per-usage class lists — NOT off RelationshipModel,
which deliberately flattens usages by class name across the whole project
and loses "which classes appeared together on one element."

WHY `p-4 pt-2` IS *NOT* FLAGGED (AND WHY THAT MATTERS)

Tailwind's compiled stylesheet orders utilities so that more specific ones
(pt-*, a single side) reliably come after more general ones (p-*, all
sides) — `p-4 pt-2` is normal, intentional Tailwind usage ("all sides 1rem,
except top 0.5rem"), not a bug. Flagging every side/axis utility next to
its "all sides" counterpart would bury real bugs in noise and erode trust
in the tool. So each of p/px/py/pt/pr/pb/pl (and the margin equivalents) is
tracked as its OWN family — only an EXACT SAME utility prefix appearing
twice with a different value in the same variant scope is flagged (e.g.
"p-4 p-2", not "p-4 pt-2").

WHY VARIANT SCOPE MATTERS

`p-4 md:p-2` is a deliberate responsive override (p-2 only applies at the
md breakpoint and above) — not a conflict. `hover:bg-red-500
hover:bg-blue-500` IS a conflict (same hover state, same property, two
different values — one silently wins). So utilities are grouped by their
variant prefix chain (everything before the final class, e.g. ("md",) or
("hover", "dark")) before checking for same-family collisions within that
group.

SCOPE (v1) — deliberately conservative to avoid false positives:
- Only checks `static_classes` already extracted per className usage by
  babel_parse.js (StringLiteral / TemplateLiteral literal parts / clsx
  string+object-key arguments). Dynamic/conditional parts are not analyzed
  here — we can't know the final combination without running the app.
- Only classifies utilities into families this module explicitly
  recognizes (see FAMILY_PATTERNS below) — spacing, sizing, display,
  position, flexbox alignment, z-index, font-weight/size, text-align,
  text/background/border color, border-radius, opacity, overflow. An
  unrecognized utility is silently skipped (not flagged, not guessed at)
  rather than risk a wrong classification.
- Arbitrary-value utilities (`p-[13px]`) ARE matched by family (the regex
  matches the prefix, not the specific token list) but two different
  arbitrary values in the same family are still correctly flagged.
"""
import re
from typing import Callable, List, Optional, Tuple

from .models import Issue, JSXFileParseResult

# (regex matching the full base utility INCLUDING its value, family key).
# Checked in order — more specific patterns (e.g. text-align keywords) are
# listed before more general ones so a class like "text-left" doesn't fall
# through to being misread as a color or size utility.
FAMILY_PATTERNS: List[Tuple["re.Pattern[str]", str]] = [
    # Display / position (single keyword, no value)
    (re.compile(r"^(block|inline-block|inline|flex|inline-flex|grid|inline-grid|hidden|"
                r"table|inline-table|table-caption|table-cell|table-column|"
                r"table-column-group|table-footer-group|table-header-group|"
                r"table-row-group|table-row|flow-root|contents|list-item)$"), "display"),
    (re.compile(r"^(static|fixed|absolute|relative|sticky)$"), "position"),

    # Spacing — each prefix is its OWN family on purpose (see module docstring)
    (re.compile(r"^p-"), "padding-all"),
    (re.compile(r"^px-"), "padding-x"),
    (re.compile(r"^py-"), "padding-y"),
    (re.compile(r"^pt-"), "padding-top"),
    (re.compile(r"^pr-"), "padding-right"),
    (re.compile(r"^pb-"), "padding-bottom"),
    (re.compile(r"^pl-"), "padding-left"),
    (re.compile(r"^-?m-"), "margin-all"),
    (re.compile(r"^-?mx-"), "margin-x"),
    (re.compile(r"^-?my-"), "margin-y"),
    (re.compile(r"^-?mt-"), "margin-top"),
    (re.compile(r"^-?mr-"), "margin-right"),
    (re.compile(r"^-?mb-"), "margin-bottom"),
    (re.compile(r"^-?ml-"), "margin-left"),

    # Sizing
    (re.compile(r"^min-w-"), "min-width"),
    (re.compile(r"^min-h-"), "min-height"),
    (re.compile(r"^max-w-"), "max-width"),
    (re.compile(r"^max-h-"), "max-height"),
    (re.compile(r"^w-"), "width"),
    (re.compile(r"^h-"), "height"),

    # Flexbox
    (re.compile(r"^flex-(row|row-reverse|col|col-reverse)$"), "flex-direction"),
    (re.compile(r"^flex-(wrap|wrap-reverse|nowrap)$"), "flex-wrap"),
    (re.compile(r"^justify-(start|end|center|between|around|evenly|normal|stretch)$"), "justify-content"),
    (re.compile(r"^items-(start|end|center|baseline|stretch)$"), "align-items"),

    (re.compile(r"^z-"), "z-index"),
    (re.compile(r"^opacity-\d+$"), "opacity"),

    (re.compile(r"^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$"), "font-weight"),

    # `text-` is overloaded across three different properties in Tailwind —
    # alignment keywords and size keywords are checked FIRST (fixed, known
    # vocab) before falling back to "anything else text-color-shaped".
    (re.compile(r"^text-(left|center|right|justify|start|end)$"), "text-align"),
    (re.compile(r"^text-(xs|sm|base|lg|[2-9]?xl)$"), "font-size"),
    (re.compile(r"^text-(black|white|transparent|current|inherit)$"), "text-color"),
    (re.compile(r"^text-[a-z]+-\d{2,3}$"), "text-color"),
    (re.compile(r"^text-\[.+\]$"), "text-color"),  # arbitrary value, e.g. text-[#ff0000]

    (re.compile(r"^bg-(black|white|transparent|current|inherit)$"), "background-color"),
    (re.compile(r"^bg-[a-z]+-\d{2,3}$"), "background-color"),
    (re.compile(r"^bg-\[.+\]$"), "background-color"),

    (re.compile(r"^border-(black|white|transparent|current|inherit)$"), "border-color"),
    (re.compile(r"^border-[a-z]+-\d{2,3}$"), "border-color"),

    (re.compile(r"^rounded(-(none|sm|md|lg|xl|2xl|3xl|full))?$"), "border-radius"),

    (re.compile(r"^overflow-x-(auto|hidden|visible|scroll|clip)$"), "overflow-x"),
    (re.compile(r"^overflow-y-(auto|hidden|visible|scroll|clip)$"), "overflow-y"),
    (re.compile(r"^overflow-(auto|hidden|visible|scroll|clip)$"), "overflow"),
]

# Roughly matches Tailwind's known variant vocabulary (responsive breakpoints,
# common pseudo-class/state variants, and dark mode). A variant chain segment
# NOT in this set (e.g. a custom plugin variant) is still treated as a
# variant — we don't need to know its name, just that it's a scope, so an
# unrecognized prefix is fine to keep as-is rather than reject the class.
_KNOWN_UTILITY_START = re.compile(r"^[a-zA-Z0-9\[].*$")


def classify_family(base_utility: str) -> Optional[str]:
    for pattern, family in FAMILY_PATTERNS:
        if pattern.match(base_utility):
            return family
    return None


def parse_utility(raw_class: str) -> Tuple[Tuple[str, ...], str]:
    """
    Splits a utility class into (variant_chain, base_utility).
    "md:hover:bg-red-500" -> (("md", "hover"), "bg-red-500")
    "p-4"                 -> ((), "p-4")
    "!p-4"                -> ((), "p-4")   — leading '!' (important) stripped;
                                              doesn't change WHICH property is set
    """
    cls = raw_class.strip().lstrip("!")
    if not cls:
        return (), ""
    parts = cls.split(":")
    base = parts[-1]
    variants = tuple(parts[:-1])
    return variants, base


def detect_tailwind_conflicts(
    jsx_results: List[JSXFileParseResult], id_gen: Callable[[], str]
) -> List[Issue]:
    issues: List[Issue] = []

    for jsx_result in jsx_results:
        for usage in jsx_result.class_name_usages:
            if not usage.static_classes:
                continue

            # variant_chain -> family -> {base_utility -> None}  (dict used
            # as an ordered set, to report utilities in the order they
            # appeared in the className rather than an arbitrary hash order)
            groups: dict = {}
            for raw_class in usage.static_classes:
                variants, base = parse_utility(raw_class)
                if not base:
                    continue
                family = classify_family(base)
                if family is None:
                    continue  # unrecognized utility — skip, don't guess
                key = (variants, family)
                groups.setdefault(key, {})[base] = None

            for (variants, family), bases in groups.items():
                distinct_bases = list(bases.keys())
                if len(distinct_bases) < 2:
                    continue  # only a real conflict once 2+ DIFFERENT values collide

                variant_label = ":".join(variants) + ":" if variants else ""
                utility_list = ", ".join(f"{variant_label}{b}" for b in distinct_bases)

                issues.append(
                    Issue(
                        id=id_gen(),
                        issue_type="tailwind_utility_conflict",
                        severity="medium",
                        class_name=utility_list,
                        message=(
                            f"On this <{usage.element}> element, {utility_list} all set "
                            f"the same CSS property ({family}) but disagree — whichever "
                            f"rule the compiled stylesheet emits last silently wins, "
                            f"regardless of the order these classes appear in className."
                        ),
                        confidence="high",
                        css_definitions=[],
                        jsx_usages=[],
                        conflict_category="tailwind_same_element_conflict",
                        reaching_applications=[],
                        scope_analysis=(
                            f"Found on {jsx_result.file_path}, line {usage.line_number}, "
                            f"within the same className expression — this is a same-element "
                            f"conflict, not a cross-file reachability question, so no "
                            f"reachability graph was needed to confirm it."
                        ),
                    )
                )

    return issues
