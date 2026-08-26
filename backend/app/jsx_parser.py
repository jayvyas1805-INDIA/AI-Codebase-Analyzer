"""
The JSX Parser + Import Resolver (Phase 3).

Extraction itself happens in js_helper/babel_parse.js — a real Babel AST
parser, since JSX isn't valid Python syntax and we already committed to
"use a real AST parser" rather than regex. This module:
  1. Calls that Node script as a subprocess, once per file
  2. Turns its JSON output into our Pydantic models
  3. Resolves relative import paths ("./Hero.css") into project-root-relative
     paths ("src/components/Hero.css"), so Phase 4 can directly match a JSX
     file's imports against the CSS files Phase 2 already parsed
"""
import json
import os
import subprocess
from typing import List, Optional, Tuple

from .config import BASE_DIR
from .models import ImportSpecifier, ImportStatement, ClassNameUsage, JSXFileParseResult

JS_HELPER_SCRIPT = os.path.join(BASE_DIR, "js_helper", "babel_parse.js")

# Extensions we try, in order, when an import has no explicit extension
# (e.g. `import Hero from "./Hero"` could mean Hero.jsx, Hero.js, or Hero/index.js)
RESOLVE_EXTENSIONS = (".jsx", ".js", ".css")


def _resolve_import_source(
    source: str, importer_relative_path: str, project_root_abs: str
) -> Tuple[Optional[str], bool]:
    """
    Returns (resolved_path, is_external).
    resolved_path is relative to the project root, using "/" separators.
    is_external=True for npm packages ("react", "clsx") — nothing to resolve.
    """
    if not source.startswith("."):
        return None, True  # npm package, not a local file

    importer_dir = os.path.dirname(importer_relative_path)
    combined = os.path.normpath(os.path.join(importer_dir, source))

    candidates = []
    if os.path.splitext(combined)[1]:
        candidates.append(combined)
    else:
        for ext in RESOLVE_EXTENSIONS:
            candidates.append(combined + ext)
        for ext in (".jsx", ".js"):
            candidates.append(os.path.join(combined, "index" + ext))

    for candidate in candidates:
        candidate_norm = candidate.replace(os.sep, "/")
        if os.path.isfile(os.path.join(project_root_abs, candidate_norm)):
            return candidate_norm, False

    # Nothing matched on disk — still return our best guess rather than
    # silently dropping it. Phase 4 can flag it as "import target not found".
    return combined.replace(os.sep, "/"), False


def parse_jsx_file(
    absolute_path: str, relative_path: str, project_root_abs: str
) -> JSXFileParseResult:
    empty = lambda errors: JSXFileParseResult(
        file_path=relative_path, imports=[], class_name_usages=[], parse_errors=errors
    )

    try:
        proc = subprocess.run(
            ["node", JS_HELPER_SCRIPT, absolute_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return empty(["Node.js not found. Make sure Node is installed and on your PATH."])
    except subprocess.TimeoutExpired:
        return empty(["Parsing timed out (file may be unusually large or malformed)."])

    if proc.returncode != 0:
        return empty([f"Node process failed: {proc.stderr.strip()[:500]}"])

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return empty([f"Could not parse Node output: {proc.stdout[:300]}"])

    if "error" in data:
        return empty([f"Babel parse error: {data['error']}"])

    imports: List[ImportStatement] = []
    for imp in data.get("imports", []):
        resolved_path, is_external = _resolve_import_source(
            imp["source"], relative_path, project_root_abs
        )
        specifiers = [ImportSpecifier(**s) for s in imp["specifiers"]]
        imports.append(
            ImportStatement(
                source=imp["source"],
                specifiers=specifiers,
                line_number=imp["line_number"],
                is_css_import=imp["is_css_import"],
                resolved_path=resolved_path,
                is_external=is_external,
            )
        )

    usages = [
        ClassNameUsage(
            element=u["element"],
            line_number=u["line_number"],
            static_classes=u["static_classes"],
            dynamic_expression=u.get("dynamic_expression"),
            is_fully_static=u["is_fully_static"],
        )
        for u in data.get("classNameUsages", [])
    ]

    return JSXFileParseResult(
        file_path=relative_path, imports=imports, class_name_usages=usages, parse_errors=[]
    )
