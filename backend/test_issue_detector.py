"""
Standalone full-pipeline test — no server required.
Run: python test_issue_detector.py
"""
import os
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_file
from app.relationship_model import build_relationship_model
from app.issue_detector import detect_issues

PROJECT_ROOT_ABS = os.path.abspath("sample_project")

if __name__ == "__main__":
    scan_result = scan_project(PROJECT_ROOT_ABS, job_id="local-test")

    css_results = [
        parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files
    ]
    jsx_results = [
        parse_jsx_file(f.absolute_path, f.relative_path, PROJECT_ROOT_ABS)
        for f in scan_result.jsx_files + scan_result.js_files
    ]

    model = build_relationship_model(css_results, jsx_results)
    issues = detect_issues(model)

    print(f"project_has_dynamic_classnames: {model.project_has_dynamic_classnames}\n")
    print(f"Found {len(issues)} issue(s):\n")

    for issue in issues:
        print(f"[{issue.severity.upper():6}] [{issue.confidence:4} confidence] {issue.issue_type}: {issue.class_name}")
        print(f"  {issue.message}")
        for d in issue.css_definitions:
            print(f"    CSS def: {d.file_path}:{d.line_number}  {[f'{x.property}: {x.value}' for x in d.declarations]}")
        for u in issue.jsx_usages:
            print(f"    JSX use: {u.file_path}:{u.line_number}  <{u.element}>")
        print()
