"""V13 negative-case fixtures: reject null, impossible and out-of-range values.

Development architecture V4 p.42: V13 Reject impossible, null, and
out-of-range values. Proof: Negative-case fixtures.

Only deterministic, fabricated rows are mutated in memory. The original V9
runtime, V10 frozen source, V11 draft dictionary and V12 strict contract
remain unchanged. No customer source, human approval, production action or
industrial safety assertion is established by these tests.
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
import verify_v12

PROJECT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT / "fixtures" / "negative_cases_v13.json"
REPORT = PROJECT / "evidence" / "V13" / "negative_case_report.json"
EXPECTED_NEGATIVE_COUNT = 29
EXPECTED_BOUNDARY_COUNT = 7
ALLOWED_CATEGORIES = {"null", "nonfinite", "out_of_range", "impossible"}

# Exact expected case identities. An accidental removal of difficult negative
# tests must fail the build, rather than quietly lowering the test count.
EXPECTED_CASES = {
    "NULL-CASE-ID": "null_required_field",
    "NULL-EVENT-UTC": "null_required_field",
    "NULL-DOWNTIME": "null_required_field",
    "NULL-REPAIR-COST": "null_required_field",
    "NULL-EVIDENCE-LIST": "null_required_field",
    "NULL-ASSET-ORIGIN": "null_required_field",
    "NULL-REVIEW-ACTION": "null_required_field",
    "NULL-SEEDED-LABEL": "null_required_field",
    "RANGE-NEGATIVE-DOWNTIME": "numeric_out_of_range",
    "RANGE-EXCESS-DOWNTIME": "numeric_out_of_range",
    "RANGE-NEGATIVE-COST": "numeric_out_of_range",
    "RANGE-EXCESS-COST": "numeric_out_of_range",
    "NONFINITE-NAN-COST": "nonfinite_numeric",
    "NONFINITE-INF-DOWNTIME": "nonfinite_numeric",
    "NONFINITE-MINUS-INF-COST": "nonfinite_numeric",
    "DATE-NONLEAP-FEB29": "impossible_calendar_timestamp",
    "DATE-FEB30": "impossible_calendar_timestamp",
    "DATE-MONTH13": "impossible_calendar_timestamp",
    "DATE-HOUR25": "impossible_calendar_timestamp",
    "DUPLICATE-ASSET-ID": "duplicate_asset_id",
    "DUPLICATE-CASE-ID": "duplicate_case_id",
    "DUPLICATE-WORK-ORDER": "duplicate_work_order_reference",
    "UNKNOWN-CASE-ASSET": "unknown_asset_reference",
    "UNKNOWN-SCRIPT-CASE": "unknown_case_reference",
    "UNKNOWN-LABEL-CASE": "unknown_case_reference",
    "DUPLICATE-SCRIPT-CASE": "duplicate_review_case",
    "DUPLICATE-LABEL-CASE": "duplicate_label_case",
    "DUPLICATE-EVIDENCE-REF": "duplicate_evidence_reference",
    "TOO-MANY-EVIDENCE-REFS": "evidence_ref_count_out_of_range",
}
EXPECTED_BOUNDARIES = {
    "BOUNDARY-ZERO-DOWNTIME": ("case_records", "downtime_hours", 0),
    "BOUNDARY-MAX-DOWNTIME": ("case_records", "downtime_hours", 240),
    "BOUNDARY-ZERO-COST": ("case_records", "repair_cost_usd", 0),
    "BOUNDARY-MAX-COST": ("case_records", "repair_cost_usd", 1000000),
    "VALID-LEAP-DAY": ("case_records", "occurred_at_utc", "2028-02-29T12:30:00Z"),
    "EMPTY-EVIDENCE-ALLOWED": ("case_records", "evidence_refs", []),
    "THREE-UNIQUE-REFS-ALLOWED": ("case_records", "evidence_refs",
                                ["SYN-EV-001", "SYN-EV-002", "SYN-EV-003"]),
}
EXPECTED_GROUP_ROWS = {
    "asset_records": 6,
    "case_records": 12,
    "scripted_review_entries": 4,
    "seeded_reference_labels": 12,
}


class V13NegativeCaseError(ValueError):
    """A fixed error category, never raw source content."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise V13NegativeCaseError(code)


def read_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(
            V13NegativeCaseError("invalid_nonfinite_json_literal")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V13NegativeCaseError("negative_case_corpus_invalid_json") from None
    require(type(value) is dict, "negative_case_corpus_not_object")
    return value


def _target_parts(item: dict[str, Any], groups: dict[str, dict[str, Any]]) -> tuple[str, int, str]:
    target = item.get("target")
    require(type(target) is dict and set(target) == {"dataset", "row_index", "field"},
            "case_target_shape_invalid")
    dataset, index, field = target["dataset"], target["row_index"], target["field"]
    require(type(dataset) is str and dataset in groups, "case_target_dataset_invalid")
    require(type(index) is int and 0 <= index < EXPECTED_GROUP_ROWS[dataset],
            "case_target_row_index_invalid")
    require(type(field) is str and field in groups[dataset]["required_fields"],
            "case_target_field_invalid")
    return dataset, index, field


def validate_corpus(corpus: dict[str, Any],
                    groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Lock expected scenarios, operations, provenance, and unsigned governance."""
    require(type(corpus) is dict, "corpus_not_object")
    require(corpus.get("schema_version") == "1.0.0", "corpus_schema_version")
    require(corpus.get("increment") == "V13", "corpus_increment")
    require(corpus.get("objective") == "Reject impossible, null, and out-of-range values",
            "corpus_objective")
    require(corpus.get("required_proof") == "Negative-case fixtures", "corpus_proof")
    require(corpus.get("corpus_status") ==
            "SYNTHETIC_NEGATIVE_CONTROLS_NOT_CUSTOMER_APPROVED", "false_corpus_approval")
    require(corpus.get("source_baseline_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5", "baseline_reference_drift")
    require(corpus.get("source_dictionary") ==
            "docs/data/SOURCE_FIELD_DICTIONARY_V11.json", "dictionary_reference_drift")
    require(corpus.get("schema_contract") ==
            "docs/data/SCHEMA_CONTRACT_V12.json", "contract_reference_drift")
    require(corpus.get("source_fixture_set_id") ==
            "SYN-RI-V5-20261107-A", "fixture_reference_drift")
    require(corpus.get("expected_negative_count") == EXPECTED_NEGATIVE_COUNT,
            "negative_count_drift")
    require(corpus.get("expected_boundary_control_count") == EXPECTED_BOUNDARY_COUNT,
            "positive_boundary_count_drift")
    governance = corpus.get("governance")
    require(type(governance) is dict, "missing_corpus_governance")
    for field in ("formal_phase_02_approved", "v11_dictionary_approved",
                  "v12_schema_owner_approved", "customer_data_authorized",
                  "production_approved"):
        require(governance.get(field) is False, "unsupported_approval_" + field)
    require(governance.get("v10_formal_decision") == "PENDING_HUMAN_SIGNOFF" and
            governance.get("v10_promotion_recommendation") == "BLOCKED",
            "v10_decision_claim_inaccurate")
    require(governance.get("reviewer_name") is None and
            governance.get("reviewer_signature") is None, "invented_reviewer_signature")

    negatives = corpus.get("negative_cases")
    positives = corpus.get("valid_boundary_controls")
    require(type(negatives) is list and len(negatives) == EXPECTED_NEGATIVE_COUNT,
            "negative_fixture_inventory_drift")
    require(type(positives) is list and len(positives) == EXPECTED_BOUNDARY_COUNT,
            "positive_fixture_inventory_drift")
    ids: set[str] = set()
    category_counts: dict[str, int] = {}
    for item in negatives:
        require(type(item) is dict and
                set(item) == {"case_id", "category", "target", "mutation", "expected_error"},
                "negative_fixture_shape_invalid")
        name = item["case_id"]
        require(type(name) is str and name in EXPECTED_CASES and name not in ids,
                "unknown_or_duplicate_negative_case")
        ids.add(name)
        require(item["expected_error"] == EXPECTED_CASES[name], "negative_error_drift")
        category = item["category"]
        require(type(category) is str and category in ALLOWED_CATEGORIES,
                "negative_category_invalid")
        category_counts[category] = category_counts.get(category, 0) + 1
        dataset, _, field = _target_parts(item, groups)
        mutation = item["mutation"]
        require(type(mutation) is dict, "mutation_not_object")
        action = mutation.get("action")
        require(action in ("set", "copy", "special"), "mutation_action_not_allowed")
        if action == "copy":
            require(set(mutation) == {"action", "source_row_index"},
                    "copy_mutation_shape_invalid")
            source_index = mutation["source_row_index"]
            require(type(source_index) is int and 0 <= source_index < EXPECTED_GROUP_ROWS[dataset],
                    "copy_source_index_invalid")
        else:
            require(set(mutation) == {"action", "value"}, "set_mutation_shape_invalid")
            if action == "special":
                require(mutation["value"] in
                        ("nan", "positive_infinity", "negative_infinity"),
                        "special_value_not_allowed")
            else:
                # Dict/list values are accepted only for entirely fictional field types;
                # no user-defined Python, executable code or path can be injected.
                require(type(mutation["value"]) in
                        (str, int, float, bool, list, type(None)),
                        "mutation_value_type_invalid")
        if category == "null":
            require(action == "set" and mutation["value"] is None and
                    item["expected_error"] == "null_required_field", "null_fixture_mismatch")
        if category == "nonfinite":
            require(action == "special" and
                    field in ("downtime_hours", "repair_cost_usd") and
                    item["expected_error"] == "nonfinite_numeric",
                    "nonfinite_fixture_mismatch")
    require(ids == set(EXPECTED_CASES), "negative_case_ids_missing")

    observed_boundary_ids: set[str] = set()
    for item in positives:
        require(type(item) is dict and
                set(item) == {"case_id", "target", "value"}, "boundary_shape_invalid")
        name = item["case_id"]
        require(type(name) is str and name in EXPECTED_BOUNDARIES and
                name not in observed_boundary_ids, "boundary_id_invalid_or_duplicate")
        observed_boundary_ids.add(name)
        dataset, _, field = _target_parts(item, groups)
        expected_dataset, expected_field, expected_value = EXPECTED_BOUNDARIES[name]
        require(dataset == expected_dataset and field == expected_field and
                type(item["value"]) is type(expected_value) and
                item["value"] == expected_value, "boundary_value_drift")
    require(observed_boundary_ids == set(EXPECTED_BOUNDARIES), "boundary_inventory_missing")
    require(category_counts == {"null": 8, "out_of_range": 5,
                                "nonfinite": 3, "impossible": 13},
            "negative_case_category_coverage_drift")
    return {"negative_count": len(negatives), "positive_boundary_count": len(positives),
            "category_counts": category_counts}


def validate_semantic_bounds(groups: dict[str, dict[str, Any]],
                             dictionary_index: dict[str, dict[str, dict[str, Any]]],
                             sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Add V13 semantic feasibility checks to the strict V12 contract.

    All range ceilings are V11 *synthetic fixture* parameters, not an approved
    maintenance or financial standard. Valid empty arrays/zero values stay valid.
    """
    for group_id, group in groups.items():
        rows = sources[group["fixture_file"]][group["array_path"]]
        required = group["required_fields"]
        for row in rows:
            for name in required:
                if name in row and row[name] is None:
                    raise V13NegativeCaseError("null_required_field")
                if name not in row:
                    continue  # V12 reports missing_required_field explicitly
                value = row[name]
                field = dictionary_index[group_id][name]
                if field["logical_type"] == "number" and type(value) in (int, float):
                    if not math.isfinite(value):
                        raise V13NegativeCaseError("nonfinite_numeric")
                    if "min_value" in field and not (
                        field["min_value"] <= value <= field["max_value"]
                    ):
                        raise V13NegativeCaseError("numeric_out_of_range")
                if field["logical_type"] == "utc_timestamp" and type(value) is str:
                    try:
                        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        raise V13NegativeCaseError("impossible_calendar_timestamp") from None
                    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
                        raise V13NegativeCaseError("impossible_calendar_timestamp")
                if group_id == "case_records" and name == "evidence_refs" and type(value) is list:
                    if len(value) > field["max_items"]:
                        raise V13NegativeCaseError("evidence_ref_count_out_of_range")
                    if all(type(x) is str for x in value) and len(value) != len(set(value)):
                        raise V13NegativeCaseError("duplicate_evidence_reference")

    # V12 verifies exact field names, non-null types, enums, ID patterns and
    # array element patterns before cross-record referential checks.
    try:
        v12_summary = verify_v12.validate_rows(groups, sources)
    except verify_v12.SchemaContractError as exc:
        raise V13NegativeCaseError(str(exc)) from None

    assets = sources[groups["asset_records"]["fixture_file"]][groups["asset_records"]["array_path"]]
    cases = sources[groups["case_records"]["fixture_file"]][groups["case_records"]["array_path"]]
    reviews = sources[groups["scripted_review_entries"]["fixture_file"]][groups["scripted_review_entries"]["array_path"]]
    labels = sources[groups["seeded_reference_labels"]["fixture_file"]][groups["seeded_reference_labels"]["array_path"]]

    def unique(rows: list[dict[str, Any]], key: str, error: str) -> None:
        values = [row[key] for row in rows]
        require(len(values) == len(set(values)), error)

    unique(assets, "asset_id", "duplicate_asset_id")
    unique(cases, "case_id", "duplicate_case_id")
    unique(cases, "work_order_ref", "duplicate_work_order_reference")
    unique(reviews, "case_id", "duplicate_review_case")
    unique(labels, "case_id", "duplicate_label_case")
    asset_keys = {row["asset_id"] for row in assets}
    case_keys = {row["case_id"] for row in cases}
    require(all(row["asset_id"] in asset_keys for row in cases),
            "unknown_asset_reference")
    require(all(row["case_id"] in case_keys for row in reviews + labels),
            "unknown_case_reference")
    require({row["case_id"] for row in labels} == case_keys,
            "seeded_label_coverage_gap")
    require(sum(len(x) for x in [assets, cases, reviews, labels]) == 34,
            "fixture_record_count_drift")
    return {
        "records_checked": 34,
        "datasets_checked": 4,
        "declared_fields_checked": 21,
        "v12_required_field_checks": v12_summary["required_field_checks"],
        "semantic_checks_passed": True,
        "synthetic_boundaries_only": True,
        "real_customer_values_used": False,
    }


def _mutate(sources: dict[str, dict[str, Any]],
            groups: dict[str, dict[str, Any]], item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changed = copy.deepcopy(sources)
    dataset, index, field = _target_parts(item, groups)
    group = groups[dataset]
    target = changed[group["fixture_file"]][group["array_path"]][index]
    mutation = item["mutation"] if "mutation" in item else {"action": "set", "value": item["value"]}
    action = mutation["action"]
    if action == "copy":
        value = changed[group["fixture_file"]][group["array_path"]][mutation["source_row_index"]][field]
    elif action == "special":
        marker = mutation["value"]
        value = {"nan": math.nan, "positive_infinity": math.inf,
                 "negative_infinity": -math.inf}[marker]
    else:
        value = mutation["value"]
    target[field] = copy.deepcopy(value)
    return changed


def exercise_cases(corpus: dict[str, Any], groups: dict[str, dict[str, Any]],
                   dictionary_index: dict[str, dict[str, dict[str, Any]]],
                   sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Execute every committed invalid fixture and each valid boundary control."""
    negatives = []
    for item in corpus["negative_cases"]:
        altered = _mutate(sources, groups, item)
        try:
            validate_semantic_bounds(groups, dictionary_index, altered)
        except V13NegativeCaseError as error:
            require(str(error) == item["expected_error"],
                    "negative_rejection_code_mismatch")
        else:
            raise V13NegativeCaseError("invalid_negative_fixture_was_accepted")
        negatives.append({
            "case_id": item["case_id"], "category": item["category"],
            "expected_code": item["expected_error"], "result": "REJECTED_AS_EXPECTED",
        })
    boundaries = []
    for item in corpus["valid_boundary_controls"]:
        altered = _mutate(sources, groups, item)
        validate_semantic_bounds(groups, dictionary_index, altered)
        boundaries.append({"case_id": item["case_id"], "result": "ACCEPTED_AS_EXPECTED"})
    require(len(negatives) == EXPECTED_NEGATIVE_COUNT, "negative_run_count_drift")
    require(len(boundaries) == EXPECTED_BOUNDARY_COUNT, "boundary_run_count_drift")
    return {
        "negative_case_count": len(negatives),
        "negative_cases_rejected": len(negatives),
        "negative_cases": negatives,
        "valid_boundary_case_count": len(boundaries),
        "valid_boundary_cases_accepted": len(boundaries),
        "valid_boundary_cases": boundaries,
        "original_fixture_files_modified": False,
        "real_customer_data_used": False,
    }


def main() -> int:
    frozen = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF" and
            decision.get("formal_phase_promotion_authorized") is False,
            "v10_formal_promotion_not_blocked")
    dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    dictionary_index = verify_v11.validate_dictionary(dictionary)
    contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    groups = verify_v12.validate_contract(contract, dictionary)
    sources = verify_v11.load_sources()
    verify_v11.validate_rows(dictionary_index, sources)
    verify_v12.validate_rows(groups, sources)

    corpus = read_corpus()
    inventory = validate_corpus(corpus, groups)
    positive = validate_semantic_bounds(groups, dictionary_index, sources)
    scenario_results = exercise_cases(corpus, groups, dictionary_index, sources)
    record = {
        "increment": "V13",
        "proof": "Negative-case fixtures",
        "result": "synthetic_negative_cases_passed_governance_pending",
        "technical_acceptance_candidate": True,
        "formal_phase_02_promotion_authorized": False,
        "source_fixture_set_id": corpus["source_fixture_set_id"],
        "source_baseline_commit": corpus["source_baseline_commit"],
        "v10_frozen_source_files_verified": frozen["frozen_files_verified"],
        "v11_dictionary_approved": False,
        "v12_schema_owner_approved": False,
        "v13_owner_or_reviewer_approved": False,
        "customer_data_used": False,
        "runtime_changes_to_frozen_v9": False,
        "inventory": inventory,
        "positive_fixture_validation": positive,
        "case_execution": scenario_results,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "No data from Minn-Dak or any customer, real reviewer or actual plant.",
            "Numeric bounds are illustrative V11 synthetic constraints, not real equipment limits.",
            "No proof of operational data quality, financial benefit, domain source authority or production safety.",
            "V10 formal promotion remains blocked pending human decision; V11 dictionary unsigned.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V13_NEGATIVE_CASES: " + json.dumps({
        "result": record["result"],
        "negative_cases_rejected": scenario_results["negative_cases_rejected"],
        "valid_boundaries_accepted": scenario_results["valid_boundary_cases_accepted"],
        "source_rows": positive["records_checked"],
        "frozen_files": frozen["frozen_files_verified"],
        "formally_approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V13NegativeCaseError, verify_v10.DecisionEvidenceError,
            verify_v11.FieldDictionaryError, verify_v12.SchemaContractError,
            ValueError, KeyError, OSError, TypeError):
        print("V13_NEGATIVE_CASES_FAILED: synthetic_or_governance_invariant", file=sys.stderr)
        raise SystemExit(1) from None
