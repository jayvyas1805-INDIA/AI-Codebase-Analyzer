"""
Regression test for CSS Modules support, added to extend the conflict
engine to real-world React projects (most of which use *.module.css).

Three things this locks in, using the sample_css_modules_project fixture
(Button.module.css and Card.module.css BOTH locally define `.button` with
different values; Button.module.css ALSO has `:global(.icon)`, which
collides with a plain global `.icon` in globalicon.css):

  1. Module-local `.button` in two different files must NOT be flagged as
     a conflict/duplicate — the bundler hashes it uniquely per file, so it
     structurally cannot collide. Flagging it would be a false positive.
  2. `:global(.icon)` inside a .module.css file must still be caught as a
     REAL conflict against a plain global `.icon` elsewhere — the escape
     hatch is deliberately NOT scoped, so this is exactly the kind of bug
     this tool exists to catch, and the old code would have missed it
     entirely (`:global(...)` doesn't match the plain class-selector regex).
  3. `styles.button` (a resolved CSS Modules reference) must be treated as
     confidently static, NOT as an opaque dynamic expression — otherwise
     every unused-class severity in the WHOLE project gets quietly
     downgraded via project_has_dynamic_classnames, even for classes that
     have nothing to do with CSS Modules.

Requires: js_helper/node_modules installed (npm install inside js_helper/).

Run: python test_css_modules.py
"""
import os

from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.reachability_lookup import ReachabilityLookup
from app.scope_aware_conflicts import detect_scope_aware_conflicts

FIXTURE = "sample_css_modules_project"
assert os.path.isdir(FIXTURE), (
    f"Fixture '{FIXTURE}' not found — this test expects it alongside the "
    f"other sample_*_project fixtures in backend/."
)


def _id_gen():
    counter = {"n": 0}
    def gen():
        counter["n"] += 1
        return f"issue-{counter['n']}"
    return gen


scan_result = scan_project(FIXTURE, job_id="test-css-modules")
css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
jsx_results = parse_jsx_files(jsx_files_to_parse, FIXTURE)

for r in jsx_results:
    assert not r.parse_errors, (
        f"{r.file_path} failed to parse: {r.parse_errors} "
        f"(did you run `npm install` in js_helper/?)"
    )

model = build_relationship_model(css_results, jsx_results)

print("=" * 60)
print("Check 1: module-local classes excluded from cross-file registry")
print("=" * 60)
assert "button" not in model.css_classes, (
    "'button' leaked into the global cross-file registry — module-local "
    "classes must be excluded, they can't structurally collide"
)
assert len(model.module_local_definitions.get(
    "src/components/Button/Button.module.css::button", []
)) == 1
assert len(model.module_local_definitions.get(
    "src/components/Card/Card.module.css::button", []
)) == 1
print("PASS — both .button definitions correctly kept module-local, not in css_classes")

print()
print("=" * 60)
print("Check 2: :global(.icon) still enters the normal global registry")
print("=" * 60)
assert "icon" in model.css_classes, ":global(.icon) should still be a normal global class"
icon_files = {d.file_path for d in model.css_classes["icon"]}
assert icon_files == {"src/globalicon.css", "src/components/Button/Button.module.css"}, icon_files
print("PASS — :global() escape hatch correctly enters cross-file conflict detection")

print()
print("=" * 60)
print("Check 3: styles.foo resolves as static, doesn't pollute dynamic tracking")
print("=" * 60)
assert model.project_has_dynamic_classnames is False, (
    "styles.button / cardStyles.button should resolve as confidently "
    "static CSS Modules references, not count as 'dynamic classnames'"
)
assert "src/components/Button/Button.module.css::button" in model.module_local_usages
assert "src/components/Card/Card.module.css::button" in model.module_local_usages
print("PASS — module refs resolved without flipping project_has_dynamic_classnames")

print()
print("=" * 60)
print("Check 4: end-to-end — ONLY the real (icon) conflict is reported")
print("=" * 60)
codebase_map = build_codebase_map(scan_result)
reachability_graph = build_reachability_graph(codebase_map, jsx_results)
reach = ReachabilityLookup(reachability_graph, codebase_map)
issues = detect_scope_aware_conflicts(model, reach, _id_gen())

class_names_flagged = {i.class_name for i in issues}
assert "button" not in class_names_flagged, (
    f"'button' was flagged as an issue — false positive on a module-local "
    f"class. All issues: {[(i.class_name, i.issue_type) for i in issues]}"
)
assert "icon" in class_names_flagged, "the real :global(.icon) conflict was missed"
icon_issue = next(i for i in issues if i.class_name == "icon")
assert icon_issue.conflict_category == "confirmed_conflict", icon_issue.conflict_category
assert icon_issue.severity == "high", icon_issue.severity
print("PASS — only the genuine :global(.icon) conflict is reported, at high severity")

print()
print("All CSS Modules checks PASSED.")
