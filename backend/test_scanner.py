"""
Standalone scanner test — no server required.
Run: python test_scanner.py
"""
from app.scanner import scan_project

if __name__ == "__main__":
    result = scan_project("sample_project", job_id="local-test")

    print(f"Scanned {result.total_files_scanned} files\n")

    print(f"JSX files ({len(result.jsx_files)}):")
    for f in result.jsx_files:
        print(f"  - {f.relative_path}  ({f.size_bytes} bytes)")

    print(f"\nJS files ({len(result.js_files)}):")
    for f in result.js_files:
        print(f"  - {f.relative_path}  ({f.size_bytes} bytes)")

    print(f"\nCSS files ({len(result.css_files)}):")
    for f in result.css_files:
        print(f"  - {f.relative_path}  ({f.size_bytes} bytes)")

    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  ! {w}")
    else:
        print("\nNo warnings.")
