"""
Pydantic models = the data "contracts" for this project.

Why Pydantic: FastAPI uses these to automatically validate request/response
data AND generate interactive API docs (Swagger UI) for free. Every later
phase (CSS parser, JSX parser, issue detector) will add its own models here
or in its own file, but they'll all build on top of ScanResult.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel


class ScannedFile(BaseModel):
    relative_path: str   # e.g. "src/components/Navbar.jsx" — safe to show in UI
    absolute_path: str   # e.g. "/backend/workspace/abc123/source/src/components/Navbar.jsx"
    file_type: str        # "jsx" | "js" | "css"
    size_bytes: int


class ScanResult(BaseModel):
    job_id: str
    root_path: str
    total_files_scanned: int
    jsx_files: List[ScannedFile]
    js_files: List[ScannedFile]
    css_files: List[ScannedFile]
    warnings: List[str]


# ---- Phase 2: CSS Parser models ----

class CSSDeclaration(BaseModel):
    property: str   # e.g. "background"
    value: str      # e.g. "red"


class CSSRule(BaseModel):
    file_path: str                       # relative path, e.g. "src/components/Navbar.css"
    selector: str                         # raw selector text, e.g. ".container, .navbar"
    class_names: List[str]                # simple class names extracted, e.g. ["container"]
    declarations: List[CSSDeclaration]
    line_number: int                      # 1-indexed, where the rule starts
    is_supported_selector: bool           # False if selector uses combinators/ids/tags/pseudo-classes
    media_context: Optional[str] = None   # e.g. "(max-width: 768px)" if inside @media, else None


class CSSFileParseResult(BaseModel):
    file_path: str
    rules: List[CSSRule]
    parse_errors: List[str]
    skipped_at_rules: List[str]           # e.g. ["@keyframes", "@font-face"] — noted, not parsed


# ---- Phase 3: JSX Parser + Import Resolver models ----

class ImportSpecifier(BaseModel):
    imported_name: Optional[str] = None   # e.g. "useState"; None for default/namespace imports
    local_name: str                        # the name actually used in this file
    import_type: str                       # "default" | "named" | "namespace"


class ImportStatement(BaseModel):
    source: str                            # raw string as written, e.g. "./Hero.css" or "react"
    specifiers: List[ImportSpecifier]
    line_number: int
    is_css_import: bool
    resolved_path: Optional[str] = None    # relative to project root, if it's a local file
    is_external: bool = False              # True for npm packages (react, clsx, etc.)


class ClassNameUsage(BaseModel):
    element: str                           # JSX tag name, e.g. "div"
    line_number: int
    static_classes: List[str]              # class names we could confidently resolve
    dynamic_expression: Optional[str] = None  # raw source of parts we couldn't resolve
    is_fully_static: bool                  # False if any part of className was conditional/dynamic


class JSXFileParseResult(BaseModel):
    file_path: str
    imports: List[ImportStatement]
    class_name_usages: List[ClassNameUsage]
    parse_errors: List[str]


# ---- Phase 4: Relationship Model + Issue Detection models ----

class CSSClassDefinitionRef(BaseModel):
    file_path: str
    line_number: int
    selector: str
    declarations: List[CSSDeclaration]
    media_context: Optional[str] = None


class JSXClassUsageRef(BaseModel):
    file_path: str
    line_number: int
    element: str
    is_fully_static: bool


class Issue(BaseModel):
    id: str
    issue_type: str    # "duplicate_class" | "partial_overlap_class" | "css_conflict" | "unused_css_class" | "undefined_css_class" | "unimported_css_file" | "isolated_duplicate"
    severity: str        # "low" | "medium" | "high" | "info"
    class_name: str
    message: str          # short deterministic explanation (NOT from the LLM)
    confidence: str = "high"   # "high" | "medium" | "low"
    css_definitions: List[CSSClassDefinitionRef] = []
    jsx_usages: List[JSXClassUsageRef] = []
    ai_explanation: Optional[str] = None    # filled in Phase 5 — what/why + affected components
    ai_recommendation: Optional[str] = None  # filled in Phase 5 — concrete fix suggestion
    # ---- Phase 3 (new): scope-aware classification, per spec section 8 ----
    conflict_category: Optional[str] = None   # "confirmed_conflict" | "potential_conflict" | "isolated_duplicate" | "duplicate_definition" | "unused_css"
    reaching_applications: List[str] = []     # application names whose entry point can reach ALL involved files (empty for isolated findings)
    scope_analysis: Optional[str] = None      # human-readable explanation of the scope/reachability reasoning behind the category


# ---- Phase 7: Chat models ----

class ChatMessage(BaseModel):
    role: str      # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    history: List[ChatMessage]


# ---- Phase 6 (new): Codebase Mapper / Application Boundary models ----
# Spec ref: sections 3 (structure awareness) and 4 (application boundary
# detection). This is evidence-based grouping ONLY — it does not yet know
# whether two applications' CSS can actually interact (that's the import/
# reachability graph, built on top of this in the next phase).

class Application(BaseModel):
    name: str                          # folder name, e.g. "admin", or "root" if no boundary found
    root_path: str                     # relative path from project root; "" means the whole project
    has_package_json: bool
    entry_points: List[str] = []       # relative paths of detected entry files (App.jsx, index.js, ...)
    jsx_files: List[str] = []          # relative paths of files assigned to this application
    js_files: List[str] = []
    css_files: List[str] = []


class CodebaseMap(BaseModel):
    root_path: str
    applications: List[Application]
    shared_jsx_files: List[str] = []   # files outside every detected application boundary
    shared_js_files: List[str] = []
    shared_css_files: List[str] = []
    boundary_detection_method: str     # "package_json" | "src_heuristic" | "single_app_fallback"
    warnings: List[str] = []


# ---- Phase 7 (new): Import / Reachability Graph models ----
# Spec ref: sections 5 (CSS scope and reachability) and 6 (import graph).
# Built on top of the Phase 6 CodebaseMap + the existing JSX parser's
# import data. Answers: "starting from each application's entry point(s),
# which JSX/CSS files can actually be pulled in?" — this is what lets
# Phase 3 tell an isolated duplicate from a real cross-application conflict.

class ApplicationReachability(BaseModel):
    application_name: str
    application_root: str
    entry_points_used: List[str] = []
    reachable_jsx_files: List[str] = []
    reachable_js_files: List[str] = []
    reachable_css_files: List[str] = []
    reachability_method: str   # "import_graph" | "folder_fallback_no_entry_point"
    unresolved_imports: List[str] = []   # local imports that pointed nowhere on disk


class ReachabilityGraph(BaseModel):
    applications: List[ApplicationReachability] = []
    # css relative path -> list of application names that can reach it
    css_reachable_from: Dict[str, List[str]] = {}
    # css files not reachable from ANY application's entry point
    unreached_css_files: List[str] = []
    warnings: List[str] = []


# ---- Phase 8 (new): Fix Planner + Patch Generator models ----
# Spec ref: sections 14 (fix planner), 15 (minimize blast radius),
# 16 (patch generation), 23 (structured LLM output must be validated).
# These are produced DETERMINISTICALLY (no LLM) — blast radius, which
# file to rename, and exact line replacements are all things the analyzer
# already has hard evidence for for; guessing them with an LLM would just
# reintroduce the "confidently wrong" risk the spec keeps warning about.

class FixOption(BaseModel):
    strategy: str            # e.g. "rename_scoped_class", "consolidate_duplicate"
    description: str
    blast_radius: int        # number of JSX usages that would be affected
    risk: str                 # "low" | "medium" | "high"
    affected_files: List[str] = []


class FixPlan(BaseModel):
    issue_id: str
    class_name: str
    plannable: bool                       # False if this issue type must never be auto-fixed
    reason_if_not_plannable: Optional[str] = None
    chosen_strategy: Optional[str] = None
    target_file: Optional[str] = None     # the specific file the chosen strategy modifies first
    risk: Optional[str] = None
    blast_radius: Optional[int] = None
    rationale: Optional[str] = None
    options_considered: List[FixOption] = []


class PatchFileChange(BaseModel):
    start_line: int
    end_line: int
    replacement: str
    original: Optional[str] = None   # original line text, kept for diff display / manual review


class PatchFile(BaseModel):
    path: str
    changes: List[PatchFileChange]


class Patch(BaseModel):
    issue_id: str
    strategy: str
    description: str
    files: List[PatchFile] = []
    manual_review_needed: List[str] = []   # human-readable notes on anything the generator refused to guess at
    valid: bool = True
    validation_errors: List[str] = []


# ---- Phase 9 (new): Sandbox Validation models ----
# Spec ref: sections 17 (sandbox validation), 18 (validation must respect
# application boundaries), 19 (iterative fix loop).

class ValidationResult(BaseModel):
    passed: bool
    original_issue_resolved: bool
    new_conflicts_introduced: int
    unrelated_applications_affected: List[str] = []
    before_summary: Dict[str, int] = {}
    after_summary: Dict[str, int] = {}
    notes: List[str] = []


class FixAttempt(BaseModel):
    attempt_number: int
    strategy: str
    target_file: str
    patch: Patch
    validation: ValidationResult


class FixResult(BaseModel):
    issue_id: str
    success: bool
    attempts: List[FixAttempt] = []
    final_message: str


class FullAnalysisResult(BaseModel):
    job_id: str
    total_css_files_parsed: int
    total_jsx_files_parsed: int
    project_has_dynamic_classnames: bool
    css_parse_errors: List[str]
    jsx_parse_errors: List[str]
    issues: List[Issue]           # real, actionable findings only (isolated_duplicate excluded)
    total_issues: int             # count of the above — stays "clean" per user request
    isolated_duplicates: List[Issue] = []   # same-name classes proven NOT to interact — informational only, not a problem
    codebase_map: Optional[CodebaseMap] = None
    reachability_graph: Optional[ReachabilityGraph] = None
