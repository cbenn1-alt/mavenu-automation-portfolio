"""V19 independent synthetic aggregate reconciliation and discrepancy tests.

The second method uses an in-memory SQLite database and integral seconds/
USD cents from fictional raw records. Comparison with V17's stored expected
outputs does not establish independent customer or plant domain truth.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

import reconcile_v19 as reconcile
import verify_v19 as verifier


class V19IndependentReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = reconcile.policy()
        cls.raw = reconcile.source()
        cls.reference = reconcile.expected()
        cls.computed = reconcile.compute_independent(cls.raw)
        cls.result = reconcile.compare(cls.computed, cls.reference)
        cls.scenarios = reconcile.exercise_scenarios(
            cls.config, cls.raw, cls.reference
        )
        cls.scenario_results = {case["id"]: case for case in
                                cls.scenarios["case_results"]}

    def test_01_architecture_objective_and_evidence(self):
        self.assertEqual(self.config["objective"],
                         "Reconcile aggregates and operational metrics")
        self.assertEqual(self.config["required_proof"],
                         "Independent computation results")

    def test_02_method_is_independent_sqlite_integer_arithmetic(self):
        self.assertEqual(self.config["compute_method"],
                         "independent_sqlite_in_memory_integer_seconds_and_usd_cents")
        self.assertIs(self.config["no_v17_calculator_dependency"], True)

    def test_03_no_direct_v17_calculator_import(self):
        module = (PROJECT / "scripts" / "reconcile_v19.py").read_text(encoding="utf-8")
        self.assertNotIn("import calculations_v17", module)
        self.assertNotIn("import lineage_v16", module)

    def test_04_source_is_fabricated_not_customer(self):
        self.assertEqual(self.raw["fixture_set_id"], reconcile.SOURCE_ID)
        self.assertIs(self.raw["synthetic_only"], True)
        self.assertEqual(self.raw["source_system"], "NONE")

    def test_05_correct_exact_reference_status(self):
        self.assertEqual(self.reference["reference_status"],
                         reconcile.REFERENCE_STATE)
        self.assertIs(self.reference["approval"]["independent_domain_ground_truth"],
                      False)

    def test_06_all_25_expected_units_reconciled(self):
        self.assertEqual(self.result["reconciled_output_units"], 25)
        self.assertEqual(self.result["discrepancies"], 0)
        self.assertEqual(self.result["summary_metrics_compared"], 7)
        self.assertEqual(self.result["asset_aggregates_compared"], 6)
        self.assertEqual(self.result["case_histories_compared"], 12)

    def test_07_exact_totals_and_median(self):
        summary = self.computed["summary"]
        self.assertEqual(summary["total_downtime_hours"], "45.5")
        self.assertEqual(summary["total_repair_cost_usd"], "12735.00")
        self.assertEqual(summary["median_case_downtime_hours"], "3")

    def test_08_source_counts(self):
        self.assertEqual(self.computed["summary"]["asset_count"], 6)
        self.assertEqual(self.computed["summary"]["case_count"], 12)
        self.assertEqual(len(self.computed["asset_aggregates"]), 6)
        self.assertEqual(len(self.computed["case_history"]), 12)

    def test_09_repeat_asset_and_evidence_reference_counts(self):
        self.assertEqual(self.computed["summary"]["repeat_asset_event_count"], 6)
        self.assertEqual(self.computed["summary"]["missing_evidence_case_count"], 1)

    def test_10_integer_second_conversion(self):
        self.assertEqual(reconcile._whole_units(2.5, 3600,
                         "invalid_duration_precision"), 9000)

    def test_11_exact_integer_cents(self):
        self.assertEqual(reconcile._whole_units(860, 100,
                         "invalid_money_precision"), 86000)

    def test_12_exact_money_format(self):
        self.assertEqual(reconcile._money(1273500), "12735.00")
        self.assertEqual(reconcile._money(0), "0.00")

    def test_13_exact_duration_format(self):
        self.assertEqual(reconcile._hours(163800), "45.5")
        self.assertEqual(reconcile._hours(3600), "1")
        self.assertEqual(reconcile._hours(0), "0")

    def test_14_no_float_cent_rounding(self):
        with self.assertRaisesRegex(reconcile.ReconciliationRejected,
                                    "^invalid_money_precision$"):
            reconcile._whole_units(860.001, 100, "invalid_money_precision")

    def test_15_no_fractional_seconds(self):
        with self.assertRaisesRegex(reconcile.ReconciliationRejected,
                                    "^invalid_duration_precision$"):
            reconcile._whole_units(1.0001, 3600, "invalid_duration_precision")

    def test_16_no_nonfinite_duration(self):
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile._whole_units(float("nan"), 3600, "invalid_duration_precision")

    def test_17_no_boolean_cost(self):
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile._whole_units(True, 100, "invalid_money_precision")

    def test_18_source_row_order_does_not_change_sqlite_results(self):
        copied = copy.deepcopy(self.raw)
        copied["records"].reverse()
        copied["assets"].reverse()
        self.assertEqual(reconcile.compute_independent(copied), self.computed)

    def test_19_original_source_never_mutated(self):
        initial = json.dumps(self.raw, sort_keys=True)
        reconcile.compute_independent(self.raw)
        reconcile.exercise_scenarios(self.config, self.raw, self.reference)
        self.assertEqual(json.dumps(self.raw, sort_keys=True), initial)

    def test_20_no_live_operational_denominators(self):
        self.assertEqual(self.config["allowed_denominators"],
                         ["synthetic case count", "synthetic asset count"])
        self.assertFalse(any(x in self.computed["summary"]
                             for x in self.config["excluded_business_metrics"]))

    def test_21_per_asset_counts_sum_to_12(self):
        self.assertEqual(sum(x["case_count"] for x in
                             self.computed["asset_aggregates"]), 12)

    def test_22_per_asset_money_sums_reconcile_to_total(self):
        self.assertEqual(sum((Decimal(x["total_repair_cost_usd"]) for
                              x in self.computed["asset_aggregates"]),
                             Decimal(0)), Decimal("12735.00"))

    def test_23_per_asset_durations_reconcile_to_total(self):
        self.assertEqual(sum((Decimal(x["total_downtime_hours"]) for
                              x in self.computed["asset_aggregates"]),
                             Decimal(0)), Decimal("45.5"))

    def test_24_all_16_negative_mismatch_cases_detected(self):
        self.assertEqual(self.scenarios["scenarios"], 16)
        self.assertEqual(self.scenarios["detected"], 16)
        self.assertTrue(self.scenarios["original_source_unchanged"])

    def test_25_negative_cases_are_deterministic(self):
        repeat = reconcile.exercise_scenarios(self.config,
                                               self.raw, self.reference)
        self.assertEqual(repeat, self.scenarios)

    def test_26_cannot_claim_customer_data_authorization(self):
        changed = copy.deepcopy(self.config)
        changed["approval"]["customer_data_authorized"] = True
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.validate_policy(changed)

    def test_27_cannot_claim_source_dictionary_approved(self):
        changed = copy.deepcopy(self.config)
        changed["approval"]["v11_dictionary_approved"] = True
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.validate_policy(changed)

    def test_28_cannot_fabricate_reviewer_signature(self):
        changed = copy.deepcopy(self.config)
        changed["approval"]["approval_signature"] = "synthetic signer"
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.validate_policy(changed)

    def test_29_cannot_claim_domain_reference_ground_truth(self):
        changed = copy.deepcopy(self.reference)
        changed["approval"]["independent_domain_ground_truth"] = True
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.compare(self.computed, changed)

    def test_30_cannot_drop_scenario(self):
        changed = copy.deepcopy(self.config)
        changed["adverse_comparisons"].pop()
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.validate_policy(changed)

    def test_31_cannot_claim_unsupported_sqlite_metric(self):
        changed = copy.deepcopy(self.config)
        changed["excluded_business_metrics"].remove("mtbf_hours")
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.validate_policy(changed)

    def test_32_cannot_change_source_file(self):
        changed = copy.deepcopy(self.config)
        changed["source_file"] = "customer-data.csv"
        with self.assertRaises(reconcile.ReconciliationRejected):
            reconcile.validate_policy(changed)

    def test_33_report_governance_and_source_integrity(self):
        report = verifier.generate()
        self.assertEqual(report["result"],
                         "independent_synthetic_computation_reconciled_signoff_pending")
        self.assertEqual(report["v10_frozen_paths_verified"], 18)
        self.assertEqual(report["reconciliation"]["discrepancies"], 0)
        self.assertEqual(report["adverse_comparisons"]["detected"], 16)
        self.assertFalse(report["customer_data_used"])
        self.assertFalse(report["v19_reconciliation_approved"])
        self.assertFalse(report["real_operational_metrics_claimed"])
        self.assertTrue(report["original_source_unchanged"])

    def test_34_case_count_cannot_expand_without_reference(self):
        changed = copy.deepcopy(self.raw)
        changed["records"].append(copy.deepcopy(changed["records"][0]))
        with self.assertRaisesRegex(reconcile.ReconciliationRejected,
                                    "case_inventory_invalid"):
            reconcile.compute_independent(changed)

    def test_35_raw_reference_is_not_savings_or_risk(self):
        self.assertIn("No actual CMMS",
                      self.config["limitations"][-1])
        self.assertNotIn("saved_cost_usd", self.computed["summary"])

    def test_36_no_production_database_path(self):
        self.assertEqual(self.config["compute_method"],
                         "independent_sqlite_in_memory_integer_seconds_and_usd_cents")

    def test_metric_case_count(self):
        self.assertEqual(self.computed["summary"]["case_count"],
                         self.reference["expected_summary"]["case_count"])

    def test_metric_asset_count(self):
        self.assertEqual(self.computed["summary"]["asset_count"],
                         self.reference["expected_summary"]["asset_count"])

    def test_metric_total_downtime_hours(self):
        self.assertEqual(self.computed["summary"]["total_downtime_hours"],
                         self.reference["expected_summary"]["total_downtime_hours"])

    def test_metric_total_repair_cost_usd(self):
        self.assertEqual(self.computed["summary"]["total_repair_cost_usd"],
                         self.reference["expected_summary"]["total_repair_cost_usd"])

    def test_metric_median_case_downtime_hours(self):
        self.assertEqual(self.computed["summary"]["median_case_downtime_hours"],
                         self.reference["expected_summary"]["median_case_downtime_hours"])

    def test_metric_missing_evidence_case_count(self):
        self.assertEqual(self.computed["summary"]["missing_evidence_case_count"],
                         self.reference["expected_summary"]["missing_evidence_case_count"])

    def test_metric_repeat_asset_event_count(self):
        self.assertEqual(self.computed["summary"]["repeat_asset_event_count"],
                         self.reference["expected_summary"]["repeat_asset_event_count"])

    def test_asset_syn_asset_001(self):
        actual = next(x for x in self.computed["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-001")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-001")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_002(self):
        actual = next(x for x in self.computed["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-002")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-002")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_003(self):
        actual = next(x for x in self.computed["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-003")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-003")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_004(self):
        actual = next(x for x in self.computed["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-004")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-004")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_005(self):
        actual = next(x for x in self.computed["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-005")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-005")
        self.assertEqual(actual, expected)

    def test_asset_syn_asset_006(self):
        actual = next(x for x in self.computed["asset_aggregates"] if x["asset_id"] == "SYN-ASSET-006")
        expected = next(x for x in self.reference["expected_asset_aggregates"] if x["asset_id"] == "SYN-ASSET-006")
        self.assertEqual(actual, expected)

    def test_case_syn_case_001(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-001")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-001")
        self.assertEqual(actual, expected)

    def test_case_syn_case_002(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-002")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-002")
        self.assertEqual(actual, expected)

    def test_case_syn_case_003(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-003")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-003")
        self.assertEqual(actual, expected)

    def test_case_syn_case_004(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-004")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-004")
        self.assertEqual(actual, expected)

    def test_case_syn_case_005(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-005")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-005")
        self.assertEqual(actual, expected)

    def test_case_syn_case_006(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-006")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-006")
        self.assertEqual(actual, expected)

    def test_case_syn_case_007(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-007")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-007")
        self.assertEqual(actual, expected)

    def test_case_syn_case_008(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-008")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-008")
        self.assertEqual(actual, expected)

    def test_case_syn_case_009(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-009")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-009")
        self.assertEqual(actual, expected)

    def test_case_syn_case_010(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-010")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-010")
        self.assertEqual(actual, expected)

    def test_case_syn_case_011(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-011")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-011")
        self.assertEqual(actual, expected)

    def test_case_syn_case_012(self):
        actual = next(x for x in self.computed["case_history"] if x["case_id"] == "SYN-CASE-012")
        expected = next(x for x in self.reference["expected_case_history"] if x["case_id"] == "SYN-CASE-012")
        self.assertEqual(actual, expected)

    def test_scenario_diff_downtime(self):
        self.assertEqual(self.scenario_results["DIFF-DOWNTIME"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-DOWNTIME"]["expected"], reconcile.ADVERSE_METHODS["DIFF-DOWNTIME"][1])

    def test_scenario_diff_cost(self):
        self.assertEqual(self.scenario_results["DIFF-COST"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-COST"]["expected"], reconcile.ADVERSE_METHODS["DIFF-COST"][1])

    def test_scenario_diff_evidence(self):
        self.assertEqual(self.scenario_results["DIFF-EVIDENCE"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-EVIDENCE"]["expected"], reconcile.ADVERSE_METHODS["DIFF-EVIDENCE"][1])

    def test_scenario_diff_assignment(self):
        self.assertEqual(self.scenario_results["DIFF-ASSIGNMENT"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-ASSIGNMENT"]["expected"], reconcile.ADVERSE_METHODS["DIFF-ASSIGNMENT"][1])

    def test_scenario_diff_history(self):
        self.assertEqual(self.scenario_results["DIFF-HISTORY"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-HISTORY"]["expected"], reconcile.ADVERSE_METHODS["DIFF-HISTORY"][1])

    def test_scenario_diff_offsetting_cost(self):
        self.assertEqual(self.scenario_results["DIFF-OFFSETTING-COST"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-OFFSETTING-COST"]["expected"], reconcile.ADVERSE_METHODS["DIFF-OFFSETTING-COST"][1])

    def test_scenario_diff_golden_summary(self):
        self.assertEqual(self.scenario_results["DIFF-GOLDEN-SUMMARY"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-GOLDEN-SUMMARY"]["expected"], reconcile.ADVERSE_METHODS["DIFF-GOLDEN-SUMMARY"][1])

    def test_scenario_diff_golden_asset(self):
        self.assertEqual(self.scenario_results["DIFF-GOLDEN-ASSET"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-GOLDEN-ASSET"]["expected"], reconcile.ADVERSE_METHODS["DIFF-GOLDEN-ASSET"][1])

    def test_scenario_diff_golden_history(self):
        self.assertEqual(self.scenario_results["DIFF-GOLDEN-HISTORY"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["DIFF-GOLDEN-HISTORY"]["expected"], reconcile.ADVERSE_METHODS["DIFF-GOLDEN-HISTORY"][1])

    def test_scenario_invalid_missing_case(self):
        self.assertEqual(self.scenario_results["INVALID-MISSING-CASE"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-MISSING-CASE"]["expected"], reconcile.ADVERSE_METHODS["INVALID-MISSING-CASE"][1])

    def test_scenario_invalid_duplicate_case(self):
        self.assertEqual(self.scenario_results["INVALID-DUPLICATE-CASE"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-DUPLICATE-CASE"]["expected"], reconcile.ADVERSE_METHODS["INVALID-DUPLICATE-CASE"][1])

    def test_scenario_invalid_unknown_asset(self):
        self.assertEqual(self.scenario_results["INVALID-UNKNOWN-ASSET"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-UNKNOWN-ASSET"]["expected"], reconcile.ADVERSE_METHODS["INVALID-UNKNOWN-ASSET"][1])

    def test_scenario_invalid_fraction_cent(self):
        self.assertEqual(self.scenario_results["INVALID-FRACTION-CENT"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-FRACTION-CENT"]["expected"], reconcile.ADVERSE_METHODS["INVALID-FRACTION-CENT"][1])

    def test_scenario_invalid_fraction_second(self):
        self.assertEqual(self.scenario_results["INVALID-FRACTION-SECOND"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-FRACTION-SECOND"]["expected"], reconcile.ADVERSE_METHODS["INVALID-FRACTION-SECOND"][1])

    def test_scenario_invalid_false_customer_origin(self):
        self.assertEqual(self.scenario_results["INVALID-FALSE-CUSTOMER-ORIGIN"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-FALSE-CUSTOMER-ORIGIN"]["expected"], reconcile.ADVERSE_METHODS["INVALID-FALSE-CUSTOMER-ORIGIN"][1])

    def test_scenario_invalid_row_field(self):
        self.assertEqual(self.scenario_results["INVALID-ROW-FIELD"]["result"], "DETECTED_AS_EXPECTED")
        self.assertEqual(self.scenario_results["INVALID-ROW-FIELD"]["expected"], reconcile.ADVERSE_METHODS["INVALID-ROW-FIELD"][1])

if __name__ == "__main__":
    unittest.main()
