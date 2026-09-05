"""
AI Context Builder (new phase, sits between issue detection and the LLM
calls in rag.py / chat.py).

Spec ref: sections 11 (AI context builder), 12 (AI must respect
static-analysis evidence), 13 (AI root-cause analysis inputs).

WHY THIS EXISTS
----------------
Before this phase, rag.py's `_format_context()` only ever showed the LLM
the issue's own `message` string plus whatever ChromaDB happened to
retrieve. It had NO idea an application/reachability model even existed —
so if a user asked "why isn't this OTHER `.button` a conflict?" (the exact
example in spec section 20), the model had nothing to reason from except
vibes. This module builds the structured package spec section 11
describes, using ONLY data the deterministic phases already produced:
Phase 1's CodebaseMap, Phase 2's ReachabilityGraph, Phase 3's
conflict_category/reaching_applications/scope_analysis, plus the existing
CSS/JSX parse results. It invents nothing new.

SECTIONS BUILT (mirrors spec section 11 exactly)
-------------------------------------------------
- Codebase context      : application(s) involved, root(s), relevant files
- Relationship context   : which component uses the class, which CSS
                           defines it, which files import each stylesheet,
                           which application each file belongs to, whether
                           another application defines the same class,
                           whether cross-application interaction exists
- CSS context            : selector, properties, media context, source lines
- React context          : component, element, className usage, location
- Analyzer evidence      : severity, conflict category, confidence,
                           scope_analysis — Phase 3's own reasoning, shown
                           verbatim so the LLM explains the SAME conclusion
                           the deterministic analyzer already reached,
                           rather than re-deriving (and possibly
                           contradicting) it.

GUARDRAIL (spec section 12)
----------------------------
CONTEXT_GUARDRAIL is a fixed instruction block meant to be prepended to
every system prompt that uses this context: never invent files, folders,
components, class names, imports, properties, or relationships; if
reachability truly can't be established from the evidence given, say so
explicitly rather than guessing.
"""
from typing import List, Optional

from .models import CodebaseMap, Issue, JSXFileParseResult, ReachabilityGraph

CONTEXT_GUARDRAIL = (
    "You must reason ONLY from the CONTEXT below. Do not invent files, "
    "folders, components, class names, imports, CSS properties, or "
    "relationships that are not explicitly present in it. If the context "
    "does not establish whether two styles can interact, say plainly that "
    "interaction cannot be established statically — do not guess or imply "
    "confidence you don't have. The 'ANALYZER EVIDENCE' section reflects "
    "conclusions a deterministic static analyzer already reached; explain "
    "and justify that conclusion, don't contradict it."
)


def _file_to_application(file_path: str, codebase_map: Optional[CodebaseMap]) -> str:
    if codebase_map is None:
        return "(unknown — no codebase map available)"
    for app in codebase_map.applications:
        if file_path in app.jsx_files or file_path in app.js_files or file_path in app.css_files:
            return app.name
    if (
        file_path in codebase_map.shared_jsx_files
        or file_path in codebase_map.shared_js_files
        or file_path in codebase_map.shared_css_files
    ):
        return "(shared — outside every detected application boundary)"
    return "(not found in codebase map)"


def _importers_of(css_file_path: str, jsx_results: List[JSXFileParseResult]) -> List[str]:
    """Which JSX/JS files actually import this CSS file, per static import evidence."""
    importers = []
    for result in jsx_results:
        for imp in result.imports:
            if imp.is_css_import and imp.resolved_path == css_file_path:
                importers.append(result.file_path)
    return sorted(set(importers))


def _other_definitions_elsewhere(issue: Issue, job) -> List[dict]:
    """
    Finds every OTHER definition of this class name in the project that is
    NOT already part of this issue's own css_definitions — i.e. exactly
    the "is there another `.button` somewhere else, and why doesn't it
    count" evidence the spec's chat example (section 20) needs.
    """
    already_included = {(d.file_path, d.line_number) for d in issue.css_definitions}
    others = []
    for css_result in job.css_results:
        for rule in css_result.rules:
            if issue.class_name not in rule.class_names:
                continue
            if (rule.file_path, rule.line_number) in already_included:
                continue
            reach = []
            if job.reachability_graph:
                reach = job.reachability_graph.css_reachable_from.get(rule.file_path, [])
            others.append(
                {
                    "file_path": rule.file_path,
                    "line_number": rule.line_number,
                    "application": _file_to_application(rule.file_path, job.codebase_map),
                    "reachable_from_applications": reach,
                }
            )
    return others


def build_issue_context(issue: Issue, job) -> str:
    """
    job is job_cache.JobData — needs .css_results, .jsx_results,
    .codebase_map, .reachability_graph. All optional except css/jsx
    results; missing map/graph degrade gracefully with an explicit note
    rather than silently omitting the section.
    """
    lines: List[str] = []

    # ---- Codebase context ----
    lines.append("=== CODEBASE CONTEXT ===")
    involved_files = sorted({d.file_path for d in issue.css_definitions} | {u.file_path for u in issue.jsx_usages})
    involved_apps = sorted({_file_to_application(f, job.codebase_map) for f in involved_files})
    lines.append(f"Application(s) involved: {involved_apps or ['(none)']}")
    if job.codebase_map:
        for app_name in involved_apps:
            app = next((a for a in job.codebase_map.applications if a.name == app_name), None)
            if app:
                lines.append(f"  - '{app.name}' root: '{app.root_path or '(project root)'}', "
                              f"entry point(s): {app.entry_points or ['(none detected)']}")
    lines.append(f"Relevant file paths: {involved_files}")

    # ---- Relationship context ----
    lines.append("\n=== RELATIONSHIP CONTEXT ===")
    for d in issue.css_definitions:
        importers = _importers_of(d.file_path, job.jsx_results)
        reach = job.reachability_graph.css_reachable_from.get(d.file_path, []) if job.reachability_graph else []
        lines.append(
            f"- '{d.file_path}' defines .{issue.class_name} — belongs to application "
            f"'{_file_to_application(d.file_path, job.codebase_map)}'; imported by: "
            f"{importers or ['(no local JS/JSX importer found)']}; reachable from "
            f"application(s): {reach or ['(unreached by static evidence)']}"
        )
    for u in issue.jsx_usages:
        lines.append(
            f"- '{u.file_path}' uses className on <{u.element}> at line {u.line_number} — "
            f"belongs to application '{_file_to_application(u.file_path, job.codebase_map)}'"
        )

    others = _other_definitions_elsewhere(issue, job)
    if others:
        lines.append(f"\nOther definitions of '.{issue.class_name}' elsewhere in the project (NOT part of this finding):")
        for o in others:
            lines.append(
                f"  - '{o['file_path']}':{o['line_number']} in application "
                f"'{o['application']}', reachable from: {o['reachable_from_applications'] or ['(unreached)']}"
            )
    else:
        lines.append(f"\nNo other definitions of '.{issue.class_name}' exist elsewhere in the project.")

    lines.append(
        f"\nCross-application interaction evidence for THIS finding: "
        f"{issue.scope_analysis or '(not applicable to this issue type)'}"
    )

    # ---- CSS context ----
    if issue.css_definitions:
        lines.append("\n=== CSS CONTEXT ===")
        for d in issue.css_definitions:
            decl_text = "; ".join(f"{x.property}: {x.value}" for x in d.declarations)
            media = f" (inside @media {d.media_context})" if d.media_context else ""
            lines.append(f"- {d.file_path}:{d.line_number}  .{issue.class_name}{media} {{ {decl_text} }}  [selector: {d.selector}]")

    # ---- React context ----
    if issue.jsx_usages:
        lines.append("\n=== REACT CONTEXT ===")
        for u in issue.jsx_usages:
            lines.append(
                f"- {u.file_path}:{u.line_number}  <{u.element} className=\"{issue.class_name}\">  "
                f"(fully static: {u.is_fully_static})"
            )

    # ---- Analyzer evidence (Phase 3's own conclusion, verbatim) ----
    lines.append("\n=== ANALYZER EVIDENCE ===")
    lines.append(f"- issue_type: {issue.issue_type}")
    lines.append(f"- conflict_category: {issue.conflict_category or '(n/a)'}")
    lines.append(f"- severity: {issue.severity}")
    lines.append(f"- confidence: {issue.confidence}")
    lines.append(f"- reaching_applications: {issue.reaching_applications or '(none — isolated or unreached)'}")
    lines.append(f"- deterministic message: {issue.message}")

    return "\n".join(lines)
