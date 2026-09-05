"""
Standalone chat command router test — no server, no Ollama.
Run: python test_chat_commands.py

Part A: detect_command() against every exact phrase from spec section 21,
including the two that must NOT match (they're open-ended questions meant
to fall through to the free-form LLM chat, already proven grounded in
Phase 4's test_ai_context_builder.py).

Part B: each deterministic handler actually runs, using the real
sample_multiapp_project fixture — no mocking of fix_planner/patch_generator
/sandbox_validator, so this proves the whole command -> real backend call
chain works end to end.
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware
from app.job_cache import JobData
from app.chat_commands import detect_command, handle_chat_message

PROJECT = "sample_multiapp_project"


def build_job():
    scan_result = scan_project(PROJECT, job_id="local-test")
    css_results = [parse_css_file(f.absolute_path, f.relative_path) for f in scan_result.css_files]
    jsx_files_to_parse = [(f.absolute_path, f.relative_path) for f in scan_result.jsx_files + scan_result.js_files]
    jsx_results = parse_jsx_files(jsx_files_to_parse, PROJECT)
    model = build_relationship_model(css_results, jsx_results)
    codebase_map = build_codebase_map(scan_result)
    reachability_graph = build_reachability_graph(codebase_map, jsx_results)
    issues = detect_issues_scope_aware(model, reachability_graph, codebase_map)
    return JobData(issues, css_results, jsx_results, codebase_map, reachability_graph, scan_result.root_path)


if __name__ == "__main__":
    print("=" * 70)
    print("Part A: command detection against spec section 21's exact phrases")
    print("=" * 70)
    cases = [
        ("Explain this issue.", None),
        ("Why is this a conflict?", None),
        ("But there is another `.button` in the customer folder. Why isn't that a conflict?", None),
        ("Which component is affected?", "which_component"),
        ("What is the safest fix?", "safest_fix"),
        ("Show me the files involved.", "show_files"),
        ("Generate a fix.", "generate_fix"),
        ("Validate the fix.", "validate_fix"),
        ("Why did the fix fail?", "why_failed"),
        ("Fix it.", "fix_it"),
    ]
    for message, expected in cases:
        got = detect_command(message)
        status = "PASS" if got == expected else "FAIL"
        print(f"  [{status}] '{message}' -> {got}  (expected {expected})")
        assert got == expected, f"'{message}' expected {expected}, got {got}"
    print("All command-detection cases PASSED.\n")

    print("=" * 70)
    print("Part B: real end-to-end command handling")
    print("=" * 70)
    job = build_job()
    panel_issue = next(i for i in job.issues if i.class_name == "panel" and i.conflict_category == "confirmed_conflict")
    btn_issue = next(i for i in job.issues if i.class_name == "btn-primary")

    print("\n--- 'Which component is affected?' (panel) ---")
    reply = handle_chat_message(panel_issue, job, "Which component is affected?")
    print(reply)
    assert "Dashboard.jsx" in reply
    print("PASS")

    print("\n--- 'Show me the files involved.' (panel) ---")
    reply = handle_chat_message(panel_issue, job, "Show me the files involved.")
    print(reply)
    assert "admin/src/styles/global.css" in reply
    assert "admin/src/components/Dashboard/dashboard.css" in reply
    print("PASS")

    print("\n--- 'What is the safest fix?' (panel) ---")
    reply = handle_chat_message(panel_issue, job, "What is the safest fix?")
    print(reply)
    assert "global.css" in reply
    assert "blast radius 0" in reply
    print("PASS")

    print("\n--- 'Generate a fix.' (panel) ---")
    reply = handle_chat_message(panel_issue, job, "Generate a fix.")
    print(reply)
    assert "global.css" in reply
    assert panel_issue.id in job.last_patch
    print("PASS")

    print("\n--- 'Validate the fix.' (panel, using the patch just generated) ---")
    reply = handle_chat_message(panel_issue, job, "Validate the fix.")
    print(reply)
    assert "PASSED" in reply
    print("PASS")

    print("\n--- 'Fix it.' (btn-primary, isolated -> must refuse with 0 sandbox runs) ---")
    reply = handle_chat_message(btn_issue, job, "Fix it.")
    print(reply)
    assert "Isolated duplicates are explicitly excluded" in reply
    print("PASS")

    print("\n--- 'Why did the fix fail?' (btn-primary, right after the refusal above) ---")
    reply = handle_chat_message(btn_issue, job, "Why did the fix fail?")
    print(reply)
    assert "Isolated duplicates are explicitly excluded" in reply
    print("PASS")

    print("\n--- 'Fix it.' (panel, real end-to-end loop) ---")
    reply = handle_chat_message(panel_issue, job, "Fix it.")
    print(reply)
    assert "Validated fix found" in reply
    assert "global.css" in reply
    print("PASS")

    print("\nAll Phase 7 chat command checks PASSED.")
