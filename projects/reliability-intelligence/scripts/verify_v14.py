"""V14 repeated-ingest comparison: synthetic idempotency/duplicate evidence.

Proof for controlled development increment: repeated-ingest comparison.
The only persistence is a generated, ignored evidence JSON file; the
test store itself is entirely ephemeral and never touches actual CMMS/OT.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import ingest_v14
import verify_v10
import verify_v11
import verify_v12
import verify_v13

PROJECT = Path(__file__).resolve().parents[1]
PLAN_PATH = PROJECT / "fixtures" / "repeated_ingest_v14.json"
REPORT = PROJECT / "evidence" / "V14" / "repeated_ingest_comparison.json"

EXPECTED_SCENARIOS = {
    "FULL_BASELINE": ("accepted", None),
    "REPEAT_IDENTICAL": ("accepted", None),
    "REORDER_IDENTICAL": ("accepted", None),
    "PARTITIONED_REPLAY": ("accepted", None),
    "PARTIAL_OVERLAP": ("accepted", None),
    "INTRA_BATCH_IDENTICAL_DUPLICATE": ("accepted", None),
    "CONFLICTING_PRIMARY_KEY": ("rejected", "identity_conflict"),
    "CONFLICT_WITHIN_BATCH": ("rejected", "identity_conflict"),
    "SECONDARY_WORK_ORDER_CONFLICT": ("rejected", "duplicate_work_order_reference"),
    "ORPHAN_CASE_ASSET": ("rejected", "unknown_asset_reference"),
    "ORPHAN_REVIEW_CASE": ("rejected", "unknown_case_reference"),
    "ORPHAN_LABEL_CASE": ("rejected", "unknown_case_reference"),
    "INVALID_ROW_ATOMIC_ROLLBACK": ("rejected", "source_record_invalid"),
    "NON_SYNTHETIC_ID": ("rejected", "source_record_invalid"),
    "EXTRA_PERSONNEL_FIELD": ("rejected", "source_record_invalid"),
    "INVALID_BATCH_SHAPE": ("rejected", "batch_shape_invalid"),
}


def require(condition: Any, code: str) -> None:
    if not condition:
        raise ingest_v14.IngestRejected(code)


def load_plan() -> dict[str, Any]:
    try:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ingest_v14.IngestRejected("replay_plan_unavailable") from None
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    require(type(plan) is dict, "plan_not_object")
    require(plan.get("schema_version") == "1.0.0", "plan_version_invalid")
    require(plan.get("increment") == "V14", "plan_increment_invalid")
    require(plan.get("objective") == "Enforce duplicates and idempotency rules",
            "plan_objective_drift")
    require(plan.get("required_proof") == "Repeated-ingest comparison",
            "plan_proof_drift")
    require(plan.get("plan_state") == "SYNTHETIC_REPLAY_TECHNICAL_DRAFT",
            "plan_false_approval")
    require(plan.get("source_fixture_set_id") == "SYN-RI-V5-20261107-A",
            "plan_fixture_set_drift")
    require(plan.get("expected_original_records") == 34, "plan_record_count_drift")
    for key in ("customer_data_used", "real_operator_actions",
                "human_approval_recorded", "formal_phase_02_approval"):
        require(plan.get(key) is False, "plan_false_authority_" + key)
    scenarios = plan.get("scenarios")
    require(type(scenarios) is list and len(scenarios) == len(EXPECTED_SCENARIOS),
            "scenario_inventory_drift")
    seen: set[str] = set()
    for item in scenarios:
        require(type(item) is dict, "scenario_not_object")
        name = item.get("scenario_id")
        require(type(name) is str and name in EXPECTED_SCENARIOS and
                name not in seen, "unknown_or_duplicate_scenario")
        seen.add(name)
        kind, error = EXPECTED_SCENARIOS[name]
        require(item.get("kind") == kind and
                type(item.get("description")) is str and
                len(item["description"]) > 20, "scenario_description_or_kind_drift")
        if kind == "rejected":
            require(item.get("expected_error") == error and
                    set(item) == {"scenario_id", "kind", "expected_error", "description"},
                    "expected_error_drift")
        else:
            require(type(item.get("expected_new_records")) is int and
                    type(item.get("expected_duplicates")) is int and
                    set(item) == {
                        "scenario_id", "kind", "expected_new_records",
                        "expected_duplicates", "description"
                    }, "expected_count_shape_drift")
    require(seen == set(EXPECTED_SCENARIOS), "missing_replay_scenarios")


def _new_store(inputs: tuple[dict[str, Any], dict[str, Any],
                             dict[str, Any], dict[str, dict[str, Any]]]
               ) -> ingest_v14.InMemoryIngest:
    policy, dictionary, v12_contract, _ = inputs
    return ingest_v14.InMemoryIngest(policy, dictionary, v12_contract)


def _case_with_new_id(row: dict[str, Any]) -> dict[str, Any]:
    new_row = copy.deepcopy(row)
    new_row["case_id"] = "SYN-CASE-099"
    new_row["work_order_ref"] = "SYN-WO-099"
    return new_row


def exercise_plan(plan: dict[str, Any],
                  inputs: tuple[dict[str, Any], dict[str, Any],
                                dict[str, Any], dict[str, dict[str, Any]]]
                  ) -> dict[str, Any]:
    """Deterministic evidence for exactly six accepted and ten rejected cases."""
    validate_plan(plan)
    policy, dictionary, contract, sources = inputs
    batch = ingest_v14.source_batch(sources)
    original_source_sha = ingest_v14.sha256(sources)
    scenarios = {s["scenario_id"]: s for s in plan["scenarios"]}
    results: list[dict[str, Any]] = []

    store = _new_store(inputs)
    first = store.ingest(batch)
    baseline_sha = first["state_sha256"]
    require(first["inserted"] == 34 and first["duplicates"] == 0,
            "initial_ingest_count")
    results.append({"scenario_id": "FULL_BASELINE", "result": "PASS",
                    "inserted": first["inserted"], "duplicates": first["duplicates"],
                    "state_sha256": baseline_sha})

    repeated = store.ingest(copy.deepcopy(batch))
    require(repeated["inserted"] == 0 and repeated["duplicates"] == 34
            and repeated["state_sha256"] == baseline_sha, "idempotent_full_replay")
    results.append({"scenario_id": "REPEAT_IDENTICAL", "result": "PASS",
                    "inserted": 0, "duplicates": 34, "state_sha256": baseline_sha})

    reordered = {name: list(reversed(copy.deepcopy(batch[name])))
                 for name in reversed(tuple(batch))}
    third = store.ingest(reordered)
    require(third["inserted"] == 0 and third["duplicates"] == 34 and
            third["state_sha256"] == baseline_sha, "idempotent_reordered_replay")
    results.append({"scenario_id": "REORDER_IDENTICAL", "result": "PASS",
                    "inserted": 0, "duplicates": 34, "state_sha256": baseline_sha})

    partitioned = _new_store(inputs)
    parts = ("asset_records", "case_records",
             "scripted_review_entries", "seeded_reference_labels")
    total_inserted = 0
    for name in parts:
        receipt = partitioned.ingest({name: copy.deepcopy(batch[name])})
        total_inserted += receipt["inserted"]
    require(total_inserted == 34 and partitioned.state_sha256() == baseline_sha,
            "partition_replay_digest_mismatch")
    results.append({"scenario_id": "PARTITIONED_REPLAY", "result": "PASS",
                    "inserted": total_inserted, "duplicates": 0,
                    "state_sha256": partitioned.state_sha256()})

    partial = store.ingest({"case_records": copy.deepcopy(batch["case_records"][:7])})
    require(partial["inserted"] == 0 and partial["duplicates"] == 7 and
            partial["state_sha256"] == baseline_sha, "overlap_replay_not_idempotent")
    results.append({"scenario_id": "PARTIAL_OVERLAP", "result": "PASS",
                    "inserted": 0, "duplicates": 7, "state_sha256": baseline_sha})

    repeated_in_batch = copy.deepcopy(batch)
    repeated_in_batch["case_records"].append(copy.deepcopy(batch["case_records"][0]))
    double_store = _new_store(inputs)
    same_batch = double_store.ingest(repeated_in_batch)
    require(same_batch["inserted"] == 34 and same_batch["duplicates"] == 1 and
            same_batch["state_sha256"] == baseline_sha,
            "same_batch_duplicate_not_suppressed")
    results.append({"scenario_id": "INTRA_BATCH_IDENTICAL_DUPLICATE",
                    "result": "PASS", "inserted": 34, "duplicates": 1,
                    "state_sha256": baseline_sha})

    def failure(name: str, target: ingest_v14.InMemoryIngest,
                candidate_batch: dict[str, list[dict[str, Any]]]) -> None:
        previous_digest = target.state_sha256()
        previous_snapshot = target.snapshot()
        try:
            target.ingest(candidate_batch)
        except ingest_v14.IngestRejected as exc:
            require(str(exc) == scenarios[name]["expected_error"],
                    "unexpected_rejection_category")
        else:
            raise ingest_v14.IngestRejected("invalid_batch_was_accepted")
        require(target.state_sha256() == previous_digest and
                target.snapshot() == previous_snapshot, "atomicity_broken")
        results.append({"scenario_id": name, "result": "REJECTED_AS_EXPECTED",
                        "error_code": scenarios[name]["expected_error"],
                        "state_preserved": True})

    modified_case = copy.deepcopy(batch["case_records"][0])
    modified_case["repair_cost_usd"] = 861
    failure("CONFLICTING_PRIMARY_KEY", store,
            {"case_records": [modified_case]})

    altered_asset = copy.deepcopy(batch["asset_records"][0])
    altered_asset["asset_class"] = "electric_motor"
    failure("CONFLICT_WITHIN_BATCH", _new_store(inputs),
            {"asset_records": [copy.deepcopy(batch["asset_records"][0]), altered_asset]})

    work_order_conflict = _case_with_new_id(batch["case_records"][0])
    work_order_conflict["work_order_ref"] = batch["case_records"][0]["work_order_ref"]
    failure("SECONDARY_WORK_ORDER_CONFLICT", store,
            {"case_records": [work_order_conflict]})

    orphan = _case_with_new_id(batch["case_records"][0])
    orphan["asset_id"] = "SYN-ASSET-999"
    failure("ORPHAN_CASE_ASSET", store, {"case_records": [orphan]})

    orphan_review = copy.deepcopy(batch["scripted_review_entries"][0])
    orphan_review["case_id"] = "SYN-CASE-099"
    failure("ORPHAN_REVIEW_CASE", store,
            {"scripted_review_entries": [orphan_review]})

    orphan_label = copy.deepcopy(batch["seeded_reference_labels"][0])
    orphan_label["case_id"] = "SYN-CASE-099"
    failure("ORPHAN_LABEL_CASE", store,
            {"seeded_reference_labels": [orphan_label]})

    invalid_case = _case_with_new_id(batch["case_records"][0])
    invalid_case["invented_operator_email"] = "SYN-NOT-A-PERSON"
    new_asset = copy.deepcopy(batch["asset_records"][0])
    new_asset["asset_id"] = "SYN-ASSET-099"
    failure("INVALID_ROW_ATOMIC_ROLLBACK", store,
            {"asset_records": [new_asset], "case_records": [invalid_case]})

    invalid_asset = copy.deepcopy(batch["asset_records"][0])
    invalid_asset["asset_id"] = "REAL-ASSET-999"
    failure("NON_SYNTHETIC_ID", store, {"asset_records": [invalid_asset]})

    bad_personnel_field = copy.deepcopy(batch["case_records"][0])
    bad_personnel_field["operator_email"] = "SYN-ONLY"
    failure("EXTRA_PERSONNEL_FIELD", store,
            {"case_records": [bad_personnel_field]})

    failure("INVALID_BATCH_SHAPE", store,
            {"real_customer_workorders": []})

    for record in results:
        item = scenarios[record["scenario_id"]]
        if item["kind"] == "accepted":
            require(record["inserted"] == item["expected_new_records"] and
                    record["duplicates"] == item["expected_duplicates"],
                    "replay_expected_count_mismatch")
    require(len(results) == len(EXPECTED_SCENARIOS) and
            {x["scenario_id"] for x in results} == set(EXPECTED_SCENARIOS),
            "incomplete_repeated_ingest_replay")
    require(ingest_v14.sha256(sources) == original_source_sha,
            "original_source_was_modified")
    require(store.state_sha256() == baseline_sha and
            double_store.state_sha256() == baseline_sha and
            partitioned.state_sha256() == baseline_sha,
            "final_digest_changed_by_replay")
    return {
        "scenario_count": len(results),
        "accepted_scenarios": 6,
        "rejected_scenarios": 10,
        "original_record_count": 34,
        "replayed_duplicate_count": repeated["duplicates"],
        "canonical_baseline_sha256": baseline_sha,
        "final_replay_sha256": store.state_sha256(),
        "original_synthetic_source_sha256": original_source_sha,
        "original_sources_unchanged": True,
        "replays_idempotent": True,
        "conflicts_atomic": True,
        "simulator_persistent_storage": False,
        "scenario_results": results,
    }


def main() -> int:
    frozen = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
            "v10_promotion_not_approved")
    inputs = ingest_v14.load_ingest_inputs()
    policy, dictionary, contract, sources = inputs
    ingest_v14.validate_policy(policy, dictionary, contract)
    dictionary_index = verify_v11.validate_dictionary(dictionary)
    verify_v11.validate_rows(dictionary_index, sources)
    v12_groups = verify_v12.validate_contract(contract, dictionary)
    verify_v12.validate_rows(v12_groups, sources)
    verify_v13.validate_semantic_bounds(v12_groups, dictionary_index, sources)
    plan = load_plan()
    result = exercise_plan(plan, inputs)
    report = {
        "increment": "V14",
        "objective": "Enforce duplicates and idempotency rules",
        "required_proof": "Repeated-ingest comparison",
        "result": "synthetic_idempotency_verified_formal_approval_pending",
        "synthetic_only": True,
        "source_baseline_commit": policy["v9_frozen_source_commit"],
        "frozen_v10_source_files_verified": frozen["frozen_files_verified"],
        "v10_formal_phase_promotion": "BLOCKED_RECOMMENDATION_PENDING_HUMAN_SIGNOFF",
        "v11_source_dictionary_approved": False,
        "v12_schema_approved": False,
        "v14_product_owner_approved": False,
        "customer_data_used": False,
        "production_write_actions": False,
        "external_systems_contacted": False,
        "comparison": result,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "Per-process in-memory deduplication, not persistent or distributed exactly-once delivery.",
            "No client data; duplicates defined by fabricated source keys and byte-canonical JSON records.",
            "No customer-approved identity or uniqueness semantics; no CMMS/ERP/OT deployment.",
            "Passing CI cannot sign V10 phase promotion or V11/V12 source contracts.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print("V14_REPEATED_INGEST: " + json.dumps({
        "result": report["result"],
        "scenarios": result["scenario_count"],
        "accepted_scenarios": result["accepted_scenarios"],
        "rejected_scenarios": result["rejected_scenarios"],
        "full_replay_duplicates": result["replayed_duplicate_count"],
        "same_snapshot_after_repeats": result["replays_idempotent"],
        "frozen_files": frozen["frozen_files_verified"],
        "formal_approval": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ingest_v14.IngestRejected, verify_v10.DecisionEvidenceError,
            verify_v11.FieldDictionaryError, verify_v12.SchemaContractError,
            verify_v13.V13NegativeCaseError, ValueError, TypeError,
            KeyError, OSError):
        print("V14_REPEATED_INGEST_FAILED: validation_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
