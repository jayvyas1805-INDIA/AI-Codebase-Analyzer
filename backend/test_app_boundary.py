"""
Standalone test for Phase 8 (Application Boundary Detection).
Run: python test_app_boundary.py
"""
import os
from app.scanner import scan_project
from app.app_boundary import detect_applications, build_file_application_map

PROJECT_ROOT_ABS = os.path.abspath("sample_monorepo_project")

if __name__ == "__main__":
    scan_result = scan_project(PROJECT_ROOT_ABS, job_id="monorepo-test")

    print(f"package.json files found: {scan_result.package_json_files}\n")

    applications = detect_applications(PROJECT_ROOT_ABS, scan_result.package_json_files)
    print("Detected applications:")
    for app in applications:
        print(f"  name={app.name!r}  root_path={app.root_path!r}  package_json={app.package_json_path!r}")
    print()

    all_files = [
        f.relative_path
        for f in scan_result.jsx_files + scan_result.js_files + scan_result.css_files
    ]
    file_app_map = build_file_application_map(all_files, applications)

    print("File → owning application:")
    for path in sorted(file_app_map):
        print(f"  {path}  ->  {file_app_map[path].name}")
