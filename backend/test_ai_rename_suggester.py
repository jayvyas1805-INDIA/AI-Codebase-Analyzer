"""
Regression test for ai_rename_suggester.py + its wiring into
patch_generator.py's _generate_rename.

The real LLM provider isn't reachable from every environment (no
LLM_API_KEY set, or network restrictions), so this test mocks
llm_client.call_llm_chat directly rather than hitting a real provider —
what's being verified is OUR validation/fallback logic, not any
particular model's output quality.

Covers the filename_classname naming convention:
  1. A clean, valid LLM suggestion ('<slug>_<class_name>') is accepted.
  2. Messy filenames/responses (PascalCase, chatty text, quotes) are
     salvaged into the correct 'slug_classname' shape.
  3. Anything that does NOT follow the filename_classname convention
     (wrong/missing class-name suffix, empty slug, bad characters, a
     bracketed llm_client failure message) is rejected -> None, and the
     mechanical fallback (also filename_classname, computed with zero LLM
     involvement) is used instead.
  4. End-to-end through patch_generator: collision dedup still applies to
     LLM-sourced names exactly like the mechanical path.

Run: python test_ai_rename_suggester.py
"""
from unittest.mock import patch

from app.ai_rename_suggester import suggest_class_name, mechanical_class_name, VALID_CLASS_NAME
from app.models import (
    CSSClassDefinitionRef, CSSDeclaration, CSSFileParseResult, CSSRule,
    FixPlan, Issue, JSXClassUsageRef,
)


class FakeJob:
    """Minimal stand-in for job_cache.JobData — just enough for
    build_issue_context() and _existing_class_names() to run."""
    def __init__(self, css_results, existing_class_names=()):
        self.css_results = css_results
        self.jsx_results = []
        self.codebase_map = None
        self.reachability_graph = None


def _make_issue():
    return Issue(
        id="issue-1",
        issue_type="css_conflict",
        severity="high",
        class_name="panel",
        message="test",
        conflict_category="confirmed_conflict",
        css_definitions=[
            CSSClassDefinitionRef(file_path="admin/global.css", line_number=1, selector=".panel",
                declarations=[CSSDeclaration(property="padding", value="10px")]),
            CSSClassDefinitionRef(file_path="admin/dashboard.css", line_number=1, selector=".panel",
                declarations=[CSSDeclaration(property="padding", value="20px")]),
        ],
        jsx_usages=[JSXClassUsageRef(file_path="admin/Dashboard.jsx", line_number=3, element="div", is_fully_static=True)],
    )


def _make_plan(target_file="admin/global.css"):
    return FixPlan(
        issue_id="issue-1", class_name="panel", plannable=True,
        chosen_strategy="rename_scoped_class", target_file=target_file,
        risk="low", blast_radius=0, rationale="test", options_considered=[],
    )


print("=" * 60)
print("Check 0: mechanical_class_name computes filename_classname with zero LLM")
print("=" * 60)
assert mechanical_class_name("admin/global.css", "panel") == "global_panel"
assert mechanical_class_name("admin/OrderSummaryV2.css", "title") == "order_summary_v2_title"
print("PASS")

print()
print("=" * 60)
print("Check 1: clean valid suggestion ('slug_classname') is accepted")
print("=" * 60)
job = FakeJob(css_results=[])
issue, plan = _make_issue(), _make_plan()
with patch("app.ai_rename_suggester.call_llm_chat", return_value="global_panel"):
    name = suggest_class_name(issue, plan, job)
assert name == "global_panel", name
print(f"PASS — got {name!r}")

print()
print("=" * 60)
print("Check 2a: PascalCase filename slug is converted, not flattened or rejected")
print("=" * 60)
plan_pascal = _make_plan(target_file="admin/OrderSummaryV2.css")
with patch("app.ai_rename_suggester.call_llm_chat", return_value="OrderSummaryV2Panel"):
    name = suggest_class_name(issue, plan_pascal, job)
assert name == "order_summary_v2_panel", (
    f"expected 'order_summary_v2_panel' (word boundaries preserved, class name "
    f"suffix intact), got {name!r}"
)
print(f"PASS — 'OrderSummaryV2Panel' -> {name!r}")

print()
print("=" * 60)
print("Check 2b: chatty response gets first-token salvage (documented, intentional)")
print("=" * 60)
with patch("app.ai_rename_suggester.call_llm_chat", return_value="global_panel is a good name"):
    name = suggest_class_name(issue, plan, job)
assert name == "global_panel", f"expected first-token salvage to yield 'global_panel', got {name!r}"
print(f"PASS — chatty response correctly salvaged down to {name!r}")

print()
print("=" * 60)
print("Check 2c: responses that DON'T follow filename_classname are rejected (-> None)")
print("=" * 60)
bad_responses = {
    "empty": "",
    "too_long": "a_" * 40 + "panel",
    "llm_client_failure": "[AI explanation unavailable — LLM_API_KEY is not set for provider 'groq'.]",
    "leading_digit": "1st_panel",
    "wrong_class_suffix": "global_card",          # dropped/changed the original class name
    "no_class_suffix_at_all": "global",            # missing the required '_panel' suffix
    "class_name_only_no_slug": "panel",            # suffix present but empty slug part
}
for label, response in bad_responses.items():
    with patch("app.ai_rename_suggester.call_llm_chat", return_value=response):
        result = suggest_class_name(issue, plan, job)
    assert result is None, f"{label}: expected None, got {result!r}"
    print(f"  PASS — {label} ({response!r}) correctly rejected")

print()
print("=" * 60)
print("Check 3: quoted-but-otherwise-clean suggestions ARE salvaged")
print("=" * 60)
# A model that wraps its answer in quotes despite instructions not to is
# common enough to be worth stripping rather than rejecting outright.
with patch("app.ai_rename_suggester.call_llm_chat", return_value='"global_panel"'):
    name = suggest_class_name(issue, plan, job)
assert name == "global_panel", name
print(f"PASS — quotes stripped, got {name!r}")

print()
print("=" * 60)
print("Check 4: end-to-end through patch_generator — collision dedup applies to LLM names too")
print("=" * 60)
from app.patch_generator import generate_patch

css_results = [
    CSSFileParseResult(file_path="admin/global.css", rules=[
        CSSRule(file_path="admin/global.css", selector=".panel", class_names=["panel"],
            declarations=[CSSDeclaration(property="padding", value="10px")], line_number=1, is_supported_selector=True),
    ], parse_errors=[], skipped_at_rules=[]),
    # A pre-existing class that collides with what the "LLM" will suggest,
    # to prove _dedupe_name() still runs on LLM-sourced names.
    CSSFileParseResult(file_path="somewhere/else.css", rules=[
        CSSRule(file_path="somewhere/else.css", selector=".global_panel", class_names=["global_panel"],
            declarations=[], line_number=1, is_supported_selector=True),
    ], parse_errors=[], skipped_at_rules=[]),
]


class FakeJobWithRoot(FakeJob):
    def __init__(self, css_results):
        super().__init__(css_results)
        self.root_path = "/tmp/does-not-need-to-exist-for-this-check"


job2 = FakeJobWithRoot(css_results)
issue2, plan2 = _make_issue(), _make_plan()
plan2.options_considered = [
    __import__("app.models", fromlist=["FixOption"]).FixOption(
        strategy="rename_scoped_class", description="test", blast_radius=0,
        risk="low", affected_files=["admin/global.css"],
    )
]

# Write the real file to disk since patch_generator reads actual source lines
import os
os.makedirs("/tmp/dedup_test/admin", exist_ok=True)
with open("/tmp/dedup_test/admin/global.css", "w") as f:
    f.write(".panel {\n  padding: 10px;\n}\n")
job2.root_path = "/tmp/dedup_test"

with patch("app.ai_rename_suggester.call_llm_chat", return_value="global_panel"):
    patch_result = generate_patch(issue2, plan2, job2)

changed_file = next(f for f in patch_result.files if f.path == "admin/global.css")
changed_line = changed_file.changes[0].replacement
assert "global_panel-2" in changed_line, (
    f"expected the LLM name to be deduped to 'global_panel-2' (collides with "
    f"an existing class), got: {changed_line!r}"
)
assert "AI-suggested" in patch_result.description
print(f"PASS — LLM-suggested 'global_panel' correctly deduped to 'global_panel-2': {changed_line.strip()!r}")

print()
print("=" * 60)
print("Check 5: with no LLM configured, the mechanical fallback also uses filename_classname")
print("=" * 60)
with patch("app.ai_rename_suggester.call_llm_chat",
           return_value="[AI explanation unavailable — LLM_API_KEY is not set for provider 'groq'.]"):
    patch_result_mech = generate_patch(issue2, plan2, job2)
changed_file_mech = next(f for f in patch_result_mech.files if f.path == "admin/global.css")
assert "global_panel" in changed_file_mech.changes[0].replacement
assert "mechanically generated" in patch_result_mech.description
print("PASS — mechanical fallback also produced a filename_classname-shaped name")

print()
print("All ai_rename_suggester checks PASSED.")
