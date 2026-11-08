"""V19 independent computation evidence: synthetic reconciled aggregates.

Runs a second computation path (SQLite + integer seconds/cents) against raw
fabricated fixtures; compares every result with authored V17 expectations.
A matching reference is not customer, finance, OT or industrial ground truth.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import sqlite3
from pathlib import Path
from typing import Any

import reconcile_v19 as rec
import verify_v10
import verify_v11
import verify_v12
import verify_v17
import verify_v18

PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "evidence" / "V19" / "independent_reconciliation_report.json"
DETAILS = PROJECT / "evidence" / "V19" / "independent_computation_results.json"


class V19EvidenceError(ValueError):
    """Fixed fail-closed diagnostic."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V19EvidenceError(code)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def generate() -> dict[str, Any]:
    freeze = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF" and
            decision.get("recommended_promotion_decision") == "BLOCKED",
            "v10_promotion_not_blocked")
    # Replays inherited data-correctness and V17 authored reference evidence.
    adverse = verify_v18.generate()
    previous = verify_v17.generate()
    require(adverse["adverse_results"]["negative_cases"] == 44 and
            previous["verified_output_counts"]["total_synthetic_reference_values_verified"] == 25,
            "inherited_data_evidence_drift")
    config, raw, authored = rec.policy(), rec.source(), rec.expected()
    rec.validate_policy(config)
    source_sha = hashlib.sha256(rec.SOURCE_PATH.read_bytes()).hexdigest()
    original = digest(raw)
    computed = rec.compute_independent(raw)
    matched = rec.compare(computed, authored)
    # Sorting, grouping and case history must not depend on fixture array order.
    reordered = copy.deepcopy(raw)
    reordered["assets"].reverse()
    reordered["records"].reverse()
    reorder = rec.compute_independent(reordered)
    require(reorder == computed, "source_record_order_changed_output")
    scenarios = rec.exercise_scenarios(config, raw, authored)
    require(scenarios["detected"] == 16 and matched["discrepancies"] == 0,
            "reconciliation_comparison_failed")
    require(digest(raw) == original and
            hashlib.sha256(rec.SOURCE_PATH.read_bytes()).hexdigest() == source_sha,
            "source_file_mutated_by_reconciliation")
    # Raw reference has no real-world denominator for availability, MTBF,
    # OEE, true repair cycle time, ROI, or avoided maintenance expense.
    require(not any(m in computed["summary"] for m in
                    config["excluded_business_metrics"]),
            "unapproved_operational_metric_computed")
    return {
        "increment": "V19",
        "objective": "Reconcile aggregates and operational metrics",
        "required_proof": "Independent computation results",
        "result": "independent_synthetic_computation_reconciled_signoff_pending",
        "calculation_method": config["compute_method"],
        "reconciliation": matched,
        "adverse_comparisons": scenarios,
        "computed_output": computed,
        "source_file_sha256": source_sha,
        "source_snapshot_sha256": original,
        "computed_result_sha256": digest(computed),
        "reference_sha256": digest({
            "summary": authored["expected_summary"],
            "asset_aggregates": authored["expected_asset_aggregates"],
            "case_history": authored["expected_case_history"],
        }),
        "independent_path_is_raw_sqlite_not_v17_python": True,
        "same_authored_synthetic_source": True,
        "input_order_invariant": True,
        "v10_frozen_paths_verified": freeze["frozen_files_verified"],
        "v10_formal_promotion_authorized": False,
        "v11_dictionary_approved": False,
        "v12_schema_approved": False,
        "v17_reference_domain_approved": False,
        "v19_reconciliation_approved": False,
        "customer_data_used": False,
        "real_operational_metrics_claimed": False,
        "original_source_unchanged": True,
        "plant_sources_connected": False,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "Independent method is SQLite/integer arithmetic but shares one fictional underlying source with V17.",
            "A matching precomputed fictional reference is not independent customer/data-steward validation.",
            "Downtime and cost sums are illustrative input arithmetic, not actual plant operations or savings.",
            "No operating-hour denominator: availability, MTBF, MTTR, OEE and ROI are deliberately excluded.",
            "V10 promotion and V11/V12 source approvals remain blocked or unsigned.",
        ],
    }


def main() -> int:
    r = generate()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {k: v for k, v in r.items()
              if k not in ("computed_output", "adverse_comparisons")}
    report["adverse_comparison_count"] = r["adverse_comparisons"]["detected"]
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    DETAILS.write_text(json.dumps({
        "increment": "V19",
        "method": r["calculation_method"],
        "result": r["result"],
        "reconciliation": r["reconciliation"],
        "computed_synthetic_results": r["computed_output"],
        "adverse_cases": r["adverse_comparisons"],
        "independent_domain_ground_truth": False,
        "customer_data_used": False,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V19_INDEPENDENT_RECONCILIATION: " + json.dumps({
        "result": r["result"],
        "reconciled": r["reconciliation"]["reconciled_output_units"],
        "adverse_discrepancies_detected": r["adverse_comparisons"]["detected"],
        "synthetic_case_count": r["computed_output"]["summary"]["case_count"],
        "frozen_source_files": r["v10_frozen_paths_verified"],
        "domain_approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V19EvidenceError, rec.ReconciliationRejected,
            verify_v10.DecisionEvidenceError, verify_v11.FieldDictionaryError,
            verify_v12.SchemaContractError, ValueError, KeyError, TypeError,
            OSError, OverflowError, ArithmeticError, sqlite3.Error):
        print("V19_INDEPENDENT_RECONCILIATION_FAILED: synthetic_or_approval_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
