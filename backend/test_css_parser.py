"""
Standalone CSS parser test — no server required.
Run: python test_css_parser.py
"""
import os
from app.css_parser import parse_css_file

CSS_FILES = [
    "src/components/Navbar.css",
    "src/components/Hero.css",
]

if __name__ == "__main__":
    for rel_path in CSS_FILES:
        abs_path = os.path.join("sample_project", rel_path)
        result = parse_css_file(abs_path, rel_path)

        print(f"=== {result.file_path} ===")
        for rule in result.rules:
            media = f"  [inside @media {rule.media_context}]" if rule.media_context else ""
            support = "" if rule.is_supported_selector else "  (UNSUPPORTED selector for class analysis)"
            print(f"  Line {rule.line_number}: {rule.selector}{media}{support}")
            print(f"    class_names: {rule.class_names}")
            for decl in rule.declarations:
                print(f"    {decl.property}: {decl.value}")
        if result.skipped_at_rules:
            print(f"  Skipped at-rules: {result.skipped_at_rules}")
        if result.parse_errors:
            print(f"  Parse errors: {result.parse_errors}")
        print()
