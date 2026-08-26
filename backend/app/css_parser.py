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


def _serialize(tokens) -> str:
    return tinycss2.serialize(tokens).strip()


def _extract_class_names(selector_text: str):
    """
    A selector can be a comma-separated list of alternatives, e.g.
    ".container, .card". Each alternative is checked independently.
    Returns (class_names, is_supported).
    """
    parts = [p.strip() for p in selector_text.split(",") if p.strip()]
    class_names: List[str] = []
    all_supported = True

    for part in parts:
        if SIMPLE_CLASS_SELECTOR.match(part):
            class_names.extend(CLASS_TOKEN.findall(part))
        else:
            all_supported = False

    # de-duplicate while preserving order
    seen = set()
    unique = []
    for name in class_names:
        if name not in seen:
            seen.add(name)
            unique.append(name)

    return unique, all_supported


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
):
    for rule in rules:
        if rule.type == "qualified-rule":
            selector_text = _serialize(rule.prelude)
            class_names, supported = _extract_class_names(selector_text)
            declarations = _parse_declarations(rule.content)

            out_rules.append(
                CSSRule(
                    file_path=file_path,
                    selector=selector_text,
                    class_names=class_names,
                    declarations=declarations,
                    line_number=rule.source_line,
                    is_supported_selector=supported,
                    media_context=media_context,
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

    _walk_rules(top_level_rules, relative_path, None, out_rules, parse_errors, skipped_at_rules)

    return CSSFileParseResult(
        file_path=relative_path,
        rules=out_rules,
        parse_errors=parse_errors,
        skipped_at_rules=skipped_at_rules,
    )
