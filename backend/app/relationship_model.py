"""
The Codebase Relationship Model (Phase 4a).

Takes the outputs of Phase 2 (CSS parsing) and Phase 3 (JSX parsing) and
builds simple lookup tables keyed by class name:
  - which CSS files/rules define each class
  - which JSX files/elements use each class

This is intentionally NOT a general graph library — just two dicts. That's
enough for every rule issue_detector.py needs, and it's easy to reason about.
"""
from dataclasses import dataclass, field
from typing import Dict, List

from .models import (
    CSSFileParseResult,
    JSXFileParseResult,
    CSSClassDefinitionRef,
    JSXClassUsageRef,
)


@dataclass
class RelationshipModel:
    css_classes: Dict[str, List[CSSClassDefinitionRef]] = field(default_factory=dict)
    jsx_usages: Dict[str, List[JSXClassUsageRef]] = field(default_factory=dict)
    project_has_dynamic_classnames: bool = False


def build_relationship_model(
    css_results: List[CSSFileParseResult], jsx_results: List[JSXFileParseResult]
) -> RelationshipModel:
    model = RelationshipModel()

    for css_result in css_results:
        for rule in css_result.rules:
            if not rule.is_supported_selector:
                continue  # MVP scope: only simple class selectors (Phase 2 decision)
            for class_name in rule.class_names:
                model.css_classes.setdefault(class_name, []).append(
                    CSSClassDefinitionRef(
                        file_path=rule.file_path,
                        line_number=rule.line_number,
                        selector=rule.selector,
                        declarations=rule.declarations,
                        media_context=rule.media_context,
                    )
                )

    for jsx_result in jsx_results:
        for usage in jsx_result.class_name_usages:
            if usage.dynamic_expression is not None:
                model.project_has_dynamic_classnames = True
            for class_name in usage.static_classes:
                model.jsx_usages.setdefault(class_name, []).append(
                    JSXClassUsageRef(
                        file_path=jsx_result.file_path,
                        line_number=usage.line_number,
                        element=usage.element,
                        is_fully_static=usage.is_fully_static,
                    )
                )

    return model
