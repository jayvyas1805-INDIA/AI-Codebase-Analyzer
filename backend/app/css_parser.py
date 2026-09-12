"""
The CSS Parser (Phase 2).

Its ONLY job: read a .css file and turn it into structured CSSRule objects —
selector text, extracted class names, declarations (property/value pairs),
and the line number each rule starts on. It does NOT decide what's a
conflict — that's Phase 3 (static analysis / issue detection).

MVP scope decisions (can be expanded later):
- Only SIMPLE class selectors are fully supported: ".foo", ".foo.bar"
  (compound, no combinator). Anything with descendants (".foo .bar"),
  IDs (#foo), tags (div), or pseudo-classes (:hover) is still recorded
  (so no data is lost) but flagged is_supported_selector=False and
  won't have class_names extracted — Phase 3 should skip those for
  className-conflict detection.
- @media blocks ARE parsed (so we don't lose rules inside them), and each
  rule inside gets media_context set to the media condition string.
- Other at-rules (@keyframes, @font-face, @import, etc.) are skipped and
  just noted in skipped_at_rules — not parsed into rules.
"""
import re
from typing import List, Optional

import tinycss2

from .models import CSSDeclaration, CSSRule, CSSFileParseResult

# Matches a selector made of ONE OR MORE class parts stuck together with no
# combinator, e.g. ".container" or ".container.active" — but NOT ".a .b",
# ".a > .b", "#id", "div", or ".a:hover".
SIMPLE_CLASS_SELECTOR = re.compile(r"^(\.[a-zA-Z_][\w-]*)+$")
CLASS_TOKEN = re.compile(r"\.([a-zA-Z_][\w-]*)")

# CSS Modules escape hatch: `:global(.foo)` inside a `.module.css` file means
# ".foo" is deliberately NOT hashed/scoped — it's a real global class, same
# as in a plain CSS file, and should go through normal cross-file conflict
# detection. Anything else in a .module.css file IS hashed per-file by the
# bundler and can't collide with a same-named class elsewhere.
GLOBAL_WRAPPER = re.compile(r"^:global\(\s*(.+?)\s*\)$")


def _strip_global_wrapper(selector_part: str):
    """Returns (inner_selector, was_wrapped)."""
    m = GLOBAL_WRAPPER.match(selector_part)
    if m:
        return m.group(1), True
    return selector_part, False


def _serialize(tokens) -> str:
    return tinycss2.serialize(tokens).strip()


def _extract_class_names(selector_text: str):
    """
    A selector can be a comma-separated list of alternatives, e.g.
    ".container, .card". Each alternative is checked independently.
    Returns (class_names, is_supported, has_global_wrapper).
    """
    parts = [p.strip() for p in selector_text.split(",") if p.strip()]
    class_names: List[str] = []
    all_supported = True
    has_global_wrapper = False

    for part in parts:
        inner, was_wrapped = _strip_global_wrapper(part)
        if was_wrapped:
            has_global_wrapper = True
        if SIMPLE_CLASS_SELECTOR.match(inner):
            class_names.extend(CLASS_TOKEN.findall(inner))
        else:
            all_supported = False

    # de-duplicate while preserving order
    seen = set()
    unique = []
    for name in class_names:
        if name not in seen:
            seen.add(name)
            unique.append(name)

    return unique, all_supported, has_global_wrapper


def _parse_declarations(content_tokens) -> List[CSSDeclaration]:
    declarations = []
    for decl in tinycss2.parse_declaration_list(
        content_tokens, skip_comments=True, skip_whitespace=True
    ):
        if decl.type == "declaration":
            value = tinycss2.serialize(decl.value).strip()
            declarations.append(CSSDeclaration(property=decl.lower_name, value=value))
        # 'error' nodes (malformed declarations) are silently skipped for now
    return declarations


def _walk_rules(
    rules,
    file_path: str,
    media_context: Optional[str],
    out_rules: List[CSSRule],
    parse_errors: List[str],
    skipped_at_rules: List[str],
    is_module_file: bool,
):
    for rule in rules:
        if rule.type == "qualified-rule":
            selector_text = _serialize(rule.prelude)
            class_names, supported, has_global_wrapper = _extract_class_names(selector_text)
            declarations = _parse_declarations(rule.content)

            class_scope = "global"
            if is_module_file and not has_global_wrapper:
                class_scope = "module_local"

            out_rules.append(
                CSSRule(
                    file_path=file_path,
                    selector=selector_text,
                    class_names=class_names,
                    declarations=declarations,
                    line_number=rule.source_line,
                    is_supported_selector=supported,
                    media_context=media_context,
                    class_scope=class_scope,
                )
            )

        elif rule.type == "at-rule":
            if rule.lower_at_keyword == "media" and rule.content is not None:
                condition = _serialize(rule.prelude)
                nested_rules = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                _walk_rules(
                    nested_rules,
                    file_path,
                    condition,
                    out_rules,
                    parse_errors,
                    skipped_at_rules,
                    is_module_file,
                )
            else:
                skipped_at_rules.append(f"@{rule.at_keyword} (line {rule.source_line})")

        elif rule.type == "error":
            parse_errors.append(f"Line {rule.source_line}: {rule.message}")


def parse_css_file(absolute_path: str, relative_path: str) -> CSSFileParseResult:
    with open(absolute_path, "r", encoding="utf-8", errors="replace") as f:
        css_text = f.read()

    top_level_rules = tinycss2.parse_stylesheet(
        css_text, skip_comments=True, skip_whitespace=True
    )

    out_rules: List[CSSRule] = []
    parse_errors: List[str] = []
    skipped_at_rules: List[str] = []
    is_module_file = relative_path.endswith(".module.css")

    _walk_rules(top_level_rules, relative_path, None, out_rules, parse_errors, skipped_at_rules, is_module_file)

    return CSSFileParseResult(
        file_path=relative_path,
        rules=out_rules,
        parse_errors=parse_errors,
        skipped_at_rules=skipped_at_rules,
    )