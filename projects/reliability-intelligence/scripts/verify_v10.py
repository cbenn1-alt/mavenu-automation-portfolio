"""V10 prototype freeze, risk list, and unsigned decision verification.

The technical V9 snapshot is pinned by Git blob SHA-1 object IDs (content
consistency only, not signed provenance). V10 does not alter the V9 runtime.
Verification emits local machine-checkable evidence but CANNOT sign the
prototype decision, assign accountable owners, or authorize formal promotion.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
BASELINE = PROJECT / "docs" / "releases" / "V10_BASELINE.json"
RISKS = PROJECT / "docs" / "RISK_REGISTER_V10.json"
DECISION = PROJECT / "docs" / "releases" / "V10_DECISION.json"
V8_BASELINE = PROJECT / "docs" / "releases" / "V8_BASELINE.json"
V9_REVIEWER_RECORD = PROJECT / "docs" / "V9_REVIEWER_RECORD_TEMPLATE.json"
EVIDENCE = PROJECT / "evidence" / "V10"
REPORT = EVIDENCE / "verification.json"

PINNED_PATHS = frozenset((
    "src/reliability_intelligence/__init__.py",
    "src/reliability_intelligence/__main__.py",
    "src/reliability_intelligence/api_v1.py",
    "src/reliability_intelligence/charter.py",
    "src/reliability_intelligence/diagnostics.py",
    "src/reliability_intelligence/fixtures.py",
    "src/reliability_intelligence/services.py",
    "src/reliability_intelligence/web.py",
    "src/reliability_intelligence/workflow.py",
    "src/reliability_intelligence/static/style.css",
    "fixtures/cases.json",
    "fixtures/demo_review_script.json",
    "fixtures/manifest.json",
    "fixtures/reference_labels.json",
    "product_charter.json",
    "requirements-dev.txt",
    "scripts/replay_v9.py",
    "docs/releases/V8_BASELINE.json",
))
SEVERITIES = frozenset(("low", "medium", "high", "critical"))
BLOCKING_SCOPES = frozenset((
    "formal_v10_acceptance", "customer_data_or_pilot", "commercial_build_decision"
))


class DecisionEvidenceError(ValueError):
    """A V10 governance invariant is not satisfied."""


def need(condition: Any, code: str) -> None:
    if not condition:
        raise DecisionEvidenceError(code)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise DecisionEvidenceError("document_missing_or_invalid") from None
    need(type(value) is dict, "document_not_object")
    return value


def git_blob_id(raw: bytes) -> str:
    """Compute Git object blob identity (SHA-1), not a security signature."""
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def verify_freeze(baseline: dict[str, Any], project: Path = PROJECT) -> dict[str, Any]:
    need(baseline.get("increment") == "V10", "baseline_wrong_increment")
    need(baseline.get("objective") == "Freeze prototype baseline and open risk list",
         "baseline_wrong_objective")
    need(baseline.get("required_proof") == "Prototype decision record",
         "baseline_wrong_proof")
    need(baseline.get("baseline_state") == "TECHNICAL_BASELINE_FROZEN",
         "baseline_wrong_state")
    need(baseline.get("baseline_commit") == "704123eca45628bf504594af39a66036cc0451c5",
         "baseline_does_not_reference_verified_v9")
    need(baseline.get("baseline_runtime_version") == "0.9.0", "runtime_version_drift")
    need(baseline.get("baseline_api_schema_version") == "1.3.0", "api_version_drift")
    need(baseline.get("baseline_data_mode") == "SYNTHETIC_ONLY", "non_synthetic_freeze")
    need(baseline.get("next_phase_promotion_authorized") is False,
         "premature_phase_authorization")
    for safety_flag in (
        "customer_live_data_authorized", "plc_scada_ot_or_cmms_writes_authorized",
        "production_deployment_authorized", "customer_outcomes_measured",
        "human_review_of_v9_performed", "product_owner_signoff",
    ):
        need(baseline.get(safety_flag) is False, "unsafe_baseline_status_" + safety_flag)

    paths = baseline.get("frozen_paths_git_blob_sha1")
    need(type(paths) is dict and set(paths) == PINNED_PATHS, "frozen_path_set_drift")
    need(baseline.get("frozen_file_count") == len(PINNED_PATHS),
         "frozen_file_count_drift")
    root = project.resolve()
    for relative, expected_blob in sorted(paths.items()):
        need(re.fullmatch(r"[0-9a-f]{40}", expected_blob) is not None,
             "invalid_git_blob_id")
        candidate = (root / relative).resolve()
        need(candidate.is_relative_to(root) and candidate.is_file(),
             "missing_or_untrusted_frozen_path")
        try:
            raw = candidate.read_bytes()
        except OSError:
            raise DecisionEvidenceError("cannot_read_frozen_file") from None
        need(git_blob_id(raw) == expected_blob, "frozen_source_integrity_mismatch")
    v9 = baseline.get("v9_ci", {})
    need(type(v9) is dict, "missing_v9_evidence")
    need(v9.get("conclusion") == "success" and v9.get("tests_passed") == 153,
         "v9_ci_record_mismatch")
    need(v9.get("run_id") == 42491392469, "v9_ci_reference_mismatch")
    need(v9.get("automated_socket_replay_checks_passed") == 12,
         "v9_socket_replay_mismatch")
    need(v9.get("measured_combined_coverage_percent") == 84.951,
         "v9_coverage_record_mismatch")
    need(v9.get("source_module_count") == 9, "v9_source_module_mismatch")
    need(v9.get("minimum_coverage_percent") == 84.5, "v8_coverage_floor_mismatch")
    need(re.fullmatch(r"[0-9a-f]{64}", v9.get("reproducible_demo_trace_sha256", "")) is not None,
         "v9_trace_digest_not_sha256")
    return {"frozen_files_verified": len(paths), "baseline_commit": baseline["baseline_commit"],
            "reference_tests_passed": v9["tests_passed"],
            "reference_coverage_percent": v9["measured_combined_coverage_percent"],
            "reference_local_replay_checks": v9["automated_socket_replay_checks_passed"]}


def verify_risks(risks: dict[str, Any]) -> dict[str, Any]:
    need(risks.get("increment") == "V10", "risk_increment_mismatch")
    entries = risks.get("risks")
    need(type(entries) is list and len(entries) >= 10, "risk_register_incomplete")
    ids: set[str] = set()
    blockers: set[str] = set()
    critical = 0
    for risk in entries:
        need(type(risk) is dict, "risk_entry_not_object")
        rid = risk.get("risk_id")
        need(type(rid) is str and re.fullmatch(r"RI-V10-R\d{2}", rid) is not None,
             "risk_id_invalid")
        need(rid not in ids, "duplicate_risk_id")
        ids.add(rid)
        need(risk.get("status") == "OPEN", "risk_closure_requires_human_review")
        need(risk.get("severity") in SEVERITIES, "risk_severity_invalid")
        need(risk.get("blocking_scope") in BLOCKING_SCOPES, "risk_scope_invalid")
        need(risk.get("impact_scope") == risk["blocking_scope"], "risk_impact_scope_drift")
        need(type(risk.get("summary")) is str and len(risk["summary"]) >= 25,
             "risk_summary_missing")
        need(type(risk.get("exit_evidence")) is str and len(risk["exit_evidence"]) >= 25,
             "risk_exit_evidence_missing")
        need(type(risk.get("proposed_owner_role")) is str and len(risk["proposed_owner_role"]) >= 5,
             "proposed_owner_role_missing")
        need(risk.get("assigned_owner") is None and risk.get("remediation_due_date") is None,
             "unapproved_owner_or_due_date")
        need(risk.get("reviewed_by") is None and risk.get("reviewed_on") is None,
             "unverified_risk_review_claim")
        if risk["severity"] == "critical":
            critical += 1
        if risk["blocking_scope"] == "formal_v10_acceptance":
            blockers.add(rid)
    need(risks.get("open_count") == len(entries), "risk_open_count_mismatch")
    need(risks.get("critical_count") == critical, "risk_critical_count_mismatch")
    declared = risks.get("formal_v10_blocker_ids")
    need(type(declared) is list and set(declared) == blockers and len(declared) == len(blockers),
         "blocking_risk_references_drift")
    need(len(blockers) >= 4, "missing_formal_phase_blockers")
    for flag in ("reviewer_assigned", "risk_owner_assignments_complete", "register_approved"):
        need(risks.get(flag) is False, "risk_register_false_approval_" + flag)
    return {"risk_count": len(entries), "critical_risks": critical,
            "formal_promotion_blockers": sorted(blockers), "unassigned_owners": len(entries)}


def verify_decision(decision: dict[str, Any], baseline: dict[str, Any],
                    risk_summary: dict[str, Any], v8: dict[str, Any],
                    v9_review: dict[str, Any]) -> dict[str, Any]:
    need(decision.get("increment") == "V10", "decision_increment_mismatch")
    need(decision.get("required_proof") == "Prototype decision record", "decision_proof_mismatch")
    need(decision.get("objective") == baseline["objective"], "objective_drift")
    need(decision.get("status") == "DRAFT_UNAPPROVED", "unsigned_decision_status_drift")
    need(decision.get("technical_baseline") == "FROZEN_V9_SNAPSHOT",
         "decision_baseline_scope_drift")
    need(decision.get("recommended_promotion_decision") == "BLOCKED",
         "required_blocking_recommendation_missing")
    need(decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
         "unsupported_formal_decision_claim")
    for key in ("named_decision_owner", "owner_signature", "decision_date"):
        need(decision.get(key) is None, "invented_decision_identity_" + key)
    for key in ("product_owner_approval", "independent_reviewer_approval",
                "formal_phase_promotion_authorized", "commercial_approval",
                "customer_data_or_ot_access", "deployment_authorization",
                "economic_benefit_verified"):
        need(decision.get(key) is False, "unsupported_decision_approval_" + key)
    need(decision.get("next_phase_internal_synthetic_experiments_allowed") is True,
         "synthetic_experiment_scope_missing")
    need(type(decision.get("conditions_for_reconsideration")) is list
         and len(decision["conditions_for_reconsideration"]) >= 5,
         "decision_exit_gates_missing")
    need(decision.get("blocking_risk_ids") == risk_summary["formal_promotion_blockers"],
         "decision_blocker_mismatch")
    evidence = decision.get("known_technical_evidence")
    need(type(evidence) is dict and evidence.get("baseline_commit") == baseline["baseline_commit"],
         "technical_evidence_baseline_mismatch")
    need(evidence.get("v9_ci_run_id") == baseline["v9_ci"]["run_id"],
         "technical_evidence_ci_reference_drift")
    need(evidence.get("v9_automated_tests") == baseline["v9_ci"]["tests_passed"],
         "technical_evidence_test_count_drift")
    need(evidence.get("human_reviewer_completed") is False,
         "false_human_replay_evidence")
    need(v8.get("status") == "measured_baseline_pending_human_signoff",
         "v8_baseline_human_approval_claim")
    need(v8.get("minimum_total_percent") == baseline["v9_ci"]["minimum_coverage_percent"],
         "v8_threshold_drift")
    need(v8.get("product_owner_signoff") is False,
         "v8_owner_approval_not_recorded")
    need(v9_review.get("formal_acceptance_granted") is False and
         v9_review.get("independent_human_replay_completed") is False,
         "v9_human_review_not_yet_signed")
    need(v9_review.get("reviewer_signature") is None,
         "v9_reviewer_signature_claim")
    return {
        "recommended_promotion_decision": "BLOCKED",
        "formal_decision": "PENDING_HUMAN_SIGNOFF",
        "signoff_complete": False,
        "formal_phase_promotion_authorized": False,
    }


def main() -> int:
    baseline = read_json(BASELINE)
    risks = read_json(RISKS)
    decision = read_json(DECISION)
    v8 = read_json(V8_BASELINE)
    reviewer = read_json(V9_REVIEWER_RECORD)
    freeze = verify_freeze(baseline)
    risk_summary = verify_risks(risks)
    decision_summary = verify_decision(decision, baseline, risk_summary, v8, reviewer)
    record = {
        "increment": "V10",
        "result": "technical_evidence_verified_formal_decision_blocked",
        "reference_source_version": "V9",
        "frozen_snapshot": freeze,
        "risk_register": risk_summary,
        "prototype_decision": decision_summary,
        "v10_ci_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "customer_system_access": False,
        "customer_data_used": False,
        "model_validation_or_business_outcome_claimed": False,
        "human_acceptance_performed_by_this_check": False,
        "next_phase_formally_approved": False,
        "note": "V10 technical freeze and decision evidence only. Human owner signature remains required.",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V10_DECISION_CHECK: " + json.dumps({
        "result": record["result"], "frozen_files": freeze["frozen_files_verified"],
        "open_risks": risk_summary["risk_count"],
        "formal_blockers": len(risk_summary["formal_promotion_blockers"]),
        "recommended_promotion": decision_summary["recommended_promotion_decision"],
        "human_signoff_complete": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DecisionEvidenceError, ValueError, KeyError, TypeError, OSError):
        print("V10_DECISION_CHECK_FAILED: source_or_governance_invariant", file=sys.stderr)
        raise SystemExit(1) from None
