"""
Standalone iterative fix loop test — no server, no Ollama.
Run: python test_fix_loop.py

  1. '.btn-primary' (isolated) -> loop must return success=False
     IMMEDIATELY, zero attempts, same refusal reason as fix_planner.
  2. '.panel' (confirmed conflict, real fixture) -> loop should succeed
     on attempt 1, since the smallest-blast-radius candidate already
     passes sandbox validation.
  3. Synthetic retry test: monkeypatch validate_patch_in_sandbox (inside
     fix_loop's own imported reference) so the FIRST candidate always
     fails and the SECOND always passes — proves the loop actually
     retries with the next candidate rather than giving up after one
     failure, independent of whether real fixture data happens to pass
     on the first try.
  4. Synthetic exhaustion test: force every attempt to fail, confirm the
     loop stops at MAX_ATTEMPTS (3) rather than looping forever, and
     reports failure with all attempts' evidence attached.
"""
from app.scanner import scan_project
from app.css_parser import parse_css_file
from app.jsx_parser import parse_jsx_files
from app.relationship_model import build_relationship_model
from app.codebase_mapper import build_codebase_map
from app.import_graph import build_reachability_graph
from app.issue_detector import detect_issues_scope_aware
from app.job_cache import JobData
from app.models import ValidationResult
import app.fix_loop as fix_loop_module

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
    job = build_job()

    btn_issue = next(i for i in job.issues if i.class_name == "btn-primary")
    panel_issue = next(i for i in job.issues if i.class_name == "panel" and i.conflict_category == "confirmed_conflict")

    print("=" * 70)
    print("1) '.btn-primary' (isolated) -> must refuse immediately, 0 attempts")
    print("=" * 70)
    btn_result = fix_loop_module.attempt_validated_fix(btn_issue, job)
    print(f"success: {btn_result.success}")
    print(f"attempts: {len(btn_result.attempts)}")
    print(f"final_message: {btn_result.final_message}")
    assert btn_result.success is False
    assert len(btn_result.attempts) == 0
    print("PASS\n")

    print("=" * 70)
    print("2) '.panel' (real fixture) -> should succeed on attempt 1")
    print("=" * 70)
    panel_result = fix_loop_module.attempt_validated_fix(panel_issue, job)
    print(f"success: {panel_result.success}")
    print(f"attempts: {len(panel_result.attempts)}")
    print(f"final_message: {panel_result.final_message}")
    assert panel_result.success is True
    assert panel_result.attempts[0].validation.passed is True
    print("PASS\n")

    print("=" * 70)
    print("3) Synthetic retry test: attempt 1 fails, attempt 2 succeeds")
    print("=" * 70)
    call_count = {"n": 0}
    real_validate = fix_loop_module.validate_patch_in_sandbox

    def fake_validate(issue, patch, job):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ValidationResult(
                passed=False, original_issue_resolved=False, new_conflicts_introduced=1,
                notes=["synthetic failure for test purposes"],
            )
        return real_validate(issue, patch, job)

    fix_loop_module.validate_patch_in_sandbox = fake_validate
    try:
        retry_result = fix_loop_module.attempt_validated_fix(panel_issue, job)
    finally:
        fix_loop_module.validate_patch_in_sandbox = real_validate

    print(f"success: {retry_result.success}")
    print(f"attempts: {len(retry_result.attempts)}")
    print(f"attempt 1 passed: {retry_result.attempts[0].validation.passed}")
    if len(retry_result.attempts) > 1:
        print(f"attempt 2 passed: {retry_result.attempts[1].validation.passed}")
    assert retry_result.attempts[0].validation.passed is False
    assert retry_result.success is True, "loop should have retried and succeeded on the 2nd candidate"
    assert len(retry_result.attempts) == 2
    print("PASS: loop correctly retried after the first failure.\n")

    print("=" * 70)
    print("4) Synthetic exhaustion test: every attempt fails -> stop at MAX_ATTEMPTS")
    print("=" * 70)

    def always_fail_validate(issue, patch, job):
        return ValidationResult(
            passed=False, original_issue_resolved=False, new_conflicts_introduced=1,
            notes=["synthetic permanent failure for test purposes"],
        )

    fix_loop_module.validate_patch_in_sandbox = always_fail_validate
    try:
        exhausted_result = fix_loop_module.attempt_validated_fix(panel_issue, job)
    finally:
        fix_loop_module.validate_patch_in_sandbox = real_validate

    print(f"success: {exhausted_result.success}")
    print(f"attempts: {len(exhausted_result.attempts)}")
    print(f"final_message: {exhausted_result.final_message}")
    assert exhausted_result.success is False
    # The real invariant: bounded by min(MAX_ATTEMPTS, available candidates),
    # never infinite. '.panel' only has 2 candidate files (global.css,
    # dashboard.css), so 2 attempts here is correct — MAX_ATTEMPTS=3 is a
    # ceiling, not a guarantee every issue has 3 candidates to try.
    assert 0 < len(exhausted_result.attempts) <= fix_loop_module.MAX_ATTEMPTS, (
        f"expected 1-{fix_loop_module.MAX_ATTEMPTS} attempts, got {len(exhausted_result.attempts)}"
    )
    assert all(not a.validation.passed for a in exhausted_result.attempts)
    assert "could not generate a validated fix" in exhausted_result.final_message
    print(f"PASS: loop stopped after exhausting its {len(exhausted_result.attempts)} available candidate(s), "
          f"never looped forever.\n")

    print("All Phase 6b iterative fix loop checks PASSED.")
