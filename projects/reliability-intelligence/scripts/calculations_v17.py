"""V17 golden calculations over V16 validated fabricated data.

Mavenu AI SaaS architecture V4 page 42: Define golden/reference
calculations. Proof: Expected-output fixtures.

Arithmetic here is *not* a prediction, ROI calculation, customer ground
truth, or production reliability metric. No source files or V9 runtime are
mutated; all money/duration calculations use exact Decimal arithmetic.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import lineage_v16

PROJECT = Path(__file__).resolve().parents[1]
EXPECTED_PATH = PROJECT / "fixtures" / "expected_outputs_v17.json"
EXPECTED_COUNTS = (12, 6)
EXPECTED_METRICS = (
    "case_count", "asset_count", "total_downtime_hours",
    "total_repair_cost_usd", "median_case_downtime_hours",
    "missing_evidence_case_count", "repeat_asset_event_count",
)
EXPECTED_ASSET_FIELDS = (
    "asset_id", "case_count", "total_downtime_hours",
    "total_repair_cost_usd", "missing_evidence_case_count",
)
EXPECTED_CASE_FIELDS = (
    "case_id", "asset_id", "prior_asset_case_count",
    "asset_occurrence_index", "has_example_evidence_refs",
)
REFERENCE_STATUS = "AUTHORED_SYNTHETIC_EXPECTATIONS_NOT_DOMAIN_VALIDATED"


class GoldenCalculationRejected(ValueError):
    """Fixed-code rejection; do not include source/cost values in logs."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise GoldenCalculationRejected(code)


def as_decimal(value: Any) -> Decimal:
    require(type(value) is str, "noncanonical_decimal_input")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise GoldenCalculationRejected("noncanonical_decimal_input") from None
    require(result.is_finite(), "nonfinite_decimal_input")
    return result


def plain_decimal(value: Decimal) -> str:
    require(isinstance(value, Decimal) and value.is_finite(),
            "nonfinite_decimal_output")
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if result == "-0" else result


def money_cents(value: Decimal) -> str:
    require(Decimal("0") <= value <= Decimal("12000000"),
            "aggregate_money_out_of_bounds")
    require(value == value.quantize(Decimal("0.01")),
            "aggregate_money_precision_loss")
    return format(value, ".2f")


def load_reference(path: Path = EXPECTED_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise GoldenCalculationRejected("expected_output_fixture_unavailable") from None
    require(type(data) is dict, "expected_output_fixture_not_object")
    return data


def validate_reference(reference: dict[str, Any]) -> None:
    """Only synthetic authored reference expectations are permissible."""
    require(type(reference) is dict, "expected_output_fixture_not_object")
    require(reference.get("schema_version") == "1.0.0",
            "reference_schema_version")
    require(reference.get("increment") == "V17",
            "reference_increment_mismatch")
    require(reference.get("objective") ==
            "Define golden/reference calculations", "reference_objective_drift")
    require(reference.get("required_proof") == "Expected-output fixtures",
            "reference_proof_drift")
    require(reference.get("reference_status") == REFERENCE_STATUS,
            "unapproved_reference_misrepresented")
    require(reference.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
            "fixture_set_id_drift")
    require(reference.get("source_baseline_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5",
            "frozen_source_reference_drift")
    require(reference.get("source_files") == ["fixtures/cases.json"],
            "reference_source_file_drift")
    rules = reference.get("calculation_contract")
    require(type(rules) is dict, "missing_calculation_contract")
    require(rules.get("source_view") ==
            "V16 validated synthetic canonical record view (no production integration)",
            "source_view_drift")
    require(rules.get("sort_rule") ==
            "events UTC ascending, case ID tie-breaker", "history_sort_rule_drift")
    require(rules.get("money_rule") ==
            "Decimal USD exact cents (no FX; not actual GL accounting)",
            "money_rule_drift")
    require(rules.get("duration_rule") ==
            "Decimal hours exact (not measured plant downtime)",
            "duration_rule_drift")
    require(rules.get("median_rule") ==
            "median of all 12 fabricated durations using exact Decimal arithmetic",
            "median_rule_drift")
    require(rules.get("output_numeric_encoding") ==
            "all decimal aggregate values are ASCII strings; cost fixed two decimal digits",
            "numeric_format_rule_drift")
    require(rules.get("rounding") == "no rounding; no division-based money allocation",
            "rounding_rule_drift")
    require(rules.get("no_customer_ground_truth") is True,
            "false_reference_ground_truth")
    require(type(rules.get("asset_event_history")) is str and
            "not a reliability prediction" in rules["asset_event_history"],
            "history_overclaim")
    require(type(rules.get("evidence_rule")) is str and
            "NOT authenticated documents" in rules["evidence_rule"],
            "example_evidence_overclaim")

    summary = reference.get("expected_summary")
    assets = reference.get("expected_asset_aggregates")
    histories = reference.get("expected_case_history")
    require(type(summary) is dict and set(summary) == set(EXPECTED_METRICS),
            "expected_summary_shape")
    require(type(assets) is list and len(assets) == 6,
            "expected_asset_inventory")
    require(type(histories) is list and len(histories) == 12,
            "expected_case_history_inventory")
    for item in assets:
        require(type(item) is dict and set(item) == set(EXPECTED_ASSET_FIELDS),
                "expected_asset_shape")
        require(type(item["case_count"]) is int and
                type(item["missing_evidence_case_count"]) is int and
                type(item["asset_id"]) is str and
                item["asset_id"].startswith("SYN-ASSET-"),
                "expected_asset_type_mismatch")
        require(type(item["total_downtime_hours"]) is str and
                type(item["total_repair_cost_usd"]) is str,
                "expected_asset_aggregate_encoding")
        as_decimal(item["total_downtime_hours"])
        as_decimal(item["total_repair_cost_usd"])
    for item in histories:
        require(type(item) is dict and set(item) == set(EXPECTED_CASE_FIELDS),
                "expected_case_shape")
        require(type(item["case_id"]) is str and
                item["case_id"].startswith("SYN-CASE-") and
                type(item["asset_id"]) is str and
                item["asset_id"].startswith("SYN-ASSET-") and
                type(item["prior_asset_case_count"]) is int and
                type(item["asset_occurrence_index"]) is int and
                type(item["has_example_evidence_refs"]) is bool,
                "expected_case_type_mismatch")
    require(type(summary["case_count"]) is int and
            type(summary["asset_count"]) is int and
            type(summary["missing_evidence_case_count"]) is int and
            type(summary["repeat_asset_event_count"]) is int,
            "expected_summary_count_type")
    for field in ("total_downtime_hours", "total_repair_cost_usd",
                  "median_case_downtime_hours"):
        require(type(summary[field]) is str, "expected_summary_numeric_type")
        as_decimal(summary[field])
    require(summary["case_count"] == 12 and summary["asset_count"] == 6,
            "expected_source_inventory_drift")
    require(len({a["asset_id"] for a in assets}) == 6 and
            len({h["case_id"] for h in histories}) == 12,
            "duplicate_expected_id")
    approval = reference.get("approval")
    require(type(approval) is dict, "reference_approval_missing")
    for key in ("customer_data_authorized", "independent_domain_ground_truth",
                "human_reference_approval", "v10_formal_phase_promotion",
                "v11_source_dictionary_approved", "v12_schema_approved",
                "v17_release_approved"):
        require(approval.get(key) is False, "false_reference_approval_" + key)
    require(approval.get("named_owner") is None and
            approval.get("approval_signature") is None, "invented_reference_approver")


def compute(trace: dict[str, Any]) -> dict[str, Any]:
    """Exact reference arithmetic on a validated V16 synthetic view.

    Deterministic event history follows occurrence time and ID only within
    this invented set; no actual asset condition or operating time inferred.
    """
    require(type(trace) is dict, "trace_not_object")
    require(trace.get("increment") == "V16" and
            trace.get("data_classification") == "fabricated_non_personal" and
            trace.get("observed_ingest_event") is False and
            trace.get("customer_data_ingested") is False,
            "non_synthetic_trace_rejected")
    items = trace.get("record_traces")
    require(type(items) is list and len(items) == 34,
            "source_trace_coverage_invalid")
    cases: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for item in items:
        require(type(item) is dict and type(item.get("origin")) is dict,
                "trace_row_invalid")
        origin = item["origin"]
        group = origin.get("source_dataset")
        row = item.get("normalized_record")
        require(type(row) is dict and item.get("normalized_record_sha256") ==
                lineage_v16.sha256_object(row), "normalized_record_checksum_invalid")
        require(item.get("source_record_unchanged") is True and
                origin.get("customer_source_observed") is False,
                "unapproved_lineage_origin")
        if group == "case_records":
            require(item.get("transform_mode") == "v15_canonical_case_view" and
                    type(item.get("transformations")) is list and
                    len(item["transformations"]) == 3,
                    "case_transform_not_verified")
            cases.append(row)
        elif group == "asset_records":
            require(item.get("transformations") == [],
                    "asset_pass_through_modified")
            assets.append(row)
        elif group in ("scripted_review_entries", "seeded_reference_labels"):
            require(item.get("transformations") == [],
                    "reference_pass_through_modified")
        else:
            raise GoldenCalculationRejected("unrecognized_trace_dataset")
    require((len(cases), len(assets)) == EXPECTED_COUNTS,
            "source_case_asset_counts_drift")
    keys = [a["asset_id"] for a in assets]
    require(len(set(keys)) == 6, "duplicate_asset_keys")
    ids = [r["case_id"] for r in cases]
    require(len(set(ids)) == 12, "duplicate_case_keys")
    require(all(r["asset_id"] in keys for r in cases),
            "unknown_case_asset")

    ordered = sorted(cases, key=lambda row: (
        row["occurred_at_utc"], row["case_id"]
    ))
    seen: dict[str, int] = {}
    histories: list[dict[str, Any]] = []
    for row in ordered:
        require(type(row["case_id"]) is str and
                row["case_id"].startswith("SYN-CASE-") and
                row.get("synthetic") is True and
                row.get("review_state") == "fixture_only",
                "non_synthetic_maintenance_case")
        require(type(row.get("evidence_refs")) is list and
                all(type(x) is str and x.startswith("SYN-EV-")
                    for x in row["evidence_refs"]),
                "invalid_example_evidence_refs")
        prior = seen.get(row["asset_id"], 0)
        histories.append({
            "case_id": row["case_id"],
            "asset_id": row["asset_id"],
            "prior_asset_case_count": prior,
            "asset_occurrence_index": prior + 1,
            "has_example_evidence_refs": bool(row["evidence_refs"]),
        })
        seen[row["asset_id"]] = prior + 1
    histories.sort(key=lambda h: h["case_id"])

    downtime = [as_decimal(r["downtime_hours"]) for r in cases]
    costs = [as_decimal(r["repair_cost_usd"]) for r in cases]
    require(all(Decimal(0) <= x <= Decimal(240) for x in downtime),
            "invalid_synthetic_duration")
    require(all(Decimal(0) <= x <= Decimal(1000000) and
                x == x.quantize(Decimal(".01")) for x in costs),
            "invalid_synthetic_cost")
    duration_sorted = sorted(downtime)
    median = (duration_sorted[5] + duration_sorted[6]) / Decimal(2)
    totals = {
        "case_count": len(cases),
        "asset_count": len(assets),
        "total_downtime_hours": plain_decimal(sum(downtime, Decimal(0))),
        "total_repair_cost_usd": money_cents(sum(costs, Decimal(0))),
        "median_case_downtime_hours": plain_decimal(median),
        "missing_evidence_case_count": sum(1 for r in cases if not r["evidence_refs"]),
        "repeat_asset_event_count": sum(1 for h in histories
                                        if h["prior_asset_case_count"] > 0),
    }
    by_asset = []
    for asset in sorted(assets, key=lambda x: x["asset_id"]):
        matched = [r for r in cases if r["asset_id"] == asset["asset_id"]]
        by_asset.append({
            "asset_id": asset["asset_id"],
            "case_count": len(matched),
            "total_downtime_hours": plain_decimal(sum(
                (as_decimal(x["downtime_hours"]) for x in matched), Decimal(0)
            )),
            "total_repair_cost_usd": money_cents(sum(
                (as_decimal(x["repair_cost_usd"]) for x in matched), Decimal(0)
            )),
            "missing_evidence_case_count": sum(
                1 for x in matched if not x["evidence_refs"]
            ),
        })
    require(sum(a["case_count"] for a in by_asset) == len(cases),
            "asset_case_aggregation_mismatch")
    require(sum((as_decimal(a["total_downtime_hours"]) for a in by_asset),
                Decimal(0)) == as_decimal(totals["total_downtime_hours"]),
            "asset_duration_aggregation_mismatch")
    require(sum((as_decimal(a["total_repair_cost_usd"]) for a in by_asset),
                Decimal(0)) == as_decimal(totals["total_repair_cost_usd"]),
            "asset_money_aggregation_mismatch")
    return {
        "summary": totals,
        "asset_aggregates": by_asset,
        "case_history": histories,
    }


def compare(actual: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Exact, independent stored expected fixture comparison (not SME review)."""
    validate_reference(reference)
    require(type(actual) is dict and
            set(actual) == {"summary", "asset_aggregates", "case_history"},
            "computed_output_shape_invalid")
    expected = {
        "summary": reference["expected_summary"],
        "asset_aggregates": reference["expected_asset_aggregates"],
        "case_history": reference["expected_case_history"],
    }
    require(actual["summary"] == expected["summary"],
            "golden_summary_mismatch")
    require(actual["asset_aggregates"] == expected["asset_aggregates"],
            "golden_asset_mismatch")
    require(actual["case_history"] == expected["case_history"],
            "golden_history_mismatch")
    return {
        "expected_output_groups": 3,
        "summary_metrics": len(actual["summary"]),
        "asset_aggregates_checked": len(actual["asset_aggregates"]),
        "case_history_rows_checked": len(actual["case_history"]),
        "total_synthetic_reference_values_verified": (
            len(actual["summary"]) + len(actual["asset_aggregates"]) +
            len(actual["case_history"])
        ),
        "result": "MATCHED_AUTHORED_EXPECTATIONS",
        "independent_domain_validation": False,
    }
