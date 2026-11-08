"""V19 independent reconciliation using SQLite and integral time/money units.

Architecture V4 p.42: Reconcile aggregates and operational metrics.
Required proof: Independent computation results.

This intentionally does not import V17 calculation or V16 transformation
functions. It reads validated *fabricated* fixture records and independently
aggregates signed integer seconds/cents using a temporary SQLite database.
Operational metrics requiring actual plant uptime denominators are excluded.
No persistent store, live customer record, CMMS or industrial action.
"""

from __future__ import annotations

import copy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT / "fixtures" / "reconciliation_v19.json"
SOURCE_PATH = PROJECT / "fixtures" / "cases.json"
EXPECTED_PATH = PROJECT / "fixtures" / "expected_outputs_v17.json"
SOURCE_ID = "SYN-RI-V5-20261107-A"
REFERENCE_STATE = "AUTHORED_SYNTHETIC_EXPECTATIONS_NOT_DOMAIN_VALIDATED"
POLICY_STATE = "INDEPENDENT_SYNTHETIC_ARITHMETIC_NOT_CUSTOMER_APPROVED"
METRICS = (
    "case_count", "asset_count", "total_downtime_hours",
    "total_repair_cost_usd", "median_case_downtime_hours",
    "missing_evidence_case_count", "repeat_asset_event_count",
)
ASSET_FIELDS = (
    "asset_id", "case_count", "total_downtime_hours",
    "total_repair_cost_usd", "missing_evidence_case_count",
)
HISTORY_FIELDS = (
    "case_id", "asset_id", "prior_asset_case_count",
    "asset_occurrence_index", "has_example_evidence_refs",
)
ASSET_SOURCE_FIELDS = {"asset_id", "asset_class", "cohort", "synthetic"}
CASE_SOURCE_FIELDS = {
    "case_id", "asset_id", "work_order_ref", "occurred_at_utc",
    "failure_code", "downtime_hours", "repair_cost_usd",
    "evidence_refs", "synthetic", "review_state",
}
ADVERSE_METHODS = {
    "DIFF-DOWNTIME": ("increase_duration", "summary_mismatch"),
    "DIFF-COST": ("increase_cost", "summary_mismatch"),
    "DIFF-EVIDENCE": ("remove_evidence", "summary_mismatch"),
    "DIFF-ASSIGNMENT": ("reassign_asset", "asset_mismatch"),
    "DIFF-HISTORY": ("swap_asset_event_time", "case_history_mismatch"),
    "DIFF-OFFSETTING-COST": ("offset_cost_across_assets", "asset_mismatch"),
    "DIFF-GOLDEN-SUMMARY": ("change_expected_total", "summary_mismatch"),
    "DIFF-GOLDEN-ASSET": ("change_expected_asset", "asset_mismatch"),
    "DIFF-GOLDEN-HISTORY": ("change_expected_history", "case_history_mismatch"),
    "INVALID-MISSING-CASE": ("remove_case", "case_inventory_invalid"),
    "INVALID-DUPLICATE-CASE": ("duplicate_case", "duplicate_case_identifier"),
    "INVALID-UNKNOWN-ASSET": ("unknown_asset", "unknown_asset_reference"),
    "INVALID-FRACTION-CENT": ("fractional_cent", "invalid_money_precision"),
    "INVALID-FRACTION-SECOND": ("fractional_second", "invalid_duration_precision"),
    "INVALID-FALSE-CUSTOMER-ORIGIN": ("customer_origin", "unauthorized_source_origin"),
    "INVALID-ROW-FIELD": ("undeclared_source_field", "invalid_row_fields"),
}


class ReconciliationRejected(ValueError):
    """Reject with fixed non-sensitive diagnostic only."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise ReconciliationRejected(code)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReconciliationRejected("synthetic_fixture_unavailable") from None
    require(type(value) is dict, "synthetic_fixture_not_object")
    return value


def policy() -> dict[str, Any]:
    return read_json(POLICY_PATH)


def source() -> dict[str, Any]:
    return read_json(SOURCE_PATH)


def expected() -> dict[str, Any]:
    return read_json(EXPECTED_PATH)


def validate_policy(config: dict[str, Any]) -> None:
    require(type(config) is dict and config.get("schema_version") == "1.0.0",
            "reconciliation_policy_version")
    require(config.get("increment") == "V19" and
            config.get("objective") == "Reconcile aggregates and operational metrics" and
            config.get("required_proof") == "Independent computation results",
            "reconciliation_policy_objective")
    require(config.get("state") == POLICY_STATE,
            "reconciliation_policy_not_unsigned")
    require(config.get("source_fixture_set_id") == SOURCE_ID and
            config.get("source_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5" and
            config.get("source_file") == "fixtures/cases.json" and
            config.get("prior_expected_reference") ==
            "fixtures/expected_outputs_v17.json",
            "source_or_reference_drift")
    require(config.get("compute_method") ==
            "independent_sqlite_in_memory_integer_seconds_and_usd_cents" and
            config.get("no_v17_calculator_dependency") is True,
            "independence_claim_drift")
    require(config.get("source_records_expected") == 12 and
            config.get("assets_expected") == 6 and
            config.get("rounding_policy") ==
            "exact integer seconds and cents, reject non-integral results",
            "reconciliation_precision_contract")
    require(config.get("ordering_policy") ==
            "UTC timestamp ascending with case ID tie-break; JSON record order irrelevant",
            "reconciliation_order_contract")
    require(config.get("output_groups") ==
            ["summary", "asset_aggregates", "case_history"] and
            config.get("expected_summary_metrics") == 7 and
            config.get("expected_asset_aggregates") == 6 and
            config.get("expected_case_histories") == 12 and
            config.get("expected_reconciliation_values") == 25,
            "reconciliation_inventory_drift")
    require(config.get("allowed_denominators") ==
            ["synthetic case count", "synthetic asset count"],
            "unapproved_operational_denominator")
    require(config.get("excluded_business_metrics") ==
            ["availability_percent", "mtbf_hours", "mttr_hours",
             "oee_percent", "predicted_failure_probability",
             "roi_percent", "saved_cost_usd"], "unapproved_operational_metric")
    approvals = config.get("approval")
    require(type(approvals) is dict, "reconciliation_approvals_missing")
    for key in ("v10_formal_promotion", "v11_dictionary_approved",
                "v12_schema_approved", "v17_reference_domain_approved",
                "v19_reconciliation_approved", "customer_data_authorized",
                "production_approved", "ot_write_authorized"):
        require(approvals.get(key) is False, "reconciliation_false_approval")
    require(approvals.get("named_reviewer") is None and
            approvals.get("approval_signature") is None,
            "reconciliation_fabricated_signature")
    comparisons = config.get("adverse_comparisons")
    require(type(comparisons) is list and len(comparisons) == 16 and
            config.get("expected_adverse_comparisons") == 16,
            "reconciliation_adverse_count_drift")
    seen: set[str] = set()
    for item in comparisons:
        require(type(item) is dict and set(item) ==
                {"id", "kind", "mutation", "expected"} and
                type(item.get("id")) is str and
                item["id"] in ADVERSE_METHODS and item["id"] not in seen,
                "reconciliation_adverse_identity")
        seen.add(item["id"])
        mutation, error = ADVERSE_METHODS[item["id"]]
        require(item["mutation"] == mutation and item["expected"] == error and
                item["kind"] == ("mismatch" if item["id"].startswith("DIFF-")
                                 else "invalid"),
                "reconciliation_expected_error_drift")
    require(seen == set(ADVERSE_METHODS), "reconciliation_missing_scenario")


def _whole_units(value: Any, multiplier: int, code: str) -> int:
    require(type(value) in (int, float) and math.isfinite(value), code)
    try:
        result = Decimal(str(value)) * Decimal(multiplier)
    except (ValueError, InvalidOperation):
        raise ReconciliationRejected(code) from None
    require(result.is_finite() and result == result.to_integral_value(), code)
    require(0 <= result <= Decimal("100000000000"), code)
    return int(result)


def _hours(seconds: int) -> str:
    value = Decimal(seconds) / Decimal(3600)
    require(value * 3600 == Decimal(seconds), "duration_output_precision_loss")
    s = format(value, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _money(cents: int) -> str:
    return format(Decimal(cents) / Decimal(100), ".2f")


def _timestamp(value: Any) -> str:
    require(type(value) is str and
            re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value),
            "invalid_synthetic_timestamp")
    try:
        at = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ReconciliationRejected("invalid_synthetic_timestamp") from None
    require(at.strftime("%Y-%m-%dT%H:%M:%SZ") == value,
            "invalid_synthetic_timestamp")
    return value


def compute_independent(raw: dict[str, Any]) -> dict[str, Any]:
    """SQLite raw-source arithmetic, never calling V17 golden computation."""
    require(type(raw) is dict and raw.get("fixture_set_id") == SOURCE_ID and
            raw.get("synthetic_only") is True and
            raw.get("source_system") == "NONE",
            "unauthorized_source_origin")
    assets = raw.get("assets")
    cases = raw.get("records")
    require(type(assets) is list and len(assets) == 6,
            "asset_inventory_invalid")
    require(type(cases) is list and len(cases) == 12,
            "case_inventory_invalid")
    asset_keys: set[str] = set()
    for asset in assets:
        require(type(asset) is dict and set(asset) == ASSET_SOURCE_FIELDS and
                asset.get("synthetic") is True and
                type(asset.get("asset_id")) is str and
                re.fullmatch(r"SYN-ASSET-\d{3}", asset["asset_id"]),
                "invalid_asset_row")
        require(asset["asset_id"] not in asset_keys, "duplicate_asset_identifier")
        asset_keys.add(asset["asset_id"])
    processed = []
    case_keys: set[str] = set()
    work_keys: set[str] = set()
    for case in cases:
        require(type(case) is dict and set(case) == CASE_SOURCE_FIELDS,
                "invalid_row_fields")
        require(case.get("synthetic") is True and
                case.get("review_state") == "fixture_only",
                "unauthorized_source_origin")
        cid, aid, wid = case["case_id"], case["asset_id"], case["work_order_ref"]
        require(type(cid) is str and
                re.fullmatch(r"SYN-CASE-\d{3}", cid) and
                type(aid) is str and
                re.fullmatch(r"SYN-ASSET-\d{3}", aid) and
                type(wid) is str and re.fullmatch(r"SYN-WO-\d{3}", wid),
                "invalid_row_identity")
        require(cid not in case_keys, "duplicate_case_identifier")
        require(wid not in work_keys, "duplicate_work_order_reference")
        case_keys.add(cid)
        work_keys.add(wid)
        require(aid in asset_keys, "unknown_asset_reference")
        require(type(case["evidence_refs"]) is list and
                all(type(x) is str and re.fullmatch(r"SYN-EV-\d{3}", x)
                    for x in case["evidence_refs"]) and
                len(case["evidence_refs"]) <= 3 and
                len(set(case["evidence_refs"])) == len(case["evidence_refs"]),
                "invalid_reference_field")
        ts = _timestamp(case["occurred_at_utc"])
        seconds = _whole_units(case["downtime_hours"], 3600,
                               "invalid_duration_precision")
        cents = _whole_units(case["repair_cost_usd"], 100,
                             "invalid_money_precision")
        require(seconds <= 864000, "invalid_duration_precision")
        require(cents <= 100000000, "invalid_money_precision")
        processed.append((cid, aid, wid, ts, seconds, cents,
                          len(case["evidence_refs"])))

    # No file-backed database is used. Intermediate numeric units are exact
    # integral seconds and USD cents; independent SQL grouping and correlated
    # history count intentionally differ from the V17 Python grouping method.
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE assets (asset_id TEXT PRIMARY KEY)")
        db.execute(
            "CREATE TABLE cases (case_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL,"
            " work_ref TEXT NOT NULL UNIQUE, occurred_utc TEXT NOT NULL,"
            " duration_seconds INTEGER NOT NULL, cost_cents INTEGER NOT NULL,"
            " evidence_count INTEGER NOT NULL)"
        )
        db.executemany("INSERT INTO assets(asset_id) VALUES (?)",
                       [(name,) for name in sorted(asset_keys)])
        db.executemany("INSERT INTO cases VALUES (?,?,?,?,?,?,?)", processed)
        case_count, total_seconds, total_cents, missing_count = db.execute(
            "SELECT COUNT(*), SUM(duration_seconds), SUM(cost_cents), "
            "SUM(CASE WHEN evidence_count=0 THEN 1 ELSE 0 END) FROM cases"
        ).fetchone()
        sorted_seconds = [x[0] for x in db.execute(
            "SELECT duration_seconds FROM cases ORDER BY duration_seconds, case_id"
        ).fetchall()]
        require(len(sorted_seconds) == 12, "case_inventory_invalid")
        median = Decimal(sorted_seconds[5] + sorted_seconds[6]) / Decimal(2)
        require(median == median.to_integral_value(),
                "median_seconds_fractional")
        per_asset = []
        for aid, n, secs, cents, missing in db.execute(
            "SELECT a.asset_id, COUNT(c.case_id),"
            " COALESCE(SUM(c.duration_seconds),0), COALESCE(SUM(c.cost_cents),0),"
            " COALESCE(SUM(CASE WHEN c.case_id IS NOT NULL AND"
            " c.evidence_count=0 THEN 1 ELSE 0 END),0)"
            " FROM assets a LEFT JOIN cases c ON c.asset_id=a.asset_id"
            " GROUP BY a.asset_id ORDER BY a.asset_id"
        ).fetchall():
            per_asset.append({
                "asset_id": aid, "case_count": n,
                "total_downtime_hours": _hours(secs),
                "total_repair_cost_usd": _money(cents),
                "missing_evidence_case_count": missing,
            })
        history = []
        for cid, aid, prior, count in db.execute(
            "SELECT c.case_id, c.asset_id,"
            " (SELECT COUNT(*) FROM cases p WHERE p.asset_id=c.asset_id"
            " AND (p.occurred_utc<c.occurred_utc OR"
            " (p.occurred_utc=c.occurred_utc AND p.case_id<c.case_id))),"
            " c.evidence_count"
            " FROM cases c ORDER BY c.case_id"
        ).fetchall():
            history.append({
                "case_id": cid, "asset_id": aid,
                "prior_asset_case_count": prior,
                "asset_occurrence_index": prior+1,
                "has_example_evidence_refs": count > 0,
            })
    summary = {
        "case_count": case_count, "asset_count": len(asset_keys),
        "total_downtime_hours": _hours(total_seconds),
        "total_repair_cost_usd": _money(total_cents),
        "median_case_downtime_hours": _hours(int(median)),
        "missing_evidence_case_count": missing_count,
        "repeat_asset_event_count": sum(1 for h in history
                                        if h["prior_asset_case_count"] > 0),
    }
    require(len(per_asset) == 6 and len(history) == 12 and
            sum(a["case_count"] for a in per_asset) == case_count and
            sum(a["missing_evidence_case_count"] for a in per_asset) == missing_count and
            sum(int(Decimal(a["total_downtime_hours"])*3600) for a in per_asset)
            == total_seconds and
            sum(int(Decimal(a["total_repair_cost_usd"])*100) for a in per_asset)
            == total_cents, "internal_sqlite_reconciliation_mismatch")
    return {"summary": summary, "asset_aggregates": per_asset,
            "case_history": history}


def compare(actual: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Exact compare to separate authored V17 expected-output JSON fixture."""
    require(type(reference) is dict and
            reference.get("increment") == "V17" and
            reference.get("reference_status") == REFERENCE_STATE and
            reference.get("fixture_set_id") == SOURCE_ID,
            "reference_status_or_source_invalid")
    approvals = reference.get("approval")
    require(type(approvals) is dict and
            approvals.get("independent_domain_ground_truth") is False and
            approvals.get("human_reference_approval") is False,
            "unapproved_reference_misrepresented")
    expected = {
        "summary": reference["expected_summary"],
        "asset_aggregates": reference["expected_asset_aggregates"],
        "case_history": reference["expected_case_history"],
    }
    require(type(actual) is dict and set(actual) == set(expected),
            "independent_result_shape_invalid")
    require(set(actual["summary"]) == set(METRICS) and
            len(actual["asset_aggregates"]) == 6 and
            len(actual["case_history"]) == 12,
            "independent_result_inventory_drift")
    require(actual["summary"] == expected["summary"], "summary_mismatch")
    require(actual["asset_aggregates"] == expected["asset_aggregates"],
            "asset_mismatch")
    require(actual["case_history"] == expected["case_history"],
            "case_history_mismatch")
    return {
        "summary_metrics_compared": 7,
        "asset_aggregates_compared": 6,
        "case_histories_compared": 12,
        "reconciled_output_units": 25,
        "discrepancies": 0,
        "code_paths_independent": True,
        "customer_data_independent": False,
        "customer_domain_validated": False,
        "result": "EXACT_MATCH_TO_AUTHORED_SYNTHETIC_REFERENCE",
    }


def _apply_mutation(name: str, source_doc: dict[str, Any],
                    expected_doc: dict[str, Any]) -> None:
    """Fixed synthetic error scenarios only; no user-provided code or paths."""
    rows = source_doc["records"]
    if name == "increase_duration":
        rows[0]["downtime_hours"] = 3.5
    elif name == "increase_cost":
        rows[0]["repair_cost_usd"] = 870
    elif name == "remove_evidence":
        rows[0]["evidence_refs"] = []
    elif name == "reassign_asset":
        rows[0]["asset_id"] = "SYN-ASSET-002"
    elif name == "swap_asset_event_time":
        rows[6]["occurred_at_utc"] = "2026-01-01T00:00:00Z"
    elif name == "offset_cost_across_assets":
        rows[0]["repair_cost_usd"] = 870
        rows[1]["repair_cost_usd"] = 420
    elif name == "change_expected_total":
        expected_doc["expected_summary"]["total_repair_cost_usd"] = "12736.00"
    elif name == "change_expected_asset":
        expected_doc["expected_asset_aggregates"][0]["total_repair_cost_usd"] = "1821.00"
    elif name == "change_expected_history":
        expected_doc["expected_case_history"][0]["asset_occurrence_index"] = 99
    elif name == "remove_case":
        rows.pop()
    elif name == "duplicate_case":
        rows[1] = copy.deepcopy(rows[0])
    elif name == "unknown_asset":
        rows[0]["asset_id"] = "SYN-ASSET-999"
    elif name == "fractional_cent":
        rows[0]["repair_cost_usd"] = 860.001
    elif name == "fractional_second":
        rows[0]["downtime_hours"] = 1.0001
    elif name == "customer_origin":
        source_doc["source_system"] = "REAL_CMMS"
    elif name == "undeclared_source_field":
        rows[0]["employee_email"] = "FAKE@example.invalid"
    else:
        raise ReconciliationRejected("unknown_mutation")


def exercise_scenarios(config: dict[str, Any],
                       baseline: dict[str, Any],
                       reference: dict[str, Any]) -> dict[str, Any]:
    validate_policy(config)
    original = json.dumps(baseline, sort_keys=True, separators=(",", ":"))
    cases = []
    for item in config["adverse_comparisons"]:
        altered = copy.deepcopy(baseline)
        authored = copy.deepcopy(reference)
        _apply_mutation(item["mutation"], altered, authored)
        try:
            compare(compute_independent(altered), authored)
        except ReconciliationRejected as err:
            require(str(err) == item["expected"],
                    "adverse_reconciliation_error_code_drift")
        else:
            raise ReconciliationRejected("adverse_discrepancy_not_detected")
        cases.append({"id": item["id"], "expected": item["expected"],
                      "result": "DETECTED_AS_EXPECTED"})
    require(json.dumps(baseline, sort_keys=True, separators=(",", ":")) == original,
            "original_synthetic_source_changed")
    return {"scenarios": len(cases), "detected": len(cases),
            "case_results": cases, "original_source_unchanged": True}
