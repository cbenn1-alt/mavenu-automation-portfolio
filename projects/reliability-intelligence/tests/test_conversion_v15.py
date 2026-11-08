"""V15 unit tests: conversion reference test cases and fail-closed governance.

The 27 accepted and 24 rejected cases are expanded into stable individual
unittest methods. All source values are fabricated, never customer data.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import normalize_v15 as norm
import verify_v15 as v15


class V15ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = v15.reference()
        cls.counts = v15.validate_reference(cls.ref)

    def test_01_exact_architecture_objective_and_proof(self):
        self.assertEqual(self.ref["objective"], "Normalize timestamps, units and locales")
        self.assertEqual(self.ref["required_proof"], "Conversion reference tests")

    def test_02_exact_positive_negative_counts(self):
        self.assertEqual(self.ref["expected_accepted_count"], 27)
        self.assertEqual(self.ref["expected_rejected_count"], 24)
        self.assertEqual(len(self.ref["accepted_reference_cases"]), 27)
        self.assertEqual(len(self.ref["rejected_reference_cases"]), 24)

    def test_03_conversion_types_are_covered(self):
        self.assertEqual(self.counts, {"timestamp": 18, "duration": 16, "money": 17})

    def test_04_reference_is_explicitly_unsigned(self):
        self.assertEqual(self.ref["fixture_status"], "SYNTHETIC_REFERENCE_UNAPPROVED")
        for key in ("formal_phase_02_authorized", "source_dictionary_approved",
                    "customer_data_authorized", "owner_signoff", "production_authorized"):
            self.assertIs(self.ref["approval"][key], False)
        self.assertIsNone(self.ref["approval"]["signature"])

    def test_05_source_snapshot_remains_frozen(self):
        frozen = v15.verify_v10.verify_freeze(
            v15.verify_v10.read_json(v15.verify_v10.BASELINE))
        self.assertEqual(frozen["frozen_files_verified"], 18)

    def test_06_prior_human_promotion_is_not_claimed(self):
        decision = v15.verify_v11.read_json(v15.verify_v11.DECISION_PATH)
        self.assertEqual(decision["recommended_promotion_decision"], "BLOCKED")
        self.assertIs(decision["formal_phase_promotion_authorized"], False)

    def test_07_original_twelve_records_normalize_without_mutation(self):
        sources = v15.verify_v11.load_sources()
        prior = v15.ingest_v14.sha256(sources)
        result = v15.unchanged_fixture_conversion(sources)
        self.assertEqual(result["case_count"], 12)
        self.assertEqual(result["source_sha256_before_and_after"], prior)
        self.assertEqual(v15.ingest_v14.sha256(sources), prior)

    def test_08_canonical_replay_is_idempotent(self):
        results = v15.execute_cases(self.ref)
        self.assertTrue(results["canonical_replay_idempotent"])
        self.assertEqual(results["accepted"], 27)
        self.assertEqual(results["rejected"], 24)

    def test_09_equivalent_iso_offsets_share_utc_timestamp(self):
        self.assertEqual(
            norm.normalize_timestamp("2026-01-05T10:00:00Z", "en-US"),
            norm.normalize_timestamp("2026-01-05T05:00:00-05:00", "en-US"))
        self.assertEqual(
            norm.normalize_timestamp("2026-01-05T12:00:00+02:00", "de-DE"),
            norm.normalize_timestamp("2026-01-05T04:00:00-06:00", "en-GB"))

    def test_10_explicit_locale_dates_share_utc(self):
        a = norm.normalize_timestamp("01/05/2026 05:00:00", "en-US", "-05:00")
        b = norm.normalize_timestamp("05/01/2026 05:00:00", "en-GB", "-05:00")
        c = norm.normalize_timestamp("05.01.2026 05:00:00", "de-DE", "-05:00")
        d = norm.normalize_timestamp("05/01/2026 05:00:00", "fr-FR", "-05:00")
        self.assertEqual({a, b, c, d}, {"2026-01-05T10:00:00Z"})

    def test_11_usd_locale_decimal_equivalence(self):
        a = norm.normalize_money("1,234.50", "USD", "en-US")
        b = norm.normalize_money("1.234,50", "USD", "de-DE")
        c = norm.normalize_money("1 234,50", "USD", "fr-FR")
        self.assertEqual(a, b)
        self.assertEqual(b, c)

    def test_12_duration_unit_equivalence(self):
        self.assertEqual(norm.normalize_duration("2.5", "hours", "en-US"),
                         norm.normalize_duration("150", "minutes", "en-US"))
        self.assertEqual(norm.normalize_duration("9000", "seconds", "en-US"), "2.5")

    def test_13_money_never_silently_rounds(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^money_precision_loss$"):
            norm.normalize_money("0.001", "USD", "en-US")

    def test_14_duration_never_silently_rounds(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^duration_precision_loss$"):
            norm.normalize_duration("1", "seconds", "en-US")

    def test_15_currency_exchange_not_supported(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^unsupported_currency$"):
            norm.normalize_money("100.00", "EUR", "en-US")

    def test_16_naive_timestamp_not_assumed_utc(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^missing_timezone_offset$"):
            norm.normalize_timestamp("2026-01-05T10:00:00", "en-US")

    def test_17_inconsistent_timezone_double_specification_rejected(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^conflicting_timezone_offset$"):
            norm.normalize_timestamp("2026-01-05T10:00:00Z", "en-US", "-05:00")

    def test_18_python_boolean_not_accepted_as_duration(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^invalid_numeric_format$"):
            norm.normalize_duration(True, "hours", "en-US")

    def test_19_python_float_not_accepted_as_usd_source(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^invalid_numeric_format$"):
            norm.normalize_money(1.1, "USD", "en-US")

    def test_20_unsupported_conversion_kind_rejected(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^unsupported_conversion_kind$"):
            norm.convert_reference({"kind": "external_api", "value": "X", "locale": "en-US"})

    def test_21_unsupported_locale_rejected(self):
        with self.assertRaisesRegex(norm.NormalizationRejected, "^unsupported_locale$"):
            norm.normalize_duration("1", "hours", "xx-XX")

    def test_22_no_precision_loss_in_exact_money_boundary(self):
        self.assertEqual(norm.normalize_money("1000000", "USD", "en-US"),
                         "1000000.00")

    def test_23_no_precision_loss_in_duration_zero(self):
        self.assertEqual(norm.normalize_duration("0", "seconds", "en-US"), "0")

    def test_24_original_fixture_has_no_transformed_artifacts(self):
        result = v15.unchanged_fixture_conversion(v15.verify_v11.load_sources())
        for row in result["synthetic_rows"]:
            self.assertTrue(row["case_id"].startswith("SYN-CASE-"))
            self.assertTrue(row["occurred_at_utc"].endswith("Z"))
            self.assertRegex(row["repair_cost_usd"], r"^\d+\.\d{2}$")

    def test_25_distinct_reference_ids(self):
        cases = self.ref["accepted_reference_cases"] + self.ref["rejected_reference_cases"]
        self.assertEqual(len(cases), len({item["id"] for item in cases}))

    def test_26_reference_rejects_false_source_approval(self):
        bad = copy.deepcopy(self.ref)
        bad["approval"]["source_dictionary_approved"] = True
        with self.assertRaises(v15.ConversionEvidenceError):
            v15.validate_reference(bad)

    def test_27_reference_rejects_dropped_case(self):
        bad = copy.deepcopy(self.ref)
        bad["rejected_reference_cases"].pop()
        with self.assertRaises(v15.ConversionEvidenceError):
            v15.validate_reference(bad)

    def test_28_reference_rejects_changed_currency_policy(self):
        bad = copy.deepcopy(self.ref)
        bad["money_currency"] = "EUR"
        with self.assertRaises(v15.ConversionEvidenceError):
            v15.validate_reference(bad)

    def test_29_reference_rejects_changed_duration_range(self):
        bad = copy.deepcopy(self.ref)
        bad["conversion_policy"]["duration_range_hours"] = [0, 1000000]
        with self.assertRaises(v15.ConversionEvidenceError):
            v15.validate_reference(bad)

    def test_30_reference_rejects_fabricated_signoff(self):
        bad = copy.deepcopy(self.ref)
        bad["approval"]["signature"] = "Fake reviewer"
        with self.assertRaises(v15.ConversionEvidenceError):
            v15.validate_reference(bad)


def _test_accepted(ref: dict):
    def run(self):
        actual = norm.convert_reference(ref)
        self.assertEqual(actual, ref["expected"])
    return run


def _test_rejected(ref: dict):
    def run(self):
        with self.assertRaisesRegex(norm.NormalizationRejected,
                                    "^" + ref["error"] + "$"):
            norm.convert_reference(ref)
    return run


# Stable individual test method IDs; the existing V8 test inventory can verify
# all 51 reference cases remain discovered in the complete regression suite.
_reference = v15.reference()
for _item in _reference["accepted_reference_cases"]:
    setattr(V15ConversionTests, "test_accept_" + _item["id"].lower().replace("-", "_"),
            _test_accepted(_item))
for _item in _reference["rejected_reference_cases"]:
    setattr(V15ConversionTests, "test_reject_" + _item["id"].lower().replace("-", "_"),
            _test_rejected(_item))


if __name__ == "__main__":
    unittest.main()
