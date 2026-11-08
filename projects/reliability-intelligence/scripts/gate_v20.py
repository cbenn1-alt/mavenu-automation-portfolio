"""V20 data-quality gate: synthetic evidence verification, NOT sign-off.

Mavenu AI SaaS Platform Development Architecture V4 p.42:
V20 Approve data correctness test baseline. Proof: Data quality sign-off.

No code path can auto-sign, approve a source dictionary, promote Phase 02,
authorize V21/customer data/OT, or create an apparent human reviewer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT / "docs" / "data" / "DATA_QUALITY_BASELINE_V20.json"
SIGNOFF_PATH = PROJECT / "docs" / "releases" / "V20_SIGNOFF.json"

EXPECTED_STAGES = [
    ("V11", "Approved source/field dictionary",
     "evidence/V11/verification.json", "technical_dictionary_verified_approval_pending"),
    ("V12", "Schema validation test report",
     "evidence/V12/schema_validation_report.json", "synthetic_schema_validated_approval_pending"),
    ("V13", "Negative-case fixtures",
     "evidence/V13/negative_case_report.json", "synthetic_negative_cases_passed_governance_pending"),
    ("V14", "Repeated-ingest comparison",
     "evidence/V14/repeated_ingest_comparison.json",
     "synthetic_idempotency_verified_formal_approval_pending"),
    ("V15", "Conversion reference tests",
     "evidence/V15/conversion_reference_report.json",
     "synthetic_conversions_verified_formal_approval_pending"),
    ("V16", "Record-level trace sample",
     "evidence/V16/lineage_verification.json",
     "synthetic_reconstructed_lineage_verified_human_approval_pending"),
    ("V17", "Expected-output fixtures",
     "evidence/V17/golden_reference_report.json",
     "authored_synthetic_reference_outputs_matched_approval_pending"),
    ("V18", "Adverse-case regression suite",
     "evidence/V18/adverse_regression_report.json",
     "synthetic_adverse_cases_verified_human_approval_pending"),
    ("V19", "Independent computation results",
     "evidence/V19/independent_reconciliation_report.json",
     "independent_synthetic_computation_reconciled_signoff_pending"),
]
EXPECTED_CHECKS = {
    "V11": {"dataset_count": 4, "owner_approval_obtained": False,
            "customer_data_authorized": False},
    "V12": {"frozen_source_files_verified": 18,
            "human_approval_completed": False},
    "V13": {"case_execution.negative_cases_rejected": 29,
            "case_execution.valid_boundary_cases_accepted": 7},
    "V14": {"comparison.replayed_duplicate_count": 34,
            "comparison.scenario_count": 16, "customer_data_used": False},
    "V15": {"accepted_reference_tests": 27,
            "rejected_reference_tests": 24, "customer_data_used": False},
    "V16": {"source_records": 34, "transforms_replayed": 36,
            "sample_record_count": 5, "actual_ingest_event_observed": False},
    "V17": {"verified_output_counts.total_synthetic_reference_values_verified": 25,
            "independent_domain_ground_truth": False},
    "V18": {"adverse_results.negative_cases": 44,
            "adverse_results.positive_controls": 5, "customer_data_used": False},
    "V19": {"reconciliation.reconciled_output_units": 25,
            "adverse_comparison_count": 16, "v19_reconciliation_approved": False},
}
BLOCKER_IDS = [f"G20-{i:02d}" for i in range(1, 9)]
SIGNATURE_FIELDS = (
    "named_product_owner", "named_customer_data_owner",
    "named_independent_reviewer", "named_security_ot_reviewer",
    "decision_date_utc", "evidence_commit", "approved_scope",
    "owner_signature", "independent_reviewer_signature",
    "customer_source_approval_signature", "security_ot_review_signature"
)
FALSE_FIELDS = (
    "phase_signoff_granted", "residual_risks_accepted",
    "formal_v10_gate_resolved"
)


class QualityGateRejected(ValueError):
    """Stable diagnostic only. Do not include external input data in errors."""


def need(condition: Any, code: str) -> None:
    if not condition:
        raise QualityGateRejected(code)


def read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise QualityGateRejected("required_policy_unavailable") from None
    need(type(obj) is dict, "policy_not_object")
    return obj


def baseline() -> dict[str, Any]:
    return read_json(BASELINE_PATH)


def signoff() -> dict[str, Any]:
    return read_json(SIGNOFF_PATH)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    try:
        return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True, allow_nan=False).encode("ascii"))
    except (TypeError, ValueError, OverflowError):
        raise QualityGateRejected("noncanonical_evidence") from None


def _path(record: dict[str, Any], dotted: str) -> Any:
    current: Any = record
    for segment in dotted.split("."):
        need(type(current) is dict and segment in current,
             "missing_evidence_field")
        current = current[segment]
    return current


def exact_value(actual: Any, expected: Any) -> bool:
    return type(actual) is type(expected) and actual == expected


def validate_signature_form(form: dict[str, Any]) -> None:
    """Validate a *blank* template only; it is not a signature processor."""
    need(type(form) is dict and form.get("record_state") ==
         "UNSIGNED_DRAFT_DO_NOT_USE_AS_APPROVAL", "signoff_template_state")
    for key in SIGNATURE_FIELDS:
        need(key in form and form[key] is None,
             "fabricated_signature_or_owner")
    for key in FALSE_FIELDS:
        need(form.get(key) is False, "unapproved_signature_claim")


def validate_baseline(register: dict[str, Any],
                      signoff_record: dict[str, Any]) -> None:
    need(type(register) is dict and register.get("schema_version") == "1.0.0",
         "baseline_schema_version")
    need(register.get("increment") == "V20" and
         register.get("objective") == "Approve data correctness test baseline" and
         register.get("required_proof") == "Data quality sign-off",
         "baseline_objective_drift")
    need(register.get("data_classification") == "FABRICATED_SYNTHETIC_ONLY" and
         register.get("fixture_set_id") == "SYN-RI-V5-20261107-A" and
         register.get("pinned_v9_source_commit") ==
         "704123eca45628bf504594af39a66036cc0451c5",
         "baseline_source_provenance_drift")
    need(register.get("governance_decision_path") ==
         "docs/releases/V10_DECISION.json" and
         register.get("v11_dictionary_path") ==
         "docs/data/SOURCE_FIELD_DICTIONARY_V11.json" and
         register.get("v12_schema_path") ==
         "docs/data/SCHEMA_CONTRACT_V12.json",
         "baseline_governance_path_drift")
    evidence = register.get("evidence_policy")
    need(type(evidence) is dict and
         evidence.get("minimum_total_regression_tests") == 754 and
         exact_value(evidence.get("minimum_combined_coverage_percent"), 84.5) and
         evidence.get("expected_v10_frozen_paths") == 18 and
         evidence.get("require_each_stage_distinct") is True and
         evidence.get("require_all_report_checks") is True and
         evidence.get("source_digest_algorithm") == "SHA-256" and
         evidence.get("evidence_digest_algorithm") == "SHA-256",
         "evidence_quality_policy_drift")
    stages = evidence.get("required_stages")
    need(type(stages) is list and len(stages) == 9,
         "stage_inventory_missing")
    for entry, (version, proof, path, result) in zip(stages, EXPECTED_STAGES):
        need(type(entry) is dict and
             entry.get("increment") == version and
             entry.get("proof") == proof and
             entry.get("evidence_path") == path and
             entry.get("expected_result") == result and
             entry.get("checks") == EXPECTED_CHECKS[version],
             "stage_evidence_contract_drift")
    supporting = evidence.get("supporting_evidence")
    need(supporting == [
        {"increment": "V8", "evidence_path": "evidence/V8/verification.json",
         "checks": {"coverage_floor_passed": True, "test_count_floor_passed": True}},
        {"increment": "V10", "evidence_path": "evidence/V10/verification.json",
         "checks": {"next_phase_formally_approved": False,
                    "frozen_snapshot.frozen_files_verified": 18}},
    ], "supporting_evidence_contract_drift")
    gate = register.get("gate_policy")
    need(type(gate) is dict and gate.get("technical_evidence_state") ==
         "CAN_PASS_WITHOUT_HUMAN_SIGNATURE" and gate.get("human_approval_state") ==
         "BLOCKED_PENDING_HUMAN_SIGNOFF" and gate.get("recommended_decision") ==
         "DO_NOT_PROMOTE" and gate.get("passing_ci_is_not_signoff") is True,
         "gate_decision_policy_drift")
    for flag in ("future_phase_v21_authorized", "production_ingestion_authorized",
                 "customer_data_authorized", "ot_or_cmms_write_authorized"):
        need(gate.get(flag) is False, "unauthorized_next_phase_or_customer_access")
    blockers = gate.get("blocking_items")
    need(type(blockers) is list and len(blockers) == 8 and
         [b.get("id") for b in blockers if type(b) is dict] == BLOCKER_IDS,
         "blocking_issue_inventory_drift")
    for item in blockers:
        need(type(item.get("owner_role")) is str and
             len(item["owner_role"]) > 5 and
             type(item.get("issue")) is str and len(item["issue"]) > 30 and
             type(item.get("resolution_proof")) is str and
             len(item["resolution_proof"]) > 20,
             "blocking_issue_evidence_missing")
    form = register.get("signature_template")
    validate_signature_form(form)
    need(type(signoff_record) is dict and
         signoff_record.get("increment") == "V20" and
         signoff_record.get("required_proof") == "Data quality sign-off" and
         signoff_record.get("decision") == "BLOCKED_PENDING_HUMAN_SIGNOFF" and
         signoff_record.get("authorization_to_advance") is False and
         signoff_record.get("technically_verified_only") is True and
         signoff_record.get("blocking_ids") == BLOCKER_IDS,
         "signoff_decision_drift")
    validate_signature_form(signoff_record)
    for key in form:
        need(key in signoff_record and exact_value(form[key], signoff_record[key]),
             "signoff_form_mismatch")


def validate_source_approvals(root: Path = PROJECT) -> dict[str, Any]:
    """Verify upstream approvals remain *unsigned*, never promote them."""
    decision = read_json(root / "docs/releases/V10_DECISION.json")
    dictionary = read_json(root / "docs/data/SOURCE_FIELD_DICTIONARY_V11.json")
    contract = read_json(root / "docs/data/SCHEMA_CONTRACT_V12.json")
    need(decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF" and
         decision.get("recommended_promotion_decision") == "BLOCKED" and
         decision.get("formal_phase_promotion_authorized") is False and
         decision.get("owner_signature") is None,
         "upstream_v10_gate_not_blocked")
    need(dictionary.get("dictionary_status") ==
         "DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED" and
         dictionary.get("product_owner_approved") is False and
         dictionary.get("customer_source_authorized") is False and
         dictionary.get("approval_record", {}).get("signatures") == [],
         "unsigned_v11_dictionary_claim")
    need(contract.get("contract_status") ==
         "TECHNICALLY_CHECKABLE_DRAFT_NOT_APPROVED" and
         contract.get("dictionary_approval_status") == "PENDING",
         "unsigned_v12_schema_claim")
    return {
        "v10_formal_promotion": "BLOCKED_RECOMMENDATION_PENDING_HUMAN_SIGNOFF",
        "v11_dictionary": "DRAFT_NOT_APPROVED",
        "v12_schema": "DRAFT_NOT_APPROVED",
        "customer_source_authorized": False,
    }


def verify_proof_entries(register: dict[str, Any],
                         evidence_by_path: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Validate exact expected report results and every required check."""
    manifest = []
    entries = (
        register["evidence_policy"]["supporting_evidence"] +
        register["evidence_policy"]["required_stages"]
    )
    need(type(evidence_by_path) is dict and len(entries) == 11 and
         set(evidence_by_path) == {x["evidence_path"] for x in entries},
         "proof_evidence_inventory_incomplete")
    for entry in entries:
        path = entry["evidence_path"]
        result = evidence_by_path[path]
        need(type(result) is dict and result.get("increment") == entry["increment"],
             "proof_increment_mismatch")
        if "expected_result" in entry:
            need(result.get("result") == entry["expected_result"],
                 "proof_result_mismatch")
        for field, expected in entry["checks"].items():
            actual = _path(result, field)
            need(exact_value(actual, expected), "proof_field_mismatch")
        manifest.append({
            "increment": entry["increment"],
            "proof": entry.get("proof", "Historical technical prerequisite"),
            "evidence_path": path,
            "status": "TECHNICAL_EVIDENCE_PRESENT_NOT_HUMAN_APPROVAL",
            "required_checks_passed": len(entry["checks"]),
            "canonical_report_sha256": canonical_sha256(result),
        })
    return {
        "reports_verified": len(manifest),
        "v11_v19_reports_verified": 9,
        "supporting_reports_verified": 2,
        "all_expected_fields_matched": True,
        "manifest": manifest,
    }


def evaluate_quality_gate(register: dict[str, Any],
                          form: dict[str, Any],
                          evidence_by_path: dict[str, dict[str, Any]],
                          coverage_percent: float,
                          test_count: int) -> dict[str, Any]:
    validate_baseline(register, form)
    need(type(test_count) is int and
         test_count >= register["evidence_policy"]["minimum_total_regression_tests"],
         "test_inventory_below_baseline")
    need(type(coverage_percent) in (float, int) and
         not isinstance(coverage_percent, bool) and
         coverage_percent >=
         register["evidence_policy"]["minimum_combined_coverage_percent"],
         "source_coverage_below_floor")
    v8_report = evidence_by_path.get("evidence/V8/verification.json", {})
    need(exact_value(v8_report.get("test_count"), test_count),
         "coverage_test_count_mismatch")
    need(type(v8_report.get("coverage_total_percent")) in (float, int) and
         abs(float(v8_report["coverage_total_percent"]) -
             float(coverage_percent)) < 0.0001,
         "coverage_report_mismatch")
    technical = verify_proof_entries(register, evidence_by_path)
    return {
        "technical_evidence": "PASS",
        "human_data_quality_signoff": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "formal_phase_02_approval": False,
        "future_phase_v21_authorized": False,
        "customer_data_authorized": False,
        "production_deployment_authorized": False,
        "owner_signature_observed": False,
        "decision": "DO_NOT_PROMOTE",
        "tests_verified": test_count,
        "source_coverage_percent": round(float(coverage_percent), 3),
        "blockers_unresolved": len(register["gate_policy"]["blocking_items"]),
        "blocking_ids": BLOCKER_IDS.copy(),
        "evidence": technical,
    }
