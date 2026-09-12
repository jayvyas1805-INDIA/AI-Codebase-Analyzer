"""
Regression test for tailwind_conflicts.py.

Covers both directions of correctness: real same-property, same-variant-
scope conflicts ARE flagged, and the three most common ways a naive
implementation would false-positive are NOT flagged:
  - "p-4 pt-2"       -> legitimate override (all-sides vs top-only), not a conflict
  - "p-4 md:p-2"     -> legitimate responsive override, different variant scope
  - "bg-red-500 hover:bg-blue-500" -> different variant scope (base vs hover)

Requires: js_helper/node_modules installed (npm install inside js_helper/).

Run: python test_tailwind_conflicts.py
"""
import os

from app.scanner import scan_project
from app.jsx_parser import parse_jsx_files
from app.tailwind_conflicts import detect_tailwind_conflicts, classify_family, parse_utility

FIXTURE = "sample_tailwind_project"
assert os.path.isdir(FIXTURE), f"Fixture '{FIXTURE}' not found alongside the other sample_*_project dirs."


def _id_gen():
    counter = {"n": 0}
    def gen():
        counter["n"] += 1
        return f"issue-{counter['n']}"
    return gen


print("=" * 60)
print("Check 1: parse_utility splits variant chain from base utility")
print("=" * 60)
assert parse_utility("p-4") == ((), "p-4")
assert parse_utility("md:p-2") == (("md",), "p-2")
assert parse_utility("md:hover:bg-red-500") == (("md", "hover"), "bg-red-500")
assert parse_utility("!p-4") == ((), "p-4")  # important-modifier stripped
print("PASS")

print()
print("=" * 60)
print("Check 2: family classification — the ambiguous text- prefix in particular")
print("=" * 60)
assert classify_family("p-4") == "padding-all"
assert classify_family("pt-4") == "padding-top"
assert classify_family("p-4") != classify_family("pt-4"), "p and pt must NOT share a family"
assert classify_family("text-left") == "text-align"
assert classify_family("text-sm") == "font-size"
assert classify_family("text-red-500") == "text-color"
assert classify_family("some-unknown-utility") is None
print("PASS")

print()
print("=" * 60)
print("Check 3: end-to-end against sample_tailwind_project")
print("=" * 60)
scan_result = scan_project(FIXTURE, job_id="test-tailwind")
jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
jsx_results = parse_jsx_files(jsx_files_to_parse, FIXTURE)
for r in jsx_results:
    assert not r.parse_errors, f"{r.file_path} failed to parse: {r.parse_errors}"

issues = detect_tailwind_conflicts(jsx_results, _id_gen())
assert len(issues) == 3, f"expected exactly 3 real conflicts, got {len(issues)}: {[i.class_name for i in issues]}"

class_names = {i.class_name for i in issues}
assert "p-4, p-2" in class_names, class_names
assert "hover:bg-red-500, hover:bg-blue-500" in class_names, class_names
assert "flex, block" in class_names, class_names

# Explicitly confirm the false-positive traps did NOT fire
flagged_text = " | ".join(class_names)
assert "pt-2" not in flagged_text, "p-4 + pt-2 (legit override) was wrongly flagged"
assert "md:p-2" not in flagged_text, "p-4 + md:p-2 (responsive override) was wrongly flagged"
assert "hover:bg-blue-500, bg-red-500" not in flagged_text and "bg-red-500" not in flagged_text.replace("hover:bg-red-500", ""), \
    "bg-red-500 + hover:bg-blue-500 (different variant scope) was wrongly flagged"

for i in issues:
    assert i.issue_type == "tailwind_utility_conflict"
    assert i.severity == "medium"

print("PASS — exactly the 3 real conflicts found, all 3 false-positive traps correctly ignored")

print()
print("All Tailwind conflict checks PASSED.")
