"""
Regression test for two bugs found and fixed in the same session:

  1. THE UNRESOLVED-APP BUG (reachability_lookup.py)
     When app-boundary detection can't resolve ANY application for a file
     (no import-graph entry, no folder-based fallback match), apps_for()
     and jsx_reachable_apps() used to return an EMPTY set. Two files that
     both hit this case would then have empty & empty = empty intersection
     in _has_confirmed_usage(), which can never be non-empty — permanently
     blocking confirmed_conflict, and worse, causing _cluster_by_reach to
     never link them into the same cluster at all, so a genuine same-app
     conflict got reported as `isolated_duplicate` (i.e. "NOT a conflict").
     Fix: unresolved files now share a sentinel (UNRESOLVED_APP) instead
     of an empty set, so they correctly cluster together.

  2. THE DEAD-CODE SEVERITY BUG (scope_aware_conflicts.py)
     `severity = "medium" if conflicting_properties == shared_properties
     else "medium"` — both branches always evaluated to "medium", so every
     non-confirmed conflict got the same severity regardless of how much
     of the overlap conflicted or how impactful the properties were.
     Fix: severity is now "medium" only when a meaningful fraction of
     shared properties conflict AND at least one is layout/appearance-
     affecting; otherwise "low".

This is deliberately a focused unit test on reachability_lookup.py +
scope_aware_conflicts.py directly, NOT a full scan-pipeline test like
test_scope_aware_conflicts.py — the full pipeline needs the js_helper
Node/Babel dependency installed and goes through codebase_mapper's
single_app_fallback, which makes the specific "nothing resolves at all"
edge case unreliable to force from real fixture files. Testing these two
modules directly is the right level for this bug.

Run: python test_reachability_fallback.py
"""
from app.models import (
    CSSClassDefinitionRef, CSSDeclaration, JSXClassUsageRef,
    ReachabilityGraph,
)
from app.relationship_model import RelationshipModel
from app.reachability_lookup import ReachabilityLookup, UNRESOLVED_APP
from app.scope_aware_conflicts import detect_scope_aware_conflicts


def _id_gen():
    counter = {"n": 0}
    def gen():
        counter["n"] += 1
        return f"issue-{counter['n']}"
    return gen


def _two_file_conflict_model(prop="color", val_a="red", val_b="blue"):
    model = RelationshipModel()
    model.css_classes = {
        "widget": [
            CSSClassDefinitionRef(file_path="a.css", line_number=1, selector=".widget",
                declarations=[CSSDeclaration(property=prop, value=val_a)]),
            CSSClassDefinitionRef(file_path="b.css", line_number=1, selector=".widget",
                declarations=[CSSDeclaration(property=prop, value=val_b)]),
        ]
    }
    model.jsx_usages = {
        "widget": [JSXClassUsageRef(file_path="App.jsx", line_number=1, element="div", is_fully_static=True)]
    }
    return model


print("=" * 60)
print("Test 1: totally unresolved app boundary (today's bug)")
print("=" * 60)
graph = ReachabilityGraph(applications=[], css_reachable_from={}, unreached_css_files=[], warnings=[])
reach = ReachabilityLookup(graph, codebase_map=None)
model = _two_file_conflict_model()
issues = detect_scope_aware_conflicts(model, reach, _id_gen())
widget = [i for i in issues if i.class_name == "widget"]
assert len(widget) == 1, f"expected 1 issue, got {len(widget)}"
assert widget[0].conflict_category == "confirmed_conflict", (
    f"expected confirmed_conflict, got {widget[0].conflict_category} "
    f"(this is the exact bug: unresolved files used to be treated as "
    f"isolated instead of same-context)"
)
assert widget[0].severity == "high", f"expected high, got {widget[0].severity}"
assert UNRESOLVED_APP not in widget[0].reaching_applications, (
    "raw sentinel leaked into a user-facing field"
)
print("PASS — unresolved-app conflict correctly confirmed as high severity")
print(f"  reaching_applications (display): {widget[0].reaching_applications}")

print()
print("=" * 60)
print("Test 2: genuinely separate resolved apps stay isolated (no regression)")
print("=" * 60)
from app.models import ApplicationReachability
graph2 = ReachabilityGraph(
    applications=[
        ApplicationReachability(application_name="admin", application_root="admin",
            reachable_jsx_files=["admin/App.jsx"], reachable_css_files=["a.css"],
            reachability_method="import_graph"),
        ApplicationReachability(application_name="customer", application_root="customer",
            reachable_jsx_files=["customer/App.jsx"], reachable_css_files=["b.css"],
            reachability_method="import_graph"),
    ],
    css_reachable_from={"a.css": ["admin"], "b.css": ["customer"]},
    unreached_css_files=[], warnings=[],
)
reach2 = ReachabilityLookup(graph2, codebase_map=None)
model2 = _two_file_conflict_model()
model2.jsx_usages = {
    "widget": [JSXClassUsageRef(file_path="admin/App.jsx", line_number=1, element="div", is_fully_static=True)]
}
issues2 = detect_scope_aware_conflicts(model2, reach2, _id_gen())
widget2 = [i for i in issues2 if i.class_name == "widget"]
assert len(widget2) == 1, f"expected 1 issue, got {len(widget2)}"
assert widget2[0].conflict_category == "isolated_duplicate", (
    f"expected isolated_duplicate, got {widget2[0].conflict_category} — "
    f"two files with genuinely different, resolved apps should NOT cluster "
    f"together just because the sentinel fix exists"
)
print("PASS — real cross-app isolation still correctly detected (no over-merging)")

print()
print("=" * 60)
print("Test 3: severity reflects property impact, not a coin flip (dead-code fix)")
print("=" * 60)
# Same app, but usage is NOT confirmed (usage file not reachable from the
# cluster's app) — forces the partial_overlap_class / potential_conflict
# branch where the old code always said "medium" no matter what.
graph3 = ReachabilityGraph(
    applications=[
        ApplicationReachability(application_name="admin", application_root="admin",
            reachable_jsx_files=["OTHER.jsx"], reachable_css_files=["a.css", "b.css"],
            reachability_method="import_graph"),
    ],
    css_reachable_from={"a.css": ["admin"], "b.css": ["admin"]},
    unreached_css_files=[], warnings=[],
)
reach3 = ReachabilityLookup(graph3, codebase_map=None)

# 3a: conflicting property is cosmetic-only (cursor) -> should be "low"
model_low = _two_file_conflict_model(prop="cursor", val_a="pointer", val_b="default")
issues_low = detect_scope_aware_conflicts(model_low, reach3, _id_gen())
w_low = [i for i in issues_low if i.class_name == "widget"][0]
assert w_low.severity == "low", f"expected low for cosmetic-only conflict, got {w_low.severity}"
print(f"PASS — cursor-only conflict correctly downgraded to 'low' (was hardcoded 'medium')")

# 3b: conflicting property is layout-affecting (color) -> should be "medium"
model_med = _two_file_conflict_model(prop="color", val_a="red", val_b="blue")
issues_med = detect_scope_aware_conflicts(model_med, reach3, _id_gen())
w_med = [i for i in issues_med if i.class_name == "widget"][0]
assert w_med.severity == "medium", f"expected medium for color conflict, got {w_med.severity}"
print(f"PASS — color conflict correctly stays 'medium'")

print()
print("All reachability-fallback / severity-signal checks PASSED.")