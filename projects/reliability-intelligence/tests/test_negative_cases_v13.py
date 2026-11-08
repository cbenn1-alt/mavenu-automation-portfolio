"""V13 regression tests: every committed impossible/null/range fixture exercised.

All mutations operate on deep copies of fictional repository data.
No real industrial or customer acceptance is implied.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import verify_v13 as v13


class V13NegativeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionary = v13.verify_v11.read_json(v13.verify_v11.DICTIONARY_PATH)
        cls.dictionary_index = v13.verify_v11.validate_dictionary(cls.dictionary)
        cls.contract = v13.verify_v11.read_json(v13.verify_v12.CONTRACT_PATH)
        cls.groups = v13.verify_v12.validate_contract(cls.contract, cls.dictionary)
        cls.sources = v13.verify_v11.load_sources()
        cls.corpus = v13.read_corpus()
        cls.inventory = v13.validate_corpus(cls.corpus, cls.groups)

    def _negative(self, name: str):
        item = next(x for x in self.corpus["negative_cases"] if x["case_id"] == name)
        altered = v13._mutate(self.sources, self.groups, item)
        with self.assertRaisesRegex(v13.V13NegativeCaseError, "^" +
                                    item["expected_error"] + "$"):
            v13.validate_semantic_bounds(self.groups, self.dictionary_index, altered)

    def _positive(self, name: str):
        item = next(x for x in self.corpus["valid_boundary_controls"] if x["case_id"] == name)
        altered = v13._mutate(self.sources, self.groups, item)
        report = v13.validate_semantic_bounds(self.groups, self.dictionary_index, altered)
        self.assertTrue(report["semantic_checks_passed"])

    def test_01_v13_objective_and_proof(self):
        self.assertEqual(self.corpus["objective"], "Reject impossible, null, and out-of-range values")
        self.assertEqual(self.corpus["required_proof"], "Negative-case fixtures")

    def test_02_exact_negative_and_boundary_counts(self):
        self.assertEqual(self.inventory["negative_count"], 29)
        self.assertEqual(self.inventory["positive_boundary_count"], 7)

    def test_03_negative_categories(self):
        self.assertEqual(self.inventory["category_counts"],
                         {"null": 8, "out_of_range": 5, "nonfinite": 3, "impossible": 13})

    def test_04_original_synthetic_data_is_valid(self):
        result = v13.validate_semantic_bounds(
            self.groups, self.dictionary_index, self.sources)
        self.assertEqual(result["records_checked"], 34)
        self.assertEqual(result["declared_fields_checked"], 21)

    def test_05_v10_source_freeze_still_intact(self):
        freeze = v13.verify_v10.verify_freeze(
            v13.verify_v10.read_json(v13.verify_v10.BASELINE))
        self.assertEqual(freeze["frozen_files_verified"], 18)

    def test_06_upstream_v10_promotion_not_approved(self):
        decision = v13.verify_v11.read_json(v13.verify_v11.DECISION_PATH)
        self.assertFalse(decision["formal_phase_promotion_authorized"])
        self.assertEqual(decision["recommended_promotion_decision"], "BLOCKED")

    def test_07_v11_data_dictionary_not_approved(self):
        self.assertEqual(self.dictionary["dictionary_status"],
                         "DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED")
        self.assertFalse(self.dictionary["product_owner_approved"])

    def test_08_v12_schema_contract_not_approved(self):
        self.assertFalse(self.contract["schema_owner_approved"])
        self.assertFalse(self.contract["customer_data_permitted"])

    def test_09_v13_corpus_governance_not_approved(self):
        self.assertFalse(self.corpus["governance"]["formal_phase_02_approved"])
        self.assertFalse(self.corpus["governance"]["customer_data_authorized"])
        self.assertIsNone(self.corpus["governance"]["reviewer_signature"])

    def test_10_draft_rejects_fabricated_signoff(self):
        altered = copy.deepcopy(self.corpus)
        altered["governance"]["reviewer_signature"] = "fictional approval"
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_11_corpus_rejects_missing_negative_case(self):
        altered = copy.deepcopy(self.corpus)
        altered["negative_cases"].pop()
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_12_corpus_rejects_duplicate_case_id(self):
        altered = copy.deepcopy(self.corpus)
        altered["negative_cases"][1]["case_id"] = altered["negative_cases"][0]["case_id"]
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_13_corpus_rejects_wrong_error_expectation(self):
        altered = copy.deepcopy(self.corpus)
        altered["negative_cases"][0]["expected_error"] = "accepted_anyway"
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_14_corpus_rejects_unknown_target_field(self):
        altered = copy.deepcopy(self.corpus)
        altered["negative_cases"][0]["target"]["field"] = "customer_email"
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_15_corpus_rejects_unknown_target_row(self):
        altered = copy.deepcopy(self.corpus)
        altered["negative_cases"][0]["target"]["row_index"] = 999
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_16_corpus_rejects_unsupported_special_value(self):
        altered = copy.deepcopy(self.corpus)
        item = next(x for x in altered["negative_cases"] if x["case_id"] == "NONFINITE-NAN-COST")
        item["mutation"]["value"] = "exfiltrate"
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_17_corpus_rejects_broadened_range_boundary(self):
        altered = copy.deepcopy(self.corpus)
        item = next(x for x in altered["valid_boundary_controls"] if x["case_id"] == "BOUNDARY-MAX-DOWNTIME")
        item["value"] = 300
        with self.assertRaises(v13.V13NegativeCaseError):
            v13.validate_corpus(altered, self.groups)

    def test_18_every_mutation_is_non_destructive(self):
        original = json.dumps(self.sources, sort_keys=True)
        report = v13.exercise_cases(
            self.corpus, self.groups, self.dictionary_index, self.sources)
        self.assertEqual(json.dumps(self.sources, sort_keys=True), original)
        self.assertFalse(report["original_fixture_files_modified"])

    def test_19_complete_case_execution_has_fixed_outcomes(self):
        report = v13.exercise_cases(
            self.corpus, self.groups, self.dictionary_index, self.sources)
        self.assertEqual(report["negative_cases_rejected"], 29)
        self.assertEqual(report["valid_boundary_cases_accepted"], 7)
        self.assertTrue(all(x["result"] == "REJECTED_AS_EXPECTED" for x in report["negative_cases"]))

    def test_20_complete_case_execution_is_deterministic(self):
        first = v13.exercise_cases(self.corpus, self.groups, self.dictionary_index, self.sources)
        second = v13.exercise_cases(self.corpus, self.groups, self.dictionary_index, self.sources)
        self.assertEqual(first, second)

    def test_21_reject_null_case_id(self):
        self._negative("NULL-CASE-ID")

    def test_22_reject_null_event_utc(self):
        self._negative("NULL-EVENT-UTC")

    def test_23_reject_null_downtime(self):
        self._negative("NULL-DOWNTIME")

    def test_24_reject_null_repair_cost(self):
        self._negative("NULL-REPAIR-COST")

    def test_25_reject_null_evidence_list(self):
        self._negative("NULL-EVIDENCE-LIST")

    def test_26_reject_null_asset_origin(self):
        self._negative("NULL-ASSET-ORIGIN")

    def test_27_reject_null_review_action(self):
        self._negative("NULL-REVIEW-ACTION")

    def test_28_reject_null_seeded_label(self):
        self._negative("NULL-SEEDED-LABEL")

    def test_29_reject_range_negative_downtime(self):
        self._negative("RANGE-NEGATIVE-DOWNTIME")

    def test_30_reject_range_excess_downtime(self):
        self._negative("RANGE-EXCESS-DOWNTIME")

    def test_31_reject_range_negative_cost(self):
        self._negative("RANGE-NEGATIVE-COST")

    def test_32_reject_range_excess_cost(self):
        self._negative("RANGE-EXCESS-COST")

    def test_33_reject_nonfinite_nan_cost(self):
        self._negative("NONFINITE-NAN-COST")

    def test_34_reject_nonfinite_inf_downtime(self):
        self._negative("NONFINITE-INF-DOWNTIME")

    def test_35_reject_nonfinite_minus_inf_cost(self):
        self._negative("NONFINITE-MINUS-INF-COST")

    def test_36_reject_date_nonleap_feb29(self):
        self._negative("DATE-NONLEAP-FEB29")

    def test_37_reject_date_feb30(self):
        self._negative("DATE-FEB30")

    def test_38_reject_date_month13(self):
        self._negative("DATE-MONTH13")

    def test_39_reject_date_hour25(self):
        self._negative("DATE-HOUR25")

    def test_40_reject_duplicate_asset_id(self):
        self._negative("DUPLICATE-ASSET-ID")

    def test_41_reject_duplicate_case_id(self):
        self._negative("DUPLICATE-CASE-ID")

    def test_42_reject_duplicate_work_order(self):
        self._negative("DUPLICATE-WORK-ORDER")

    def test_43_reject_unknown_case_asset(self):
        self._negative("UNKNOWN-CASE-ASSET")

    def test_44_reject_unknown_script_case(self):
        self._negative("UNKNOWN-SCRIPT-CASE")

    def test_45_reject_unknown_label_case(self):
        self._negative("UNKNOWN-LABEL-CASE")

    def test_46_reject_duplicate_script_case(self):
        self._negative("DUPLICATE-SCRIPT-CASE")

    def test_47_reject_duplicate_label_case(self):
        self._negative("DUPLICATE-LABEL-CASE")

    def test_48_reject_duplicate_evidence_ref(self):
        self._negative("DUPLICATE-EVIDENCE-REF")

    def test_49_reject_too_many_evidence_refs(self):
        self._negative("TOO-MANY-EVIDENCE-REFS")

    def test_50_accept_boundary_zero_downtime(self):
        self._positive("BOUNDARY-ZERO-DOWNTIME")

    def test_51_accept_boundary_max_downtime(self):
        self._positive("BOUNDARY-MAX-DOWNTIME")

    def test_52_accept_boundary_zero_cost(self):
        self._positive("BOUNDARY-ZERO-COST")

    def test_53_accept_boundary_max_cost(self):
        self._positive("BOUNDARY-MAX-COST")

    def test_54_accept_valid_leap_day(self):
        self._positive("VALID-LEAP-DAY")

    def test_55_accept_empty_evidence_allowed(self):
        self._positive("EMPTY-EVIDENCE-ALLOWED")

    def test_56_accept_three_unique_refs_allowed(self):
        self._positive("THREE-UNIQUE-REFS-ALLOWED")

if __name__ == "__main__":
    unittest.main()
