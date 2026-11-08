"""V12 strict synthetic schema validation and reproducible test report.

Architecture V4 p.42: V12 Validate required fields and allowed values;
proof: Schema validation test report.

This script is intentionally outside the frozen V9 production runtime.
Checks run on the pinned V5/V6 fabricated fixtures; it does not approve
the V11 data dictionary or supersede the blocked V10 phase decision.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import verify_v10
import verify_v11

PROJECT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT / "docs" / "data" / "SCHEMA_CONTRACT_V12.json"
DICTIONARY_PATH = verify_v11.DICTIONARY_PATH
DECISION_PATH = verify_v11.DECISION_PATH
EVIDENCE = PROJECT / "evidence" / "V12"
REPORT = EVIDENCE / "schema_validation_report.json"

EXPECTED_SOURCE_COUNT = 34
EXPECTED_FIELD_COUNT = 21
EXPECTED_DATASET_COUNT = 4
EXPECTED_ENUM_FIELD_COUNT = 10
EXPECTED_PATTERN_FIELD_COUNT = 7


class SchemaContractError(ValueError):
    """Fixed-code validation failure; never return source values in logs."""


def require(condition: Any, error_code: str) -> None:
    if not condition:
        raise SchemaContractError(error_code)


def _typed_values(values: list[Any]) -> set[tuple[str, str]]:
    return {(type(x).__name__, json.dumps(x, sort_keys=True)) for x in values}


def validate_contract(contract: dict[str, Any], dictionary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Cross-check compiled V12 contract against V11's unapproved dictionary."""
    require(isinstance(contract, dict), "contract_not_object")
    require(contract.get("schema_version") == "1.0.0", "contract_version")
    require(contract.get("increment") == "V12", "increment_mismatch")
    require(contract.get("objective") == "Validate required fields and allowed values",
            "objective_mismatch")
    require(contract.get("required_proof") == "Schema validation test report", "proof_mismatch")
    require(contract.get("contract_status") == "TECHNICALLY_CHECKABLE_DRAFT_NOT_APPROVED",
            "false_contract_approval")
    require(contract.get("dictionary_reference") ==
            "docs/data/SOURCE_FIELD_DICTIONARY_V11.json", "dictionary_reference_drift")
    require(contract.get("dictionary_increment") == "V11" and
            contract.get("dictionary_approval_status") == "PENDING",
            "unsigned_dictionary_status_drift")
    require(contract.get("source_baseline_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5", "source_baseline_drift")
    require(contract.get("fixture_set_id") == "SYN-RI-V5-20261107-A", "fixture_set_drift")
    require(contract.get("validation_mode") == "STRICT_EXACT_FIELDS_AND_ALLOWED_VALUES",
            "strict_validation_disabled")
    require(contract.get("real_source_systems") == [], "unverified_real_source_system")
    for field in ("customer_data_permitted", "production_approved",
                  "formal_phase_02_approval", "schema_owner_approved",
                  "customer_data_owner_approved"):
        require(contract.get(field) is False, "false_authorization_" + field)
    for field in ("named_approver", "approval_at_utc", "approval_signature"):
        require(contract.get(field) is None, "invented_approval_" + field)
    require(contract.get("record_count_expected") == EXPECTED_SOURCE_COUNT,
            "record_count_baseline_drift")
    require(contract.get("field_occurrence_count") == EXPECTED_FIELD_COUNT,
            "field_count_baseline_drift")
    require(contract.get("enum_field_count") == EXPECTED_ENUM_FIELD_COUNT,
            "enum_field_count_drift")
    require(contract.get("identifier_pattern_count") == EXPECTED_PATTERN_FIELD_COUNT,
            "pattern_field_count_drift")
    require(dictionary.get("dictionary_status") ==
            "DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED", "dictionary_not_unsigned")

    groups = contract.get("groups")
    require(isinstance(groups, list) and len(groups) == EXPECTED_DATASET_COUNT,
            "contract_group_count_drift")
    source_groups = {g["id"]: g for g in dictionary["datasets"]}
    require(set(source_groups) == set(verify_v11.EXPECTED_FIELDS),
            "v11_source_group_mismatch")
    index: dict[str, dict[str, Any]] = {}
    for group in groups:
        require(isinstance(group, dict), "contract_group_not_object")
        group_id = group.get("dataset_id")
        require(isinstance(group_id, str) and
                group_id in source_groups and group_id not in index,
                "duplicate_or_unknown_group")
        source_group = source_groups[group_id]
        fields = {f["name"]: f for f in source_group["fields"]}
        require(group.get("fixture_file") == source_group["source_file"] and
                group.get("array_path") == source_group["record_path"] and
                group.get("expected_row_count") == source_group["expected_row_count"],
                "fixture_binding_drift")
        require(group.get("extra_fields") == "REJECT" and
                group.get("missing_required_fields") == "REJECT" and
                group.get("false_boolean_provenance") == "REJECT",
                "fail_closed_contract_policy_missing")
        require(group.get("customer_source_role") == "NOT_APPROVED",
                "false_customer_authority")
        require(group.get("required_fields") == sorted(fields),
                "required_field_inventory_drift")
        require(group.get("field_types") ==
                {name: value["logical_type"] for name, value in fields.items()},
                "declared_field_type_drift")
        allowed_values = group.get("allowed_values")
        require(isinstance(allowed_values, dict) and
                set(allowed_values) == {k for k, v in fields.items()
                                       if "allowed_values" in v},
                "allowed_value_fields_drift")
        for name, values in allowed_values.items():
            require(type(values) is list and
                    _typed_values(values) == _typed_values(fields[name]["allowed_values"]) and
                    len(values) == len(fields[name]["allowed_values"]),
                    "allowed_values_drift")
        require(group.get("identifier_patterns") ==
                {name: value["pattern"] for name, value in fields.items()
                 if "pattern" in value}, "identifier_patterns_drift")
        require(group.get("element_patterns") ==
                {name: value["item_pattern"] for name, value in fields.items()
                 if "item_pattern" in value}, "element_patterns_drift")
        index[group_id] = group
    require(set(index) == set(source_groups), "incomplete_contract_group_set")
    return index


def _type_check(value: Any, logical_type: str) -> bool:
    """Exact Python types; bool must never masquerade as a numeric 1."""
    if logical_type == "string":
        return type(value) is str
    if logical_type == "boolean":
        return type(value) is bool
    if logical_type == "number":
        return type(value) in (int, float) and math.isfinite(value)
    if logical_type == "array[string]":
        return type(value) is list and all(type(x) is str for x in value)
    if logical_type == "utc_timestamp":
        if type(value) is not str:
            return False
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return False
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value
    return False


def validate_rows(groups: dict[str, dict[str, Any]],
                  sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Verify exact required fields and typed allowed values for every row."""
    require(set(sources) == {x["fixture_file"] for x in groups.values()},
            "fixture_source_inventory_drift")
    checked_required = 0
    checked_types = 0
    checked_enums = 0
    checked_patterns = 0
    row_counts: dict[str, int] = {}
    for group_id, group in sorted(groups.items()):
        source_doc = sources[group["fixture_file"]]
        require(type(source_doc) is dict and
                source_doc.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
                "fixture_identity_invalid")
        rows = source_doc.get(group["array_path"])
        require(type(rows) is list and len(rows) == group["expected_row_count"],
                "fixture_record_count_invalid")
        required = set(group["required_fields"])
        row_counts[group_id] = len(rows)
        for row in rows:
            require(type(row) is dict, "record_not_object")
            require(required.issubset(row), "missing_required_field")
            require(set(row).issubset(required), "undeclared_field")
            for name in group["required_fields"]:
                value = row[name]
                checked_required += 1
                require(_type_check(value, group["field_types"][name]),
                        "wrong_required_field_type")
                checked_types += 1
                if name in group["allowed_values"]:
                    checked_enums += 1
                    choices = group["allowed_values"][name]
                    require(any(type(value) is type(choice) and value == choice
                                for choice in choices), "disallowed_field_value")
                if name in group["identifier_patterns"]:
                    checked_patterns += 1
                    require(type(value) is str and
                            re.fullmatch(group["identifier_patterns"][name], value) is not None,
                            "invalid_identifier_pattern")
                if name in group["element_patterns"]:
                    require(type(value) is list, "invalid_list_type")
                    for element in value:
                        checked_patterns += 1
                        require(re.fullmatch(group["element_patterns"][name], element) is not None,
                                "invalid_element_pattern")
    return {
        "record_counts": row_counts,
        "records_checked": sum(row_counts.values()),
        "dataset_count": len(groups),
        "fields_declared": sum(len(g["required_fields"]) for g in groups.values()),
        "required_field_checks": checked_required,
        "type_checks": checked_types,
        "allowed_value_checks": checked_enums,
        "pattern_checks": checked_patterns,
        "all_required_and_allowed_checks_passed": True,
    }


def negative_case_report(groups: dict[str, dict[str, Any]],
                         sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run real in-memory mutations; do not use genuine customer or PII values."""
    cases: list[tuple[str, str, str, Any, str]] = [
        ("missing_case_failure_code", "case_records", "failure_code", "__DELETE__", "missing_required_field"),
        ("extra_case_field", "case_records", "invented_extra_column", "SYN-ONLY", "undeclared_field"),
        ("disallowed_failure_code", "case_records", "failure_code", "undocumented_failure", "disallowed_field_value"),
        ("boolean_as_numeric", "case_records", "downtime_hours", True, "wrong_required_field_type"),
        ("false_synthetic_provenance", "case_records", "synthetic", False, "disallowed_field_value"),
        ("non_synthetic_case_id", "case_records", "case_id", "CUSTOMER-CASE-001", "invalid_identifier_pattern"),
        ("invalid_work_order_format", "case_records", "work_order_ref", "REAL-WO-101", "invalid_identifier_pattern"),
        ("invalid_evidence_reference", "case_records", "evidence_refs", ["REAL-EVIDENCE"], "invalid_element_pattern"),
        ("disallowed_asset_class", "asset_records", "asset_class", "unknown_plant_type", "disallowed_field_value"),
        ("invalid_asset_id_format", "asset_records", "asset_id", "REAL-ASSET-1", "invalid_identifier_pattern"),
        ("unapproved_reviewer_disposition", "scripted_review_entries", "disposition", "auto_dispatch", "disallowed_field_value"),
        ("unapproved_review_reason", "scripted_review_entries", "reason_code", "plant_approved", "disallowed_field_value"),
        ("unverified_reference_label", "seeded_reference_labels", "expected_review_label", "actual_diagnosis", "disallowed_field_value"),
        ("non_boolean_label_origin", "seeded_reference_labels", "synthetic", 1, "wrong_required_field_type"),
        ("missing_reviewer_id", "scripted_review_entries", "reviewer_id", "__DELETE__", "missing_required_field"),
        ("extra_asset_field", "asset_records", "employee_phone", "SYN-NO-PII", "undeclared_field"),
    ]
    results = []
    for label, group_id, field, injected_value, expected_code in cases:
        mutated = copy.deepcopy(sources)
        group = groups[group_id]
        row = mutated[group["fixture_file"]][group["array_path"]][0]
        if injected_value == "__DELETE__":
            del row[field]
        else:
            row[field] = injected_value
        try:
            validate_rows(groups, mutated)
        except SchemaContractError as exc:
            observed = str(exc)
            require(observed == expected_code, "negative_case_wrong_rejection_" + label)
        else:
            raise SchemaContractError("negative_case_accepted_" + label)
        results.append({"case": label, "result": "REJECTED_AS_EXPECTED", "code": expected_code})
    return {
        "negative_case_count": len(results),
        "negative_cases_passed": len(results),
        "negative_cases": results,
        "fixture_files_modified": False,
        "real_customer_data_used": False,
    }


def main() -> int:
    freeze = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF" and
            decision.get("formal_phase_promotion_authorized") is False,
            "v10_formal_promotion_not_blocked")
    dictionary = verify_v11.read_json(DICTIONARY_PATH)
    verify_v11.validate_dictionary(dictionary)
    fixtures = verify_v11.load_sources()
    verify_v11.validate_rows(verify_v11.validate_dictionary(dictionary), fixtures)
    contract = verify_v11.read_json(CONTRACT_PATH)
    groups = validate_contract(contract, dictionary)
    positive = validate_rows(groups, fixtures)
    negatives = negative_case_report(groups, fixtures)
    require(positive["records_checked"] == EXPECTED_SOURCE_COUNT, "positive_row_count_drift")
    require(positive["fields_declared"] == EXPECTED_FIELD_COUNT, "positive_field_count_drift")
    report = {
        "increment": "V12",
        "proof": "Schema validation test report",
        "result": "synthetic_schema_validated_approval_pending",
        "scope": "Synthetic-only, exploratory Data Correctness V12",
        "source_baseline_commit": contract["source_baseline_commit"],
        "frozen_source_files_verified": freeze["frozen_files_verified"],
        "required_field_contract_status": contract["contract_status"],
        "v10_formal_phase_promotion": "BLOCKED_RECOMMENDATION_PENDING_HUMAN_SIGNOFF",
        "v11_dictionary_approved": False,
        "v12_schema_owner_approved": False,
        "production_or_customer_access": False,
        "positive_checks": positive,
        "negative_checks": negatives,
        "human_approval_completed": False,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "Only artificial fixtures, not real CMMS, ERP, OT or customer records.",
            "Required/allowed fields validated; V13 targeted impossible/null/out-of-range tests pending.",
            "Human source/field dictionary sign-off and V10 phase promotion remain outstanding.",
        ],
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V12_SCHEMA_REPORT: " + json.dumps({
        "status": report["result"],
        "datasets": positive["dataset_count"],
        "records": positive["records_checked"],
        "fields": positive["fields_declared"],
        "required_checks": positive["required_field_checks"],
        "enum_checks": positive["allowed_value_checks"],
        "pattern_checks": positive["pattern_checks"],
        "negative_cases": negatives["negative_cases_passed"],
        "approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SchemaContractError, verify_v10.DecisionEvidenceError,
            verify_v11.FieldDictionaryError, ValueError, KeyError, TypeError, OSError):
        print("V12_SCHEMA_REPORT_FAILED: schema_or_authorization_invariant", file=sys.stderr)
        raise SystemExit(1) from None
