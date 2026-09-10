"""
Pipeline robustness test — the question isn't "does it work on THIS zip",
it's "does it survive EVERY zip shape without crashing or silently
producing garbage." Builds several structurally different synthetic
projects and runs the full pipeline (scan -> parse -> relationship model
-> codebase map -> reachability graph -> scope-aware detection) against
each, asserting it always returns cleanly.

Run: python test_pipeline_robustness.py
"""
import os
import shutil

from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware

WORKDIR = "robustness_fixtures"


def run_pipeline(project_path):
    """Runs the exact sequence main.py's /api/scan uses. Any exception
    here is exactly the kind of crash a real user's upload must never hit."""
    scan_result = scan_project(project_path, job_id="robustness-test")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, project_path)
    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)
    return issues, codebase_map, reachability_graph


def make(path, files: dict):
    full = os.path.join(WORKDIR, path)
    if os.path.exists(full):
        shutil.rmtree(full)
    os.makedirs(full, exist_ok=True)
    for rel, content in files.items():
        fpath = os.path.join(full, rel)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        if isinstance(content, bytes):
            with open(fpath, "wb") as f:
                f.write(content)
        else:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
    return full


if __name__ == "__main__":
    cases = []

    # 1. Completely empty project — no CSS, no JSX at all.
    cases.append(("empty_project", make("empty_project", {
        "README.md": "nothing here\n",
    })))

    # 2. Only images/assets, zero relevant files.
    cases.append(("assets_only", make("assets_only", {
        "public/logo.svg": "<svg></svg>",
    })))

    # 3. Flat project: no package.json ANYWHERE, no nested src/ folders
    #    either (single_app_fallback with root_path="").
    cases.append(("flat_no_boundaries", make("flat_no_boundaries", {
        "Button.jsx": 'export default function Button() { return <button className="btn">Go</button>; }\n',
        "Button.css": ".btn { color: red; }\n",
    })))

    # 4. package.json sits in a completely unrelated tooling subfolder with
    #    ZERO css/jsx files under it — must not crash building an empty app.
    cases.append(("unrelated_package_json", make("unrelated_package_json", {
        "scripts/package.json": '{"name": "build-tools"}',
        "src/App.jsx": 'export default function App() { return <div className="wrap">Hi</div>; }\n',
        "src/App.css": ".wrap { padding: 4px; }\n",
    })))

    # 5. Malformed / broken CSS syntax — parser must degrade gracefully,
    #    not throw.
    cases.append(("broken_css", make("broken_css", {
        "src/App.jsx": 'export default function App() { return <div className="x">Hi</div>; }\n',
        "src/App.css": ".x { color: ;;; background red no-semicolon\n .y {{{ }",
    })))

    # 6. JSX with a genuine syntax error — must degrade gracefully.
    cases.append(("broken_jsx", make("broken_jsx", {
        "src/App.jsx": 'export default function App() { return <div className="x" }\n',  # missing >
        "src/App.css": ".x { color: red; }\n",
    })))

    # 7. Non-UTF8 bytes in a CSS file (e.g. a stray Windows-1252 file).
    cases.append(("non_utf8_css", make("non_utf8_css", {
        "src/App.jsx": 'export default function App() { return <div className="z">Hi</div>; }\n',
    })))
    with open(f"{WORKDIR}/non_utf8_css/src/App.css", "wb") as f:
        f.write(b".z { content: '\xe9\xe8'; color: red; }\n")  # invalid UTF-8 bytes

    # 8. Deeply nested path (12+ levels) — path handling must not choke.
    deep_rel = "/".join([f"level{i}" for i in range(12)])
    cases.append(("deeply_nested", make("deeply_nested", {
        f"{deep_rel}/Deep.jsx": 'export default function Deep() { return <div className="deep">Hi</div>; }\n',
        f"{deep_rel}/Deep.css": ".deep { color: blue; }\n",
    })))

    # 9. Empty CSS and JSX files (zero bytes).
    cases.append(("empty_files", make("empty_files", {
        "src/App.jsx": "",
        "src/App.css": "",
    })))

    all_passed = True
    for name, path in cases:
        print(f"--- {name} ---")
        try:
            issues, codebase_map, reachability_graph = run_pipeline(path)
            print(f"  OK: {len(issues)} issue(s), "
                  f"{len(codebase_map.applications)} application(s) detected "
                  f"({codebase_map.boundary_detection_method})")
        except Exception as e:
            all_passed = False
            print(f"  CRASH: {type(e).__name__}: {e}")

    print()
    if all_passed:
        print("All robustness cases survived without crashing. PASS")
    else:
        print("One or more cases CRASHED. See above.")
        raise SystemExit(1)
