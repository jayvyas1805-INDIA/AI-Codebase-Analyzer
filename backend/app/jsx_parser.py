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
from .models import ImportSpecifier, ImportStatement, ClassNameUsage, ModuleClassRef, JSXFileParseResult

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
    """
    Single-file entry point — spawns one Node process for this one file.
    Kept for backward compatibility (tests, single-file callers), but for
    scanning a whole project use parse_jsx_files() below instead: spawning
    a fresh Node process per file costs ~100-150ms of pure startup
    overhead each time, which dominates total scan time on any project
    with more than a couple dozen files.
    """
    results = parse_jsx_files([(absolute_path, relative_path)], project_root_abs)
    return results[0]


def _raw_result_to_model(
    relative_path: str, project_root_abs: str, data: dict
) -> JSXFileParseResult:
    if "error" in data:
        return JSXFileParseResult(
            file_path=relative_path, imports=[], class_name_usages=[],
            parse_errors=[f"Babel parse error: {data['error']}"],
        )

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
            module_class_refs=[
                ModuleClassRef(module_source=r["module_source"], class_name=r["class_name"])
                for r in u.get("module_class_refs", [])
            ],
        )
        for u in data.get("classNameUsages", [])
    ]

    return JSXFileParseResult(
        file_path=relative_path, imports=imports, class_name_usages=usages, parse_errors=[]
    )


def parse_jsx_files(
    files: List[Tuple[str, str]], project_root_abs: str
) -> List[JSXFileParseResult]:
    """
    Batch entry point — spawns Node ONCE for the whole project instead of
    once per file. `files` is a list of (absolute_path, relative_path)
    pairs, in the order results should come back in.

    This is the fix for the scan-speed regression on large projects: a
    300-file project used to take ~50s here alone (almost entirely Node
    process-startup overhead, ~150ms x 300), because parse_jsx_file() was
    called once per file. Batching brings that down to roughly the cost of
    ONE Node startup plus actual parse time for all files combined.
    """
    if not files:
        return []

    absolute_paths = [abs_path for abs_path, _ in files]

    try:
        proc = subprocess.run(
            ["node", JS_HELPER_SCRIPT, "--batch"],
            input=json.dumps(absolute_paths),
            capture_output=True,
            text=True,
            timeout=max(30, len(files) * 2),  # scale timeout with batch size
        )
    except FileNotFoundError:
        error = "Node.js not found. Make sure Node is installed and on your PATH."
        return [
            JSXFileParseResult(file_path=rel, imports=[], class_name_usages=[], parse_errors=[error])
            for _, rel in files
        ]
    except subprocess.TimeoutExpired:
        error = "Batch parsing timed out (project may be unusually large)."
        return [
            JSXFileParseResult(file_path=rel, imports=[], class_name_usages=[], parse_errors=[error])
            for _, rel in files
        ]

    if proc.returncode != 0:
        error = f"Node process failed: {proc.stderr.strip()[:500]}"
        return [
            JSXFileParseResult(file_path=rel, imports=[], class_name_usages=[], parse_errors=[error])
            for _, rel in files
        ]

    try:
        batch_data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        error = f"Could not parse Node batch output: {proc.stdout[:300]}"
        return [
            JSXFileParseResult(file_path=rel, imports=[], class_name_usages=[], parse_errors=[error])
            for _, rel in files
        ]

    results = []
    for abs_path, rel_path in files:
        data = batch_data.get(abs_path)
        if data is None:
            results.append(
                JSXFileParseResult(
                    file_path=rel_path, imports=[], class_name_usages=[],
                    parse_errors=["No result returned for this file in the batch output."],
                )
            )
        else:
            results.append(_raw_result_to_model(rel_path, project_root_abs, data))
    return results