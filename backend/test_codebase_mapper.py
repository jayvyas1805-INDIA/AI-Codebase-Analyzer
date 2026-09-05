"""
Standalone codebase mapper test — no server required.
Run: python test_codebase_mapper.py

Tests against TWO fixtures:
  1. sample_project        — existing single-app fixture (must still work
                              exactly as before: single_app_fallback).
  2. sample_multiapp_project — new fixture mirroring the spec's admin/
                              customer/shared example (must detect 2
                              application boundaries via package.json).
"""
from app.scanner import scan_project
from app.codebase_mapper import build_codebase_map


def run(label, path):
    print(f"\n{'=' * 60}\n{label}  ({path})\n{'=' * 60}")
    scan_result = scan_project(path, job_id="local-test")
    codebase_map = build_codebase_map(scan_result)

    print(f"Detection method: {codebase_map.boundary_detection_method}")
    print(f"Applications found: {len(codebase_map.applications)}")

    for app in codebase_map.applications:
        print(f"\n  [{app.name}]  root='{app.root_path}'  has_package_json={app.has_package_json}")
        print(f"    entry_points: {app.entry_points}")
        print(f"    jsx_files: {app.jsx_files}")
        print(f"    css_files: {app.css_files}")

    if codebase_map.shared_css_files or codebase_map.shared_jsx_files or codebase_map.shared_js_files:
        print(f"\n  [shared / unassigned]")
        print(f"    jsx_files: {codebase_map.shared_jsx_files}")
        print(f"    css_files: {codebase_map.shared_css_files}")

    if codebase_map.warnings:
        print("\n  Warnings:")
        for w in codebase_map.warnings:
            print(f"    ! {w}")


if __name__ == "__main__":
    run("Single-app fixture (must NOT regress)", "sample_project")
    run("Multi-app fixture (admin/customer/shared)", "sample_multiapp_project")
