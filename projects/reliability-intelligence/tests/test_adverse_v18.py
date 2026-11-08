"""V18 synthetic adverse-input regression suite with one test per fixture.

A fixed synthetic clock (not wall time) controls staleness tests. All
mutations are deep copies; no customer source or industrial system is used.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import adverse_v18 as adverse
import ingest_v14
import verify_v11
import verify_v12
import verify_v18 as verifier


class V18AdverseInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = adverse.read_corpus()
        cls.inventory = adverse.validate_corpus(cls.corpus)
        cls.dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
        cls.contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
        cls.sources = verify_v11.load_sources()
        cls.digest = ingest_v14.sha256(cls.sources)
        cls.by_id = {item["id"]: item for item in cls.corpus["adverse_cases"]}
        cls.controls = {item["id"]: item for item in cls.corpus["positive_controls"]}

    def adverse_case(self, name):
        item = self.by_id[name]
        with self.assertRaisesRegex(adverse.AdverseRejected,
                                    "^" + item["expected_error"] + "$"):
            altered = adverse.apply_case(item, self.sources)
            adverse.validate_snapshot(altered, self.dictionary, self.contract)
        self.assertEqual(ingest_v14.sha256(self.sources), self.digest)

    def control_case(self, name):
        item = self.controls[name]
        altered = adverse.apply_case(item, self.sources)
        result = adverse.validate_snapshot(altered, self.dictionary, self.contract)
        self.assertEqual(result["records_checked"], 34)
        self.assertEqual(result["timestamps_checked"], 12)
        self.assertEqual(ingest_v14.sha256(self.sources), self.digest)

    def test_01_objective_and_proof(self):
        self.assertEqual(self.corpus["objective"],
                         "Test missing, stale and malformed inputs")
        self.assertEqual(self.corpus["required_proof"],
                         "Adverse-case regression suite")

    def test_02_inventory_counts(self):
        self.assertEqual(self.inventory["negative_count"], 44)
        self.assertEqual(self.inventory["positive_count"], 5)

    def test_03_category_inventory(self):
        self.assertEqual(self.inventory["category_counts"],
                         {"missing": 16, "stale": 7, "malformed": 21})

    def test_04_fixed_synthetic_clock(self):
        self.assertEqual(adverse.FIXED_CLOCK, "2026-02-05T00:00:00Z")
        self.assertEqual(adverse.AGE_DAYS, 45)
        self.assertEqual(adverse.FUTURE_HOURS, 24)
        self.assertFalse(self.corpus["freshness_policy"]["actual_current_time_used"])

    def test_05_upstream_source_is_valid(self):
        result = adverse.validate_snapshot(self.sources,
                                          self.dictionary, self.contract)
        self.assertEqual(result["records_checked"], 34)
        self.assertEqual(result["timestamps_checked"], 12)
        self.assertEqual(result["source_count"], 3)

    def test_06_all_scenarios_replay(self):
        result = adverse.exercise(self.corpus, self.sources,
                                  self.dictionary, self.contract)
        self.assertEqual(result["negative_cases"], 44)
        self.assertEqual(result["positive_controls"], 5)
        self.assertTrue(result["original_source_unchanged"])
        self.assertTrue(result["in_memory_only"])

    def test_07_replay_deterministic(self):
        a = adverse.exercise(self.corpus, self.sources, self.dictionary, self.contract)
        b = adverse.exercise(self.corpus, self.sources, self.dictionary, self.contract)
        self.assertEqual(a, b)

    def test_08_original_source_unchanged(self):
        before = ingest_v14.sha256(self.sources)
        adverse.exercise(self.corpus, self.sources, self.dictionary, self.contract)
        self.assertEqual(before, ingest_v14.sha256(self.sources))

    def test_09_v10_freeze_unchanged(self):
        frozen = verifier.verify_v10.verify_freeze(
            verifier.verify_v10.read_json(verifier.verify_v10.BASELINE))
        self.assertEqual(frozen["frozen_files_verified"], 18)

    def test_10_v10_promotion_still_blocked(self):
        decision = verify_v11.read_json(verify_v11.DECISION_PATH)
        self.assertIs(decision["formal_phase_promotion_authorized"], False)
        self.assertEqual(decision["recommended_promotion_decision"], "BLOCKED")

    def test_11_no_false_customer_approval(self):
        for key in ("formal_phase_02_authorized", "v11_dictionary_approved",
                    "v12_schema_approved", "v18_domain_owner_approved",
                    "customer_data_authorized", "ot_or_cmms_write_permitted"):
            self.assertIs(self.corpus["approval"][key], False)
        self.assertIsNone(self.corpus["approval"]["signature"])

    def test_12_cannot_claim_owner_approval(self):
        bad = copy.deepcopy(self.corpus)
        bad["approval"]["v18_domain_owner_approved"] = True
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_13_cannot_claim_real_time_clock(self):
        bad = copy.deepcopy(self.corpus)
        bad["freshness_policy"]["actual_current_time_used"] = True
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_14_cannot_widen_age_window(self):
        bad = copy.deepcopy(self.corpus)
        bad["freshness_policy"]["max_age_days"] = 999
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_15_cannot_widen_future_skew(self):
        bad = copy.deepcopy(self.corpus)
        bad["freshness_policy"]["max_future_skew_hours"] = 100
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_16_cannot_remove_negative_case(self):
        bad = copy.deepcopy(self.corpus)
        bad["adverse_cases"].pop()
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_17_cannot_duplicate_negative_case_id(self):
        bad = copy.deepcopy(self.corpus)
        bad["adverse_cases"][1]["id"] = bad["adverse_cases"][0]["id"]
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_18_cannot_relabel_expected_error(self):
        bad = copy.deepcopy(self.corpus)
        bad["adverse_cases"][0]["expected_error"] = "ignored"
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_19_cannot_add_unapproved_source(self):
        bad = copy.deepcopy(self.corpus)
        bad["allowed_sources"].append("fixtures/real_customer.csv")
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_20_cannot_add_unknown_mutation_operation(self):
        bad = copy.deepcopy(self.corpus)
        bad["adverse_cases"][0]["operation"] = "send_to_cmms"
        with self.assertRaises(adverse.AdverseRejected):
            adverse.validate_corpus(bad)

    def test_21_freshness_policy_is_inclusive_at_boundaries(self):
        for name in ("OK-EXACT-STALE-BOUNDARY", "OK-EXACT-FUTURE-SKEW"):
            with self.subTest(name=name):
                self.control_case(name)

    def test_22_invalid_utf8_is_distinguished_from_json_syntax(self):
        with self.assertRaisesRegex(adverse.AdverseRejected,
                                    "^invalid_utf8_source$"):
            adverse.parse_source_bytes(adverse.RAW_MARKERS["invalid_utf8"])

    def test_23_duplicate_json_member_is_rejected(self):
        with self.assertRaisesRegex(adverse.AdverseRejected,
                                    "^duplicate_json_member$"):
            adverse.parse_source_bytes(adverse.RAW_MARKERS["duplicate_member"])

    def test_24_nonfinite_json_is_rejected(self):
        with self.assertRaisesRegex(adverse.AdverseRejected,
                                    "^invalid_nonfinite_json$"):
            adverse.parse_source_bytes(adverse.RAW_MARKERS["nonfinite_json"])

    def test_25_generated_report_excludes_customer_authority(self):
        output = verifier.generate()
        self.assertEqual(output["adverse_results"]["negative_cases"], 44)
        self.assertEqual(output["adverse_results"]["positive_controls"], 5)
        self.assertFalse(output["customer_data_used"])
        self.assertFalse(output["v18_owner_approved"])
        self.assertFalse(output["reference_freshness_customer_approved"])


def _negative(name):
    def check(self):
        self.adverse_case(name)
    return check


def _positive(name):
    def check(self):
        self.control_case(name)
    return check


_reference = adverse.read_corpus()
for _case in _reference["adverse_cases"]:
    _name = "test_adverse_" + _case["id"].lower().replace("-", "_")
    setattr(V18AdverseInputTests, _name, _negative(_case["id"]))
for _case in _reference["positive_controls"]:
    _name = "test_positive_" + _case["id"].lower().replace("-", "_")
    setattr(V18AdverseInputTests, _name, _positive(_case["id"]))


if __name__ == "__main__":
    unittest.main()
