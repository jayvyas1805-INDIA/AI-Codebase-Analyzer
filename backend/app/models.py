"""
Pydantic models = the data "contracts" for this project.

Why Pydantic: FastAPI uses these to automatically validate request/response
data AND generate interactive API docs (Swagger UI) for free. Every later
phase (CSS parser, JSX parser, issue detector) will add its own models here
or in its own file, but they'll all build on top of ScanResult.
"""
from typing import List, Optional
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
    issue_type: str    # "duplicate_class" | "partial_overlap_class" | "css_conflict" | "unused_css_class" | "undefined_css_class"
    severity: str        # "low" | "medium" | "high"
    class_name: str
    message: str          # short deterministic explanation (NOT from the LLM)
    confidence: str = "high"   # "high" | "low"
    css_definitions: List[CSSClassDefinitionRef] = []
    jsx_usages: List[JSXClassUsageRef] = []
    ai_explanation: Optional[str] = None    # filled in Phase 5 — what/why + affected components
    ai_recommendation: Optional[str] = None  # filled in Phase 5 — concrete fix suggestion


# ---- Phase 7: Chat models ----

class ChatMessage(BaseModel):
    role: str      # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    history: List[ChatMessage]


class FullAnalysisResult(BaseModel):
    job_id: str
    total_css_files_parsed: int
    total_jsx_files_parsed: int
    project_has_dynamic_classnames: bool
    css_parse_errors: List[str]
    jsx_parse_errors: List[str]
    issues: List[Issue]
    total_issues: int
