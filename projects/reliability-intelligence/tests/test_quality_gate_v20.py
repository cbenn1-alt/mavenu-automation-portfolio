"""V20 data quality review gate: tests that prove CI cannot grant sign-off.

No real customer source, plant environment, reviewer identity or operational
access. Mock evidence reports are constructed from a fixed policy solely to
exercise the gate; real report replay occurs in scripts/verify_v20.py.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import gate_v20 as gate


def fake_reports(register: dict) -> dict:
    reports = {}
    entries = (register["evidence_policy"]["supporting_evidence"] +
               register["evidence_policy"]["required_stages"])
    for item in entries:
        proof = {"increment": item["increment"],
                 "result": item.get("expected_result", "synthetic_pass")}
        for dotted, expected in item["checks"].items():
            node = proof
            keys = dotted.split(".")
            for key in keys[:-1]:
                node = node.setdefault(key, {})
            node[keys[-1]] = expected
        if item["increment"] == "V8":
            proof["test_count"] = 754
            proof["coverage_total_percent"] = 84.951
        reports[item["evidence_path"]] = proof
    return reports


class V20DataQualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.register = gate.baseline()
        cls.form = gate.signoff()
        cls.fixture = fake_reports(cls.register)

    def check_rejected(self, changed_register=None, changed_signoff=None):
        with self.assertRaises(gate.QualityGateRejected):
            gate.validate_baseline(
                self.register if changed_register is None else changed_register,
                self.form if changed_signoff is None else changed_signoff
            )

    def test_01_exact_architecture_objective_and_proof(self):
        self.assertEqual(self.register["objective"],
                         "Approve data correctness test baseline")
        self.assertEqual(self.register["required_proof"], "Data quality sign-off")

    def test_02_v20_remains_an_unsigned_request(self):
        self.assertEqual(self.form["record_state"],
                         "UNSIGNED_DRAFT_DO_NOT_USE_AS_APPROVAL")
        self.assertIs(self.form["phase_signoff_granted"], False)
        self.assertEqual(self.form["decision"], "BLOCKED_PENDING_HUMAN_SIGNOFF")

    def test_03_formal_phase_02_promotion_is_not_approved(self):
        self.assertEqual(self.register["gate_policy"]["recommended_decision"],
                         "DO_NOT_PROMOTE")
        self.assertEqual(self.register["gate_policy"]["human_approval_state"],
                         "BLOCKED_PENDING_HUMAN_SIGNOFF")

    def test_04_all_nine_v11_v19_stages_present(self):
        entries = self.register["evidence_policy"]["required_stages"]
        self.assertEqual(len(entries), 9)
        self.assertEqual([x["increment"] for x in entries],
                         [f"V{i}" for i in range(11, 20)])

    def test_05_two_historical_prerequisite_reports(self):
        entries = self.register["evidence_policy"]["supporting_evidence"]
        self.assertEqual([x["increment"] for x in entries], ["V8", "V10"])

    def test_06_eight_distinct_blocking_decisions(self):
        items = self.register["gate_policy"]["blocking_items"]
        self.assertEqual([x["id"] for x in items], gate.BLOCKER_IDS)
        self.assertEqual(len(set(x["id"] for x in items)), 8)

    def test_07_every_blocker_has_evidence_and_owner_role(self):
        for row in self.register["gate_policy"]["blocking_items"]:
            self.assertGreater(len(row["owner_role"]), 5)
            self.assertGreater(len(row["resolution_proof"]), 20)
            self.assertGreater(len(row["issue"]), 30)

    def test_08_coverage_floor_is_retained(self):
        self.assertEqual(self.register["evidence_policy"]
                         ["minimum_combined_coverage_percent"], 84.5)

    def test_09_old_regression_floor_is_retained(self):
        self.assertEqual(self.register["evidence_policy"]
                         ["minimum_total_regression_tests"], 754)

    def test_10_all_stages_match_known_proof_contracts(self):
        gate.validate_baseline(self.register, self.form)

    def test_11_mock_evidence_exactly_matches_its_technical_fixture(self):
        result = gate.verify_proof_entries(self.register, self.fixture)
        self.assertEqual(result["reports_verified"], 11)
        self.assertEqual(result["v11_v19_reports_verified"], 9)
        self.assertEqual(result["supporting_reports_verified"], 2)

    def test_12_passing_technical_gate_cannot_approve_humans(self):
        result = gate.evaluate_quality_gate(
            self.register, self.form, self.fixture, 84.951, 754
        )
        self.assertEqual(result["technical_evidence"], "PASS")
        self.assertEqual(result["decision"], "DO_NOT_PROMOTE")
        self.assertEqual(result["human_data_quality_signoff"],
                         "BLOCKED_PENDING_HUMAN_SIGNOFF")
        self.assertIs(result["future_phase_v21_authorized"], False)
        self.assertIs(result["customer_data_authorized"], False)
        self.assertIs(result["owner_signature_observed"], False)

    def test_13_signature_fields_are_all_null(self):
        for field in gate.SIGNATURE_FIELDS:
            self.assertIsNone(self.form[field])

    def test_14_real_upstream_phase_approval_not_recorded(self):
        result = gate.validate_source_approvals()
        self.assertEqual(result["v11_dictionary"], "DRAFT_NOT_APPROVED")
        self.assertEqual(result["v12_schema"], "DRAFT_NOT_APPROVED")
        self.assertIn("BLOCKED", result["v10_formal_promotion"])

    def test_15_missing_evidence_path_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered.pop("evidence/V19/independent_reconciliation_report.json")
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "proof_evidence_inventory_incomplete"):
            gate.verify_proof_entries(self.register, altered)

    def test_16_extra_unapproved_evidence_path_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["evidence/customer.json"] = {"increment": "V99"}
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "proof_evidence_inventory_incomplete"):
            gate.verify_proof_entries(self.register, altered)

    def test_17_wrong_increment_in_evidence_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["evidence/V19/independent_reconciliation_report.json"]["increment"] = "V18"
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "proof_increment_mismatch"):
            gate.verify_proof_entries(self.register, altered)

    def test_18_wrong_expected_result_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        altered["evidence/V17/golden_reference_report.json"]["result"] = "approved"
        with self.assertRaisesRegex(gate.QualityGateRejected, "proof_result_mismatch"):
            gate.verify_proof_entries(self.register, altered)

    def test_19_wrong_nested_metric_is_rejected(self):
        altered = copy.deepcopy(self.fixture)
        path = "evidence/V19/independent_reconciliation_report.json"
        altered[path]["reconciliation"]["reconciled_output_units"] = 24
        with self.assertRaisesRegex(gate.QualityGateRejected, "proof_field_mismatch"):
            gate.verify_proof_entries(self.register, altered)

    def test_20_bool_is_not_equivalent_to_numeric_one(self):
        self.assertIs(gate.exact_value(True, 1), False)
        self.assertIs(gate.exact_value(1, 1), True)

    def test_21_type_corrupted_nested_value_rejected(self):
        altered = copy.deepcopy(self.fixture)
        path = "evidence/V19/independent_reconciliation_report.json"
        altered[path]["reconciliation"]["reconciled_output_units"] = "25"
        with self.assertRaisesRegex(gate.QualityGateRejected, "proof_field_mismatch"):
            gate.verify_proof_entries(self.register, altered)

    def test_22_future_phase_cannot_be_automatically_authorized(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["future_phase_v21_authorized"] = True
        self.check_rejected(changed_register=altered)

    def test_23_customer_ingestion_cannot_be_automatically_authorized(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["customer_data_authorized"] = True
        self.check_rejected(changed_register=altered)

    def test_24_ot_writes_cannot_be_automatically_authorized(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["ot_or_cmms_write_authorized"] = True
        self.check_rejected(changed_register=altered)

    def test_25_cannot_fabricate_owner_identity(self):
        altered = copy.deepcopy(self.form)
        altered["named_product_owner"] = "Fake Person"
        self.check_rejected(changed_signoff=altered)

    def test_26_cannot_fabricate_independent_reviewer(self):
        altered = copy.deepcopy(self.form)
        altered["independent_reviewer_signature"] = "Fake"
        self.check_rejected(changed_signoff=altered)

    def test_27_cannot_supply_undocumented_decision_date(self):
        altered = copy.deepcopy(self.form)
        altered["decision_date_utc"] = "2026-11-08"
        self.check_rejected(changed_signoff=altered)

    def test_28_cannot_invent_accepted_residual_risk(self):
        altered = copy.deepcopy(self.form)
        altered["residual_risks_accepted"] = True
        self.check_rejected(changed_signoff=altered)

    def test_29_cannot_claim_formal_v10_resolution(self):
        altered = copy.deepcopy(self.form)
        altered["formal_v10_gate_resolved"] = True
        self.check_rejected(changed_signoff=altered)

    def test_30_cannot_change_signature_template_to_approved(self):
        altered = copy.deepcopy(self.register)
        altered["signature_template"]["phase_signoff_granted"] = True
        self.check_rejected(changed_register=altered)

    def test_31_rejects_dropped_baseline_stage(self):
        altered = copy.deepcopy(self.register)
        altered["evidence_policy"]["required_stages"].pop()
        self.check_rejected(changed_register=altered)

    def test_32_rejects_tampered_evidence_path(self):
        altered = copy.deepcopy(self.register)
        altered["evidence_policy"]["required_stages"][0]["evidence_path"] = (
            "evidence/customer.csv")
        self.check_rejected(changed_register=altered)

    def test_33_rejects_tampered_evidence_expected_value(self):
        altered = copy.deepcopy(self.register)
        altered["evidence_policy"]["required_stages"][8]["checks"][
            "reconciliation.reconciled_output_units"] = 24
        self.check_rejected(changed_register=altered)

    def test_34_rejects_removed_blocker(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"].pop()
        self.check_rejected(changed_register=altered)

    def test_35_rejects_blank_blocker_resolution_proof(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"][0]["resolution_proof"] = ""
        self.check_rejected(changed_register=altered)

    def test_36_rejects_wrong_standalone_signoff_decision(self):
        altered = copy.deepcopy(self.form)
        altered["decision"] = "APPROVED"
        self.check_rejected(changed_signoff=altered)

    def test_37_rejects_low_coverage(self):
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "source_coverage_below_floor"):
            gate.evaluate_quality_gate(self.register, self.form,
                                       self.fixture, 84.499, 754)

    def test_38_rejects_reduced_regression_inventory(self):
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "test_inventory_below_baseline"):
            gate.evaluate_quality_gate(self.register, self.form,
                                       self.fixture, 84.951, 753)

    def test_39_rejects_mismatched_coverage_report(self):
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "coverage_report_mismatch"):
            gate.evaluate_quality_gate(self.register, self.form,
                                       self.fixture, 84.952, 754)

    def test_40_rejects_mismatched_test_count_report(self):
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "coverage_test_count_mismatch"):
            gate.evaluate_quality_gate(self.register, self.form,
                                       self.fixture, 84.951, 755)

    def test_41_canonical_evidence_hash_does_not_depend_on_dict_order(self):
        self.assertEqual(gate.canonical_sha256({"a": 1, "b": 2}),
                         gate.canonical_sha256({"b": 2, "a": 1}))

    def test_42_nonfinite_evidence_is_rejected(self):
        with self.assertRaisesRegex(gate.QualityGateRejected,
                                    "noncanonical_evidence"):
            gate.canonical_sha256({"amount": float("nan")})

    def test_43_source_approval_reports_are_not_customer_access(self):
        self.assertFalse(self.register["gate_policy"]["production_ingestion_authorized"])
        self.assertFalse(self.register["gate_policy"]["customer_data_authorized"])

    def test_44_technical_state_is_not_release_approval(self):
        self.assertEqual(self.register["gate_policy"]["technical_evidence_state"],
                         "CAN_PASS_WITHOUT_HUMAN_SIGNATURE")
        self.assertIs(self.register["gate_policy"]["passing_ci_is_not_signoff"], True)

    def test_45_all_blocking_ids_in_unsigned_packet(self):
        self.assertEqual(self.form["blocking_ids"], gate.BLOCKER_IDS)

    def test_46_source_signature_drift_rejected(self):
        altered = copy.deepcopy(self.register)
        altered["pinned_v9_source_commit"] = "0" * 40
        self.check_rejected(changed_register=altered)

    def test_47_approval_reference_is_not_a_real_data_source(self):
        self.assertEqual(self.register["data_classification"],
                         "FABRICATED_SYNTHETIC_ONLY")
        self.assertEqual(self.register["fixture_set_id"],
                         "SYN-RI-V5-20261107-A")

    def test_48_no_signature_should_be_created_from_test_success(self):
        score = gate.evaluate_quality_gate(self.register, self.form,
                                           self.fixture, 84.951, 754)
        self.assertEqual(score["blockers_unresolved"], 8)
        self.assertIs(score["formal_phase_02_approval"], False)

    def test_stage_v11_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V11")
        self.assertEqual(item["evidence_path"], "evidence/V11/verification.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V11/verification.json"]["result"], item["expected_result"])

    def test_stage_v12_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V12")
        self.assertEqual(item["evidence_path"], "evidence/V12/schema_validation_report.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V12/schema_validation_report.json"]["result"], item["expected_result"])

    def test_stage_v13_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V13")
        self.assertEqual(item["evidence_path"], "evidence/V13/negative_case_report.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V13/negative_case_report.json"]["result"], item["expected_result"])

    def test_stage_v14_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V14")
        self.assertEqual(item["evidence_path"], "evidence/V14/repeated_ingest_comparison.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V14/repeated_ingest_comparison.json"]["result"], item["expected_result"])

    def test_stage_v15_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V15")
        self.assertEqual(item["evidence_path"], "evidence/V15/conversion_reference_report.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V15/conversion_reference_report.json"]["result"], item["expected_result"])

    def test_stage_v16_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V16")
        self.assertEqual(item["evidence_path"], "evidence/V16/lineage_verification.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V16/lineage_verification.json"]["result"], item["expected_result"])

    def test_stage_v17_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V17")
        self.assertEqual(item["evidence_path"], "evidence/V17/golden_reference_report.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V17/golden_reference_report.json"]["result"], item["expected_result"])

    def test_stage_v18_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V18")
        self.assertEqual(item["evidence_path"], "evidence/V18/adverse_regression_report.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V18/adverse_regression_report.json"]["result"], item["expected_result"])

    def test_stage_v19_contract_and_evidence(self):
        item = next(e for e in self.register["evidence_policy"]["required_stages"] if e["increment"] == "V19")
        self.assertEqual(item["evidence_path"], "evidence/V19/independent_reconciliation_report.json")
        self.assertGreaterEqual(len(item["checks"]), 2)
        self.assertEqual(self.fixture["evidence/V19/independent_reconciliation_report.json"]["result"], item["expected_result"])

    def test_blocker_01_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-01"]
        self.check_rejected(changed_register=altered)

    def test_blocker_02_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-02"]
        self.check_rejected(changed_register=altered)

    def test_blocker_03_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-03"]
        self.check_rejected(changed_register=altered)

    def test_blocker_04_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-04"]
        self.check_rejected(changed_register=altered)

    def test_blocker_05_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-05"]
        self.check_rejected(changed_register=altered)

    def test_blocker_06_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-06"]
        self.check_rejected(changed_register=altered)

    def test_blocker_07_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-07"]
        self.check_rejected(changed_register=altered)

    def test_blocker_08_cannot_be_dropped(self):
        altered = copy.deepcopy(self.register)
        altered["gate_policy"]["blocking_items"] = [b for b in altered["gate_policy"]["blocking_items"] if b["id"] != "G20-08"]
        self.check_rejected(changed_register=altered)

if __name__ == "__main__":
    unittest.main()
