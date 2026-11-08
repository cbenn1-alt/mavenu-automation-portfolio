"""V14 idempotency and duplicate rejection: synthetic-only regression.

No customer input, persistent store, OT connection or release approval.
Every test uses isolated in-memory copies of the fictional V5/V6 fixtures.
"""

import copy
import json
import math
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import ingest_v14 as ingest
import verify_v14 as verifier


class V14RepeatedIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = ingest.load_ingest_inputs()
        cls.policy, cls.dictionary, cls.contract, cls.sources = cls.inputs
        cls.plan = verifier.load_plan()
        verifier.validate_plan(cls.plan)
        cls.batch = ingest.source_batch(cls.sources)
        cls.replay = verifier.exercise_plan(cls.plan, cls.inputs)
        cls.scenarios = {r["scenario_id"]: r for r in cls.replay["scenario_results"]}

    def store(self):
        return ingest.InMemoryIngest(self.policy, self.dictionary, self.contract)

    def full_store(self):
        store = self.store()
        result = store.ingest(self.batch)
        return store, result

    def test_01_objective_and_exact_proof(self):
        self.assertEqual(self.policy["objective"], "Enforce duplicates and idempotency rules")
        self.assertEqual(self.policy["required_proof"], "Repeated-ingest comparison")
        self.assertEqual(self.plan["required_proof"], "Repeated-ingest comparison")

    def test_02_synthetic_authorization_is_not_customer_approval(self):
        for flag in ("formal_phase_02_authorized", "customer_data_authorized",
                     "human_owner_approval", "production_write_authorized",
                     "network_ingestion_enabled", "cross_process_exactly_once_guarantee"):
            self.assertIs(self.policy[flag], False)
        self.assertIsNone(self.policy["approval_signature"])

    def test_03_four_separate_identity_scopes(self):
        self.assertEqual(self.policy["identity_fields"], ingest.IDENTITIES)
        self.assertEqual(len(self.policy["identity_fields"]), 4)
        self.assertEqual(len(self.batch), 4)

    def test_04_full_first_ingest_has_34_records(self):
        store, receipt = self.full_store()
        self.assertEqual(receipt["inserted"], 34)
        self.assertEqual(receipt["duplicates"], 0)
        self.assertEqual(sum(store.row_counts().values()), 34)

    def test_05_identical_replay_has_zero_new_records(self):
        store, first = self.full_store()
        second = store.ingest(copy.deepcopy(self.batch))
        self.assertEqual((second["inserted"], second["duplicates"]), (0, 34))
        self.assertEqual(second["state_sha256"], first["state_sha256"])

    def test_06_order_independent_replay(self):
        store, first = self.full_store()
        shuffled = {key: list(reversed(copy.deepcopy(value)))
                    for key, value in reversed(list(self.batch.items()))}
        result = store.ingest(shuffled)
        self.assertEqual(result["state_sha256"], first["state_sha256"])
        self.assertEqual(result["duplicates"], 34)

    def test_07_partitioned_parent_first_ingestion_is_equivalent(self):
        a, first = self.full_store()
        b = self.store()
        for name in ("asset_records", "case_records",
                     "scripted_review_entries", "seeded_reference_labels"):
            b.ingest({name: self.batch[name]})
        self.assertEqual(b.state_sha256(), first["state_sha256"])
        self.assertEqual(b.snapshot(), a.snapshot())

    def test_08_partial_overlap_no_change(self):
        store, first = self.full_store()
        again = store.ingest({"case_records": self.batch["case_records"][:7]})
        self.assertEqual(again["duplicates"], 7)
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(first["state_sha256"], again["state_sha256"])

    def test_09_identical_duplicate_within_new_batch_is_suppressed(self):
        records = copy.deepcopy(self.batch)
        records["case_records"].append(copy.deepcopy(records["case_records"][0]))
        receipt = self.store().ingest(records)
        self.assertEqual((receipt["inserted"], receipt["duplicates"]), (34, 1))

    def test_10_empty_batch_is_idempotent(self):
        store, first = self.full_store()
        again = store.ingest({})
        self.assertEqual((again["inserted"], again["duplicates"]), (0, 0))
        self.assertEqual(again["state_sha256"], first["state_sha256"])

    def test_11_snapshot_is_defensive_copy(self):
        store, first = self.full_store()
        snapshot = store.snapshot()
        snapshot["asset_records"][0]["asset_class"] = "corrupted"
        self.assertEqual(store.state_sha256(), first["state_sha256"])

    def test_12_canonical_json_key_order_is_stable(self):
        a = {"a": 1, "b": {"x": True, "y": [1, 2]}}
        b = {"b": {"y": [1, 2], "x": True}, "a": 1}
        self.assertEqual(ingest.sha256(a), ingest.sha256(b))

    def test_13_canonical_json_rejects_nonfinite(self):
        with self.assertRaisesRegex(ingest.IngestRejected, "noncanonical_payload"):
            ingest.sha256({"x": math.nan})

    def test_14_primary_identity_conflict_preserves_state(self):
        store, first = self.full_store()
        changed = copy.deepcopy(self.batch["case_records"][0])
        changed["repair_cost_usd"] += 1
        with self.assertRaisesRegex(ingest.IngestRejected, "identity_conflict"):
            store.ingest({"case_records": [changed]})
        self.assertEqual(store.state_sha256(), first["state_sha256"])

    def test_15_identical_primary_key_but_different_array_order_conflicts(self):
        store, first = self.full_store()
        changed = copy.deepcopy(self.batch["case_records"][0])
        changed["evidence_refs"] = ["SYN-EV-002", "SYN-EV-001"]
        with self.assertRaisesRegex(ingest.IngestRejected, "identity_conflict"):
            store.ingest({"case_records": [changed]})
        self.assertEqual(store.state_sha256(), first["state_sha256"])

    def test_16_two_new_cases_cannot_share_work_order_ref(self):
        store, first = self.full_store()
        first_case = copy.deepcopy(self.batch["case_records"][0])
        second_case = copy.deepcopy(self.batch["case_records"][1])
        first_case["case_id"] = "SYN-CASE-098"
        second_case["case_id"] = "SYN-CASE-099"
        first_case["work_order_ref"] = "SYN-WO-099"
        second_case["work_order_ref"] = "SYN-WO-099"
        with self.assertRaisesRegex(ingest.IngestRejected,
                                    "duplicate_work_order_reference"):
            store.ingest({"case_records": [first_case, second_case]})
        self.assertEqual(store.state_sha256(), first["state_sha256"])

    def test_17_reversed_dataset_keys_same_batch_are_valid(self):
        store = self.store()
        reversed_data = {name: copy.deepcopy(self.batch[name])
                         for name in reversed(tuple(self.batch))}
        result = store.ingest(reversed_data)
        self.assertEqual(result["inserted"], 34)
        self.assertEqual(result["state_sha256"], self.replay["canonical_baseline_sha256"])

    def test_18_failed_batch_does_not_commit_valid_staged_asset(self):
        store, first = self.full_store()
        new_asset = copy.deepcopy(self.batch["asset_records"][0])
        new_asset["asset_id"] = "SYN-ASSET-099"
        invalid_case = copy.deepcopy(self.batch["case_records"][0])
        invalid_case["case_id"] = "SYN-CASE-099"
        invalid_case["work_order_ref"] = "SYN-WO-099"
        invalid_case["employee_email"] = "SYN-ONLY"
        with self.assertRaisesRegex(ingest.IngestRejected, "source_record_invalid"):
            store.ingest({"asset_records": [new_asset], "case_records": [invalid_case]})
        self.assertEqual(store.state_sha256(), first["state_sha256"])
        self.assertEqual(store.row_counts()["asset_records"], 6)

    def test_19_reference_integrity_failure_is_atomic(self):
        store, first = self.full_store()
        row = copy.deepcopy(self.batch["case_records"][0])
        row["case_id"] = "SYN-CASE-099"
        row["work_order_ref"] = "SYN-WO-099"
        row["asset_id"] = "SYN-ASSET-999"
        with self.assertRaisesRegex(ingest.IngestRejected, "unknown_asset_reference"):
            store.ingest({"case_records": [row]})
        self.assertEqual(store.state_sha256(), first["state_sha256"])

    def test_20_unexpected_dataset_is_rejected(self):
        store = self.store()
        with self.assertRaisesRegex(ingest.IngestRejected, "batch_shape_invalid"):
            store.ingest({"real_customer_cases": []})

    def test_21_rows_must_be_lists(self):
        store = self.store()
        with self.assertRaisesRegex(ingest.IngestRejected, "batch_shape_invalid"):
            store.ingest({"asset_records": {"asset_id": "SYN-ASSET-100"}})

    def test_22_null_rows_are_rejected(self):
        store = self.store()
        with self.assertRaisesRegex(ingest.IngestRejected, "source_record_invalid"):
            store.ingest({"asset_records": [None]})

    def test_23_policy_must_not_claim_persistent_storage(self):
        changed = copy.deepcopy(self.policy)
        changed["persistence"] = "production_db"
        with self.assertRaisesRegex(ingest.IngestRejected, "persistence_claim_drift"):
            ingest.validate_policy(changed, self.dictionary, self.contract)

    def test_24_policy_must_not_claim_signed_customer_approval(self):
        changed = copy.deepcopy(self.policy)
        changed["customer_data_authorized"] = True
        with self.assertRaises(ingest.IngestRejected):
            ingest.validate_policy(changed, self.dictionary, self.contract)

    def test_25_policy_must_not_change_primary_keys(self):
        changed = copy.deepcopy(self.policy)
        changed["identity_fields"]["case_records"] = "work_order_ref"
        with self.assertRaises(ingest.IngestRejected):
            ingest.validate_policy(changed, self.dictionary, self.contract)

    def test_26_replay_plan_cannot_drop_scenario(self):
        changed = copy.deepcopy(self.plan)
        changed["scenarios"].pop()
        with self.assertRaises(verifier.ingest_v14.IngestRejected):
            verifier.validate_plan(changed)

    def test_27_replay_plan_cannot_falsify_error(self):
        changed = copy.deepcopy(self.plan)
        bad = next(x for x in changed["scenarios"]
                   if x["scenario_id"] == "CONFLICTING_PRIMARY_KEY")
        bad["expected_error"] = "allowed"
        with self.assertRaises(verifier.ingest_v14.IngestRejected):
            verifier.validate_plan(changed)

    def test_28_all_sixteen_replay_scenarios_pass(self):
        self.assertEqual(self.replay["scenario_count"], 16)
        self.assertEqual(self.replay["accepted_scenarios"], 6)
        self.assertEqual(self.replay["rejected_scenarios"], 10)
        self.assertTrue(self.replay["conflicts_atomic"])
        self.assertFalse(self.replay["simulator_persistent_storage"])

    def test_29_replay_evidence_deterministic_across_instances(self):
        other = verifier.exercise_plan(self.plan, self.inputs)
        self.assertEqual(self.replay, other)

    def test_30_replay_did_not_mutate_sources(self):
        first = ingest.sha256(self.sources)
        verifier.exercise_plan(self.plan, self.inputs)
        self.assertEqual(first, ingest.sha256(self.sources))

    def test_31_no_new_runtime_code_or_customer_connectors(self):
        self.assertEqual(self.policy["persistence"], "NONE")
        self.assertIs(self.policy["production_write_authorized"], False)
        self.assertIs(self.policy["network_ingestion_enabled"], False)
        self.assertIs(self.policy["cross_process_exactly_once_guarantee"], False)

    def test_32_documented_source_snapshot_is_still_v9(self):
        self.assertEqual(self.policy["v9_frozen_source_commit"],
                         "704123eca45628bf504594af39a66036cc0451c5")
        self.assertEqual(self.policy["expected_reference_records"], 34)

    def test_33_scenario_full_baseline(self):
        self.assertEqual(self.scenarios["FULL_BASELINE"]["result"], "PASS")

    def test_34_scenario_repeat_identical(self):
        self.assertEqual(self.scenarios["REPEAT_IDENTICAL"]["result"], "PASS")

    def test_35_scenario_reorder_identical(self):
        self.assertEqual(self.scenarios["REORDER_IDENTICAL"]["result"], "PASS")

    def test_36_scenario_partitioned_replay(self):
        self.assertEqual(self.scenarios["PARTITIONED_REPLAY"]["result"], "PASS")

    def test_37_scenario_partial_overlap(self):
        self.assertEqual(self.scenarios["PARTIAL_OVERLAP"]["result"], "PASS")

    def test_38_scenario_intra_batch_identical_duplicate(self):
        self.assertEqual(self.scenarios["INTRA_BATCH_IDENTICAL_DUPLICATE"]["result"], "PASS")

    def test_39_scenario_conflicting_primary_key(self):
        self.assertEqual(self.scenarios["CONFLICTING_PRIMARY_KEY"]["result"], "REJECTED_AS_EXPECTED")

    def test_40_scenario_conflict_within_batch(self):
        self.assertEqual(self.scenarios["CONFLICT_WITHIN_BATCH"]["result"], "REJECTED_AS_EXPECTED")

    def test_41_scenario_secondary_work_order_conflict(self):
        self.assertEqual(self.scenarios["SECONDARY_WORK_ORDER_CONFLICT"]["result"], "REJECTED_AS_EXPECTED")

    def test_42_scenario_orphan_case_asset(self):
        self.assertEqual(self.scenarios["ORPHAN_CASE_ASSET"]["result"], "REJECTED_AS_EXPECTED")

    def test_43_scenario_orphan_review_case(self):
        self.assertEqual(self.scenarios["ORPHAN_REVIEW_CASE"]["result"], "REJECTED_AS_EXPECTED")

    def test_44_scenario_orphan_label_case(self):
        self.assertEqual(self.scenarios["ORPHAN_LABEL_CASE"]["result"], "REJECTED_AS_EXPECTED")

    def test_45_scenario_invalid_row_atomic_rollback(self):
        self.assertEqual(self.scenarios["INVALID_ROW_ATOMIC_ROLLBACK"]["result"], "REJECTED_AS_EXPECTED")

    def test_46_scenario_non_synthetic_id(self):
        self.assertEqual(self.scenarios["NON_SYNTHETIC_ID"]["result"], "REJECTED_AS_EXPECTED")

    def test_47_scenario_extra_personnel_field(self):
        self.assertEqual(self.scenarios["EXTRA_PERSONNEL_FIELD"]["result"], "REJECTED_AS_EXPECTED")

    def test_48_scenario_invalid_batch_shape(self):
        self.assertEqual(self.scenarios["INVALID_BATCH_SHAPE"]["result"], "REJECTED_AS_EXPECTED")

if __name__ == "__main__":
    unittest.main()
