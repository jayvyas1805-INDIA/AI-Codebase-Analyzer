"""
Standalone JSX parser test — no server required.
Requires Node.js on PATH and js_helper/node_modules installed (see README step).
Run: python test_jsx_parser.py
"""
import os
from app.jsx_parser import parse_jsx_file

JSX_FILES = [
    "src/components/Navbar.jsx",
    "src/components/Hero.jsx",
]

PROJECT_ROOT_ABS = os.path.abspath("sample_project")

if __name__ == "__main__":
    for rel_path in JSX_FILES:
        abs_path = os.path.join(PROJECT_ROOT_ABS, rel_path)
        result = parse_jsx_file(abs_path, rel_path, PROJECT_ROOT_ABS)

        print(f"=== {result.file_path} ===")

        if result.parse_errors:
            print(f"  ERRORS: {result.parse_errors}")
            continue

        print("  Imports:")
        for imp in result.imports:
            kind = "external" if imp.is_external else f"resolved -> {imp.resolved_path}"
            print(f"    Line {imp.line_number}: \"{imp.source}\"  ({kind})")

        print("  className usages:")
        for u in result.class_name_usages:
            static = ", ".join(u.static_classes) if u.static_classes else "(none)"
            marker = "" if u.is_fully_static else "  [has dynamic part]"
            print(f"    Line {u.line_number}: <{u.element}>  static=[{static}]{marker}")
            if u.dynamic_expression:
                print(f"      dynamic_expression: {u.dynamic_expression}")
        print()
