"""V17 deterministic golden/reference calculation regression.

Reference values were precomputed and recorded as authored synthetic
expected-output fixtures. They are not approved industrial domain labels,
customer actuals, financial savings, or independently adjudicated truth.
"""

from __future__ import annotations

import copy
from decimal import Decimal
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import calculations_v17 as calc
import ingest_v14
import lineage_v16
import verify_v17 as verifier


class V17GoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = calc.load_reference()
        cls.policy = lineage_v16.load_policy()
        cls.docs, cls.hashes = lineage_v16.load_source_documents()
        cls.trace = lineage_v16.reconstruct_trace(cls.policy, cls.docs, cls.hashes)
        cls.outputs = calc.compute(cls.trace)
        cls.comparison = calc.compare(cls.outputs, cls.reference)

    def test_01_exact_architecture_objective(self):
        self.assertEqual(self.reference["objective"],
                         "Define golden/reference calculations")
        self.assertEqual(self.reference["required_proof"], "Expected-output fixtures")

    def test_02_reference_is_authored_not_domain_truth(self):
        self.assertEqual(self.reference["reference_status"],
                         calc.REFERENCE_STATUS)
        self.assertFalse(self.reference["approval"]["independent_domain_ground_truth"])
        self.assertFalse(self.reference["approval"]["human_reference_approval"])

    def test_03_formal_promotion_and_customer_permission_are_not_claimed(self):
        for field in ("customer_data_authorized", "v10_formal_phase_promotion",
                      "v11_source_dictionary_approved", "v12_schema_approved",
                      "v17_release_approved"):
            self.assertFalse(self.reference["approval"][field])
        self.assertIsNone(self.reference["approval"]["named_owner"])
        self.assertIsNone(self.reference["approval"]["approval_signature"])

    def test_04_original_fixture_set_is_pinned(self):
        self.assertEqual(self.reference["fixture_set_id"],
                         "SYN-RI-V5-20261107-A")
        self.assertEqual(self.reference["source_baseline_commit"],
                         "704123eca45628bf504594af39a66036cc0451c5")

    def test_05_exact_reference_schema(self):
        calc.validate_reference(self.reference)
        self.assertEqual(set(self.outputs),
                         {"summary", "asset_aggregates", "case_history"})

    def test_06_all_reference_outputs_match(self):
        self.assertEqual(self.comparison["result"],
                         "MATCHED_AUTHORED_EXPECTATIONS")
        self.assertEqual(self.comparison["total_synthetic_reference_values_verified"], 25)
        self.assertFalse(self.comparison["independent_domain_validation"])

    def test_07_original_inputs_remain_unchanged(self):
        initial = ingest_v14.sha256(self.docs)
        calc.compute(self.trace)
        self.assertEqual(ingest_v14.sha256(self.docs), initial)

    def test_08_deterministic_recomputation(self):
        self.assertEqual(calc.compute(copy.deepcopy(self.trace)),
                         self.outputs)

    def test_09_exact_decimal_sum_no_binary_float(self):
        self.assertEqual(calc.as_decimal("0.1") + calc.as_decimal("0.2"),
                         Decimal("0.3"))
        self.assertEqual(calc.plain_decimal(Decimal("45.5000")), "45.5")

    def test_10_exact_cents_format(self):
        self.assertEqual(calc.money_cents(Decimal("12735")), "12735.00")
        self.assertEqual(calc.money_cents(Decimal("0.01")), "0.01")

    def test_11_fractional_cent_rejected(self):
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "aggregate_money_precision_loss"):
            calc.money_cents(Decimal("0.001"))

    def test_12_nonfinite_decimal_rejected(self):
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "nonfinite_decimal_input"):
            calc.as_decimal("NaN")

    def test_13_non_string_numeric_input_rejected(self):
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "noncanonical_decimal_input"):
            calc.as_decimal(1.5)

    def test_14_total_output_counts(self):
        self.assertEqual(self.comparison["summary_metrics"], 7)
        self.assertEqual(self.comparison["asset_aggregates_checked"], 6)
        self.assertEqual(self.comparison["case_history_rows_checked"], 12)

    def test_15_case_history_is_sorted_by_id_in_output(self):
        ids = [r["case_id"] for r in self.outputs["case_history"]]
        self.assertEqual(ids, sorted(ids))

    def test_16_asset_aggregates_are_sorted(self):
        ids = [r["asset_id"] for r in self.outputs["asset_aggregates"]]
        self.assertEqual(ids, sorted(ids))

    def test_17_first_asset_event_has_zero_prior(self):
        r = next(r for r in self.outputs["case_history"]
                 if r["case_id"] == "SYN-CASE-001")
        self.assertEqual(r["prior_asset_case_count"], 0)
        self.assertEqual(r["asset_occurrence_index"], 1)

    def test_18_second_asset_event_has_one_prior(self):
        r = next(r for r in self.outputs["case_history"]
                 if r["case_id"] == "SYN-CASE-007")
        self.assertEqual(r["prior_asset_case_count"], 1)
        self.assertEqual(r["asset_occurrence_index"], 2)

    def test_19_fictional_case_without_evidence_reference_not_authenticated(self):
        r = next(r for r in self.outputs["case_history"]
                 if r["case_id"] == "SYN-CASE-009")
        self.assertFalse(r["has_example_evidence_refs"])
        self.assertIn("NOT authenticated documents",
                      self.reference["calculation_contract"]["evidence_rule"])

    def test_20_reference_cannot_claim_approval(self):
        changed = copy.deepcopy(self.reference)
        changed["approval"]["v17_release_approved"] = True
        with self.assertRaises(calc.GoldenCalculationRejected):
            calc.validate_reference(changed)

    def test_21_reference_cannot_claim_domain_ground_truth(self):
        changed = copy.deepcopy(self.reference)
        changed["approval"]["independent_domain_ground_truth"] = True
        with self.assertRaises(calc.GoldenCalculationRejected):
            calc.validate_reference(changed)

    def test_22_reference_cannot_expand_to_customer_sources(self):
        changed = copy.deepcopy(self.reference)
        changed["source_files"].append("real-customer.csv")
        with self.assertRaises(calc.GoldenCalculationRejected):
            calc.validate_reference(changed)

    def test_23_reference_cannot_add_unsupported_metric(self):
        changed = copy.deepcopy(self.reference)
        changed["expected_summary"]["predicted_savings_usd"] = "999999"
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "expected_summary_shape"):
            calc.validate_reference(changed)

    def test_24_reference_cannot_drop_asset(self):
        changed = copy.deepcopy(self.reference)
        changed["expected_asset_aggregates"].pop()
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "expected_asset_inventory"):
            calc.validate_reference(changed)

    def test_25_reference_cannot_duplicate_case(self):
        changed = copy.deepcopy(self.reference)
        changed["expected_case_history"][1]["case_id"] = "SYN-CASE-001"
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "duplicate_expected_id"):
            calc.validate_reference(changed)

    def test_26_golden_summary_tamper_fails_closed(self):
        changed = copy.deepcopy(self.reference)
        changed["expected_summary"]["total_downtime_hours"] = "999"
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "golden_summary_mismatch"):
            calc.compare(self.outputs, changed)

    def test_27_golden_asset_cost_tamper_fails_closed(self):
        changed = copy.deepcopy(self.reference)
        changed["expected_asset_aggregates"][0]["total_repair_cost_usd"] = "1.00"
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "golden_asset_mismatch"):
            calc.compare(self.outputs, changed)

    def test_28_golden_case_history_tamper_fails_closed(self):
        changed = copy.deepcopy(self.reference)
        changed["expected_case_history"][0]["asset_occurrence_index"] = 3
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "golden_history_mismatch"):
            calc.compare(self.outputs, changed)

    def test_29_unverified_trace_origin_not_accepted(self):
        changed = copy.deepcopy(self.trace)
        changed["customer_data_ingested"] = True
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "non_synthetic_trace_rejected"):
            calc.compute(changed)

    def test_30_tampered_normalized_value_digest_rejected(self):
        changed = copy.deepcopy(self.trace)
        changed["record_traces"][0]["normalized_record_sha256"] = "0" * 64
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "normalized_record_checksum_invalid"):
            calc.compute(changed)

    def test_31_duplicate_asset_keys_rejected(self):
        changed = copy.deepcopy(self.trace)
        entries = [r for r in changed["record_traces"]
                   if r["origin"]["source_dataset"] == "asset_records"]
        entries[1]["normalized_record"]["asset_id"] = entries[0]["normalized_record"]["asset_id"]
        entries[1]["normalized_record_sha256"] = lineage_v16.sha256_object(
            entries[1]["normalized_record"])
        with self.assertRaisesRegex(calc.GoldenCalculationRejected,
                                    "duplicate_asset_keys"):
            calc.compute(changed)

    def test_32_reference_total_downtime_does_not_infer_plant_downtime(self):
        self.assertIn("not measured plant downtime",
                      self.reference["calculation_contract"]["duration_rule"])
        self.assertEqual(self.outputs["summary"]["total_downtime_hours"], "45.5")

    def test_33_reference_total_cost_is_not_a_savings_claim(self):
        self.assertIn("not actual GL accounting",
                      self.reference["calculation_contract"]["money_rule"])
        self.assertEqual(self.outputs["summary"]["total_repair_cost_usd"], "12735.00")

    def test_34_verification_report_has_no_real_customer_claim(self):
        result = verifier.generate()
        self.assertEqual(result["result"],
                         "authored_synthetic_reference_outputs_matched_approval_pending")
        self.assertFalse(result["independent_domain_ground_truth"])
        self.assertFalse(result["real_customer_data_used"])
        self.assertFalse(result["operational_outcomes_measured"])
        self.assertEqual(result["v10_frozen_files_verified"], 18)

    def test_summary_case_count(self):
        self.assertEqual(self.outputs["summary"]["case_count"],
                         self.reference["expected_summary"]["case_count"])

    def test_summary_asset_count(self):
        self.assertEqual(self.outputs["summary"]["asset_count"],
                         self.reference["expected_summary"]["asset_count"])

    def test_summary_total_downtime_hours(self):
        self.assertEqual(self.outputs["summary"]["total_downtime_hours"],
                         self.reference["expected_summary"]["total_downtime_hours"])

    def test_summary_total_repair_cost_usd(self):
        self.assertEqual(self.outputs["summary"]["total_repair_cost_usd"],
                         self.reference["expected_summary"]["total_repair_cost_usd"])

    def test_summary_median_case_downtime_hours(self):
        self.assertEqual(self.outputs["summary"]["median_case_downtime_hours"],
                         self.reference["expected_summary"]["median_case_downtime_hours"])

    def test_summary_missing_evidence_case_count(self):
        self.assertEqual(self.outputs["summary"]["missing_evidence_case_count"],
                         self.reference["expected_summary"]["missing_evidence_case_count"])

    def test_summary_repeat_asset_event_count(self):
        self.assertEqual(self.outputs["summary"]["repeat_asset_event_count"],
                         self.reference["expected_summary"]["repeat_asset_event_count"])

    def test_asset_syn_asset_001(self):
        actual = next(x for x in self.outputs["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-001")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-001")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_002(self):
        actual = next(x for x in self.outputs["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-002")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-002")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_003(self):
        actual = next(x for x in self.outputs["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-003")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-003")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_004(self):
        actual = next(x for x in self.outputs["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-004")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-004")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_005(self):
        actual = next(x for x in self.outputs["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-005")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-005")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_006(self):
        actual = next(x for x in self.outputs["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-006")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-006")
        self.assertEqual(actual, expected)

    def test_case_syn_case_001(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-001")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-001")
        self.assertEqual(actual, expected)

    def test_case_syn_case_002(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-002")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-002")
        self.assertEqual(actual, expected)

    def test_case_syn_case_003(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-003")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-003")
        self.assertEqual(actual, expected)

    def test_case_syn_case_004(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-004")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-004")
        self.assertEqual(actual, expected)

    def test_case_syn_case_005(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-005")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-005")
        self.assertEqual(actual, expected)

    def test_case_syn_case_006(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-006")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-006")
        self.assertEqual(actual, expected)

    def test_case_syn_case_007(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-007")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-007")
        self.assertEqual(actual, expected)

    def test_case_syn_case_008(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-008")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-008")
        self.assertEqual(actual, expected)

    def test_case_syn_case_009(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-009")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-009")
        self.assertEqual(actual, expected)

    def test_case_syn_case_010(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-010")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-010")
        self.assertEqual(actual, expected)

    def test_case_syn_case_011(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-011")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-011")
        self.assertEqual(actual, expected)

    def test_case_syn_case_012(self):
        actual = next(x for x in self.outputs["case_history"] if x["case_id"] == "SYN-CASE-012")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-012")
        self.assertEqual(actual, expected)

if __name__ == "__main__":
    unittest.main()
