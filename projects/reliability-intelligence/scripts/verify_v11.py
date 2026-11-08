"""V11 data-correctness exploration: validate a DRAFT synthetic source/field dictionary.

Checks type, meaning, units, candidate stewardship, exact fixture coverage,
and approved-vs-unapproved boundaries. This does NOT produce a signed dictionary
or authorize the blocked V10 -> Phase 02 promotion.

No customer records, external systems, I/O writes to fixtures or industrial
controls. The only output is an ignored local V11 technical evidence JSON.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import verify_v10

PROJECT = Path(__file__).resolve().parents[1]
DICTIONARY_PATH = PROJECT / "docs" / "data" / "SOURCE_FIELD_DICTIONARY_V11.json"
DECISION_PATH = PROJECT / "docs" / "releases" / "V10_DECISION.json"
EVIDENCE = PROJECT / "evidence" / "V11"
REPORT = EVIDENCE / "verification.json"

# Known names are pinned against accidental omission, renaming or expansion.
EXPECTED_FIELDS = {
    "asset_records": {
        "asset_id", "asset_class", "cohort", "synthetic",
    },
    "case_records": {
        "case_id", "asset_id", "work_order_ref", "occurred_at_utc",
        "failure_code", "downtime_hours", "repair_cost_usd",
        "evidence_refs", "synthetic", "review_state",
    },
    "scripted_review_entries": {
        "case_id", "reviewer_id", "disposition", "reason_code",
    },
    "seeded_reference_labels": {
        "case_id", "expected_review_label", "synthetic",
    },
}
SOURCE_BINDINGS = {
    "asset_records": ("fixtures/cases.json", "assets", 6),
    "case_records": ("fixtures/cases.json", "records", 12),
    "scripted_review_entries": ("fixtures/demo_review_script.json", "entries", 4),
    "seeded_reference_labels": ("fixtures/reference_labels.json", "records", 12),
}
EXPECTED_TYPE_POLICY = {
    "asset_records": {"asset_id": "string", "asset_class": "string",
                      "cohort": "string", "synthetic": "boolean"},
    "case_records": {"case_id": "string", "asset_id": "string",
                     "work_order_ref": "string", "occurred_at_utc": "utc_timestamp",
                     "failure_code": "string", "downtime_hours": "number",
                     "repair_cost_usd": "number", "evidence_refs": "array[string]",
                     "synthetic": "boolean", "review_state": "string"},
    "scripted_review_entries": {"case_id": "string", "reviewer_id": "string",
                                "disposition": "string", "reason_code": "string"},
    "seeded_reference_labels": {"case_id": "string",
                                "expected_review_label": "string", "synthetic": "boolean"},
}
EXPECTED_UNIT_POLICY = {
    ("case_records", "occurred_at_utc"): "UTC",
    ("case_records", "downtime_hours"): "hours",
    ("case_records", "repair_cost_usd"): "USD",
}
EXPECTED_KEY_PATTERN_POLICY = {
    ("asset_records", "asset_id"): "^SYN-ASSET-[0-9]{3}$",
    ("case_records", "case_id"): "^SYN-CASE-[0-9]{3}$",
    ("case_records", "asset_id"): "^SYN-ASSET-[0-9]{3}$",
    ("case_records", "work_order_ref"): "^SYN-WO-[0-9]{3}$",
    ("scripted_review_entries", "case_id"): "^SYN-CASE-[0-9]{3}$",
    ("scripted_review_entries", "reviewer_id"): "^SYN-REVIEWER-[0-9]{3}$",
    ("seeded_reference_labels", "case_id"): "^SYN-CASE-[0-9]{3}$",
}
EXPECTED_ITEM_PATTERN = "^SYN-EV-[0-9]{3}$"
EXPECTED_FOREIGN_KEYS = {
    ("case_records", "asset_id"): "asset_records.asset_id",
    ("scripted_review_entries", "case_id"): "case_records.case_id",
    ("seeded_reference_labels", "case_id"): "case_records.case_id",
}
EXPECTED_ENUMS = {
    ("asset_records", "asset_class"): {
        "bearing_drive", "belt_conveyor", "transfer_pump", "sensor_module",
        "electric_motor", "control_valve",
    },
    ("asset_records", "cohort"): {
        "Assembly Test Line", "Utility Test Zone", "Mock Workshop",
    },
    ("case_records", "failure_code"): {
        "bearing_wear", "belt_slip", "seal_leak",
        "sensor_fault", "motor_trip", "valve_stick",
    },
    ("case_records", "review_state"): {"fixture_only"},
    ("scripted_review_entries", "disposition"): {
        "acknowledge", "investigate_history", "request_evidence", "defer",
    },
    ("scripted_review_entries", "reason_code"): {
        "routine_synthetic_review", "repeat_history_flag",
        "missing_evidence_reference", "further_demo_review",
    },
    ("seeded_reference_labels", "expected_review_label"): {
        "single_event", "repeat_history_candidate", "missing_evidence",
    },
    ("asset_records", "synthetic"): {True},
    ("case_records", "synthetic"): {True},
    ("seeded_reference_labels", "synthetic"): {True},
}
DATASET_EXPOSURES = {
    "asset_records": "developer_and_synthetic_ui_only",
    "case_records": "local_read_only_demo_api",
    "scripted_review_entries": "internal_fixture_script_not_true_human_review",
    "seeded_reference_labels": "internal_tests_never_api_or_ui",
}
LOGICAL_TYPES = {"string", "number", "boolean", "utc_timestamp", "array[string]"}
UNITS = {"none", "UTC", "hours", "USD"}


class FieldDictionaryError(ValueError):
    """A machine-checkable source/field dictionary invariant failed."""


def require(cond: Any, code: str) -> None:
    if not cond:
        raise FieldDictionaryError(code)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise FieldDictionaryError("json_file_unavailable_or_invalid") from None
    require(type(value) is dict, "json_root_not_object")
    return value


def validate_metadata(dictionary: dict[str, Any]) -> None:
    require(dictionary.get("schema_version") == "1.0.0", "dictionary_schema_version")
    require(dictionary.get("increment") == "V11", "dictionary_increment")
    require(dictionary.get("objective") == "Declare data types, meaning, and ownership",
            "dictionary_objective")
    require(dictionary.get("required_proof") == "Approved source/field dictionary",
            "dictionary_proof")
    require(dictionary.get("dictionary_status") == "DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED",
            "unsigned_dictionary_status")
    for key in (
        "formal_phase_02_approval", "customer_source_authorized",
        "production_field_contract_approved", "product_owner_approved",
        "independent_domain_steward_approved", "field_owner_assignments_complete",
        "personnel_data_permitted", "ot_or_cmms_writes_permitted",
    ):
        require(dictionary.get(key) is False, "false_approval_" + key)
    require(dictionary.get("approved_at_utc") is None, "false_approval_date")
    require(dictionary.get("systems_of_record") == [], "unverified_source_system")
    approval = dictionary.get("approval_record")
    require(type(approval) is dict, "missing_approval_record")
    require(approval.get("approval_status") == "PENDING", "approval_not_pending")
    for key in ("named_product_owner", "named_customer_data_owner",
                "named_domain_reviewer", "approval_date_utc"):
        require(approval.get(key) is None, "invented_approval_" + key)
    require(approval.get("signatures") == [], "invented_signatures")
    source = dictionary.get("source_snapshot")
    require(type(source) is dict, "missing_source_snapshot")
    require(source.get("commit") == "704123eca45628bf504594af39a66036cc0451c5",
            "unverified_source_snapshot")
    require(source.get("fixture_set_id") == "SYN-RI-V5-20261107-A", "fixture_set_drift")
    require(source.get("v10_decision") == "DRAFT_UNAPPROVED_RECOMMENDS_BLOCKED",
            "v10_decision_inaccurate")
    definitions = dictionary.get("definitions_and_constraints")
    require(type(definitions) is dict, "definitions_missing")
    require(set(definitions.get("logical_types", [])) == LOGICAL_TYPES, "logical_type_policy")
    require(set(definitions.get("units", [])) == UNITS, "unit_policy")


def validate_dictionary(dictionary: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Validate exact dataset/field inventory and semantics of drafted metadata."""
    require(type(dictionary) is dict, "dictionary_not_object")
    validate_metadata(dictionary)
    groups = dictionary.get("datasets")
    require(type(groups) is list and len(groups) == len(EXPECTED_FIELDS),
            "dataset_inventory_drift")
    seen: dict[str, dict[str, dict[str, Any]]] = {}
    for group in groups:
        require(type(group) is dict, "dataset_not_object")
        group_id = group.get("id")
        require(type(group_id) is str and group_id in EXPECTED_FIELDS and group_id not in seen,
                "dataset_id_invalid_or_duplicate")
        expected_path, expected_record_path, count = SOURCE_BINDINGS[group_id]
        require(group.get("source_file") == expected_path and
                group.get("record_path") == expected_record_path and
                group.get("expected_row_count") == count, "source_binding_drift")
        require(group.get("customer_system_of_record") is None and
                group.get("assigned_dataset_owner") is None and
                group.get("external_data_source") is False, "invented_dataset_authority")
        require(group.get("exposure") == DATASET_EXPOSURES[group_id],
                "source_visibility_drift")
        require(type(group.get("proposed_dataset_owner")) is str and
                len(group["proposed_dataset_owner"]) >= 5, "dataset_owner_role_missing")
        require(type(group.get("semantic_entity")) is str and
                len(group["semantic_entity"]) >= 15, "dataset_meaning_missing")
        fields = group.get("fields")
        require(type(fields) is list and len(fields) == len(EXPECTED_FIELDS[group_id]),
                "field_count_drift")
        indexes: dict[str, dict[str, Any]] = {}
        for field in fields:
            require(type(field) is dict, "field_not_object")
            name = field.get("name")
            require(type(name) is str and name in EXPECTED_FIELDS[group_id] and
                    name not in indexes, "field_id_invalid_or_duplicate")
            logical_type = field.get("logical_type")
            require(logical_type == EXPECTED_TYPE_POLICY[group_id][name],
                    "field_logical_type_mismatch")
            expected_unit = EXPECTED_UNIT_POLICY.get((group_id, name), "none")
            require(field.get("unit") == expected_unit, "field_unit_mismatch")
            require(field.get("nullable") is False, "unexpected_nullable_field")
            require(type(field.get("meaning")) is str and
                    len(field["meaning"]) >= 35, "field_meaning_missing")
            require(field.get("source_authority") ==
                    "invented_repository_fixture_not_customer_system",
                    "field_source_authority_false")
            require(field.get("data_classification") == "fabricated_non_personal",
                    "field_classification_drift")
            require(type(field.get("proposed_steward_role")) is str and
                    len(field["proposed_steward_role"]) >= 5, "proposed_steward_missing")
            require(field.get("assigned_steward") is None, "assigned_steward_invented")
            expected_pattern = EXPECTED_KEY_PATTERN_POLICY.get((group_id, name))
            require(field.get("pattern") == expected_pattern, "identifier_pattern_drift")
            expected_fk = EXPECTED_FOREIGN_KEYS.get((group_id, name))
            require(field.get("foreign_key") == expected_fk, "reference_relation_drift")
            expected_enum = EXPECTED_ENUMS.get((group_id, name))
            present_enum = field.get("allowed_values")
            if expected_enum is None:
                require(present_enum is None, "unsupported_field_enum")
            else:
                require(type(present_enum) is list and
                        {(type(x).__name__, str(x)) for x in present_enum} ==
                        {(type(x).__name__, str(x)) for x in expected_enum},
                        "field_allowed_values_drift")
            if logical_type == "array[string]":
                require(field.get("item_pattern") == EXPECTED_ITEM_PATTERN and
                        field.get("max_items") == 3, "array_reference_policy_drift")
            if logical_type == "utc_timestamp":
                require(field.get("timestamp_format") == "YYYY-MM-DDTHH:MM:SSZ",
                        "timestamp_semantics_drift")
            if (group_id, name) in (("case_records", "downtime_hours"),
                                    ("case_records", "repair_cost_usd")):
                upper = 240 if name == "downtime_hours" else 1000000
                require(type(field.get("min_value")) in (int, float) and
                        field["min_value"] == 0 and
                        type(field.get("max_value")) in (int, float) and
                        field["max_value"] == upper, "numeric_bounds_drift")
                require(type(field.get("precision_policy")) is str and
                        len(field["precision_policy"]) >= 25, "numeric_precision_gap")
            indexes[name] = field
        require(set(indexes) == EXPECTED_FIELDS[group_id], "incomplete_source_fields")
        seen[group_id] = indexes
    require(set(seen) == set(EXPECTED_FIELDS), "incomplete_dataset_inventory")
    return seen


def _matches(value: Any, field: dict[str, Any]) -> bool:
    field_type = field["logical_type"]
    if value is None:
        return field["nullable"]
    if field_type == "string":
        ok = type(value) is str
    elif field_type == "boolean":
        ok = type(value) is bool
    elif field_type == "number":
        ok = type(value) in (int, float) and math.isfinite(value)
    elif field_type == "utc_timestamp":
        if type(value) is not str:
            return False
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return False
        ok = parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value
    elif field_type == "array[string]":
        ok = type(value) is list and len(value) <= field["max_items"] and len(value) <= 3
        if ok:
            ok = all(type(x) is str and re.fullmatch(field["item_pattern"], x) for x in value)
            ok = bool(ok and len(value) == len(set(value)))
    else:
        return False
    if not ok:
        return False
    if "pattern" in field and re.fullmatch(field["pattern"], value) is None:
        return False
    if "allowed_values" in field:
        if not any(type(value) is type(x) and value == x for x in field["allowed_values"]):
            return False
    if field_type == "number" and ("min_value" in field or "max_value" in field):
        return field["min_value"] <= value <= field["max_value"]
    return True


def validate_rows(indexes: dict[str, dict[str, dict[str, Any]]],
                  sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Full exact-field, type and foreign-key coverage of pinned synthetic rows."""
    need = require
    if set(sources) != {v[0] for v in SOURCE_BINDINGS.values()}:
        raise FieldDictionaryError("unexpected_source_file_inventory")
    observations: dict[str, list[dict[str, Any]]] = {}
    for group_id, (file, record_path, expected_count) in SOURCE_BINDINGS.items():
        doc = sources[file]
        need(type(doc) is dict and doc.get("fixture_set_id") ==
             "SYN-RI-V5-20261107-A", "source_fixture_set_mismatch")
        rows = doc.get(record_path)
        need(type(rows) is list and len(rows) == expected_count, "source_record_count_drift")
        fields = indexes[group_id]
        for row in rows:
            need(type(row) is dict and set(row) == set(fields), "source_field_coverage_gap")
            for name, field in fields.items():
                need(_matches(row[name], field), "source_type_or_constraint_violation")
        observations[group_id] = rows

    assets = {r["asset_id"] for r in observations["asset_records"]}
    cases = {r["case_id"] for r in observations["case_records"]}
    work_orders = [r["work_order_ref"] for r in observations["case_records"]]
    need(len(assets) == 6 and len(cases) == 12 and len(set(work_orders)) == 12,
         "source_unique_key_violation")
    need(all(r["asset_id"] in assets for r in observations["case_records"]),
         "unknown_asset_reference")
    for group_id in ("scripted_review_entries", "seeded_reference_labels"):
        rows = observations[group_id]
        ids = [r["case_id"] for r in rows]
        need(len(ids) == len(set(ids)) and set(ids).issubset(cases),
             "review_reference_integrity_violation")
    need({r["case_id"] for r in observations["seeded_reference_labels"]} == cases,
         "seeded_label_case_coverage_gap")
    return {
        "dataset_count": len(observations),
        "field_count": sum(len(x) for x in indexes.values()),
        "record_counts": {x: len(rows) for x, rows in observations.items()},
        "all_rows_match_declared_types": True,
        "all_source_fields_documented": True,
        "foreign_keys_valid": True,
        "real_customer_rows_used": False,
    }


def load_sources(root: Path = PROJECT) -> dict[str, dict[str, Any]]:
    return {path: read_json(root / path) for path in sorted({x[0] for x in SOURCE_BINDINGS.values()})}


def main() -> int:
    # V10 frozen reference is independently verified before V11 field checks.
    frozen = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = read_json(DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
            "unauthorized_formal_phase_02_promotion")
    dictionary = read_json(DICTIONARY_PATH)
    index = validate_dictionary(dictionary)
    observation = validate_rows(index, load_sources())
    result = {
        "increment": "V11",
        "result": "technical_dictionary_verified_approval_pending",
        "dictionary_status": dictionary["dictionary_status"],
        "formal_phase_02_approval": False,
        "owner_approval_obtained": False,
        "customer_data_authorized": False,
        "fixture_set_id": dictionary["source_snapshot"]["fixture_set_id"],
        "unchanged_v9_frozen_file_count": frozen["frozen_files_verified"],
        **observation,
        "next_required_proof": "Signed and approved source/field dictionary by accountable data owners",
        "git_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "note": "Technical synthetic type/semantics checks do not approve real-world source meanings, data rights or phase progression.",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V11_FIELD_DICTIONARY: " + json.dumps({
        "status": result["result"],
        "datasets": result["dataset_count"],
        "fields": result["field_count"],
        "rows": result["record_counts"],
        "source_snapshot_unchanged": True,
        "approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FieldDictionaryError, verify_v10.DecisionEvidenceError,
            ValueError, OSError, TypeError, KeyError):
        print("V11_FIELD_DICTIONARY_FAILED: validation_or_authority_invariant", file=sys.stderr)
        raise SystemExit(1) from None
