"""V11 draft field dictionary: exhaustive synthetic schema and governance tests.

All checks are non-destructive. They explicitly do NOT constitute a signed
customer source dictionary or authorize blocked V10 -> Phase 02 promotion.
"""

import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
SPEC = importlib.util.spec_from_file_location("v11_field_check", PROJECT / "scripts" / "verify_v11.py")
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class V11FieldDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionary = check.read_json(check.DICTIONARY_PATH)
        cls.index = check.validate_dictionary(cls.dictionary)
        cls.sources = check.load_sources()
        cls.observed = check.validate_rows(cls.index, cls.sources)

    def test_dictionary_is_explicitly_unapproved(self):
        self.assertEqual(self.dictionary["dictionary_status"],
                         "DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED")
        self.assertFalse(self.dictionary["formal_phase_02_approval"])
        self.assertFalse(self.dictionary["customer_source_authorized"])
        self.assertFalse(self.dictionary["product_owner_approved"])
        self.assertFalse(self.dictionary["independent_domain_steward_approved"])

    def test_v11_objective_and_proof_match_controlled_standard(self):
        self.assertEqual(self.dictionary["increment"], "V11")
        self.assertEqual(self.dictionary["objective"], "Declare data types, meaning, and ownership")
        self.assertEqual(self.dictionary["required_proof"], "Approved source/field dictionary")

    def test_four_synthetic_datasets_are_in_dictionary(self):
        self.assertEqual(set(self.index), set(check.EXPECTED_FIELDS))
        self.assertEqual(len(self.index), 4)
        self.assertEqual(self.observed["dataset_count"], 4)

    def test_all_twenty_one_fields_have_explicit_meanings_and_roles(self):
        self.assertEqual(self.observed["field_count"], 21)
        for dataset, fields in self.index.items():
            for name, definition in fields.items():
                with self.subTest(dataset=dataset, name=name):
                    self.assertGreaterEqual(len(definition["meaning"]), 35)
                    self.assertTrue(definition["proposed_steward_role"])
                    self.assertIsNone(definition["assigned_steward"])
                    self.assertIs(definition["nullable"], False)

    def test_v5_v6_fixture_record_counts_match_sources(self):
        self.assertEqual(self.observed["record_counts"], {
            "asset_records": 6,
            "case_records": 12,
            "scripted_review_entries": 4,
            "seeded_reference_labels": 12,
        })
        self.assertTrue(self.observed["all_source_fields_documented"])

    def test_existing_v10_source_freeze_remains_intact(self):
        frozen = check.verify_v10.verify_freeze(check.verify_v10.read_json(
            check.verify_v10.BASELINE))
        self.assertEqual(frozen["frozen_files_verified"], 18)

    def test_source_semantics_do_not_become_customer_authority(self):
        for group in self.dictionary["datasets"]:
            self.assertIsNone(group["customer_system_of_record"])
            self.assertFalse(group["external_data_source"])
            self.assertIsNone(group["assigned_dataset_owner"])
            for field in group["fields"]:
                self.assertEqual(field["source_authority"],
                                 "invented_repository_fixture_not_customer_system")

    def test_utc_timestamp_has_required_format_and_unit(self):
        field = self.index["case_records"]["occurred_at_utc"]
        self.assertEqual(field["logical_type"], "utc_timestamp")
        self.assertEqual(field["unit"], "UTC")
        self.assertEqual(field["timestamp_format"], "YYYY-MM-DDTHH:MM:SSZ")

    def test_cost_and_duration_are_artificial_not_financial_evidence(self):
        cost = self.index["case_records"]["repair_cost_usd"]
        downtime = self.index["case_records"]["downtime_hours"]
        self.assertEqual((cost["unit"], downtime["unit"]), ("USD", "hours"))
        self.assertIn("Invented", cost["meaning"])
        self.assertIn("Artificial", downtime["meaning"])
        self.assertIn("unapproved", cost["precision_policy"])

    def test_case_asset_review_and_label_foreign_keys(self):
        self.assertEqual(self.index["case_records"]["asset_id"]["foreign_key"],
                         "asset_records.asset_id")
        self.assertEqual(self.index["scripted_review_entries"]["case_id"]["foreign_key"],
                         "case_records.case_id")
        self.assertEqual(self.index["seeded_reference_labels"]["case_id"]["foreign_key"],
                         "case_records.case_id")
        self.assertTrue(self.observed["foreign_keys_valid"])

    def test_reference_labels_remain_internal_only(self):
        exposures = {g["id"]: g["exposure"] for g in self.dictionary["datasets"]}
        self.assertEqual(exposures["seeded_reference_labels"],
                         "internal_tests_never_api_or_ui")

    def test_dictionary_rejects_invented_owner_signature(self):
        modified = copy.deepcopy(self.dictionary)
        modified["approval_record"]["named_customer_data_owner"] = "Someone Unverified"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_premature_phase_promotion(self):
        modified = copy.deepcopy(self.dictionary)
        modified["formal_phase_02_approval"] = True
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_customer_system_of_record_claim(self):
        modified = copy.deepcopy(self.dictionary)
        modified["datasets"][0]["customer_system_of_record"] = "Unknown Plant CMMS"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_missing_field(self):
        modified = copy.deepcopy(self.dictionary)
        modified["datasets"][1]["fields"].pop()
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_extra_personnel_field(self):
        modified = copy.deepcopy(self.dictionary)
        field = copy.deepcopy(modified["datasets"][1]["fields"][0])
        field["name"] = "employee_email"
        modified["datasets"][1]["fields"].append(field)
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_unexpected_nullable_id(self):
        modified = copy.deepcopy(self.dictionary)
        modified["datasets"][0]["fields"][0]["nullable"] = True
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_money_type_and_unit_change(self):
        for key, replacement in (("logical_type", "string"), ("unit", "EUR")):
            with self.subTest(key=key):
                modified = copy.deepcopy(self.dictionary)
                field = next(f for f in modified["datasets"][1]["fields"]
                             if f["name"] == "repair_cost_usd")
                field[key] = replacement
                with self.assertRaises(check.FieldDictionaryError):
                    check.validate_dictionary(modified)

    def test_dictionary_rejects_invented_fallback_semantics(self):
        modified = copy.deepcopy(self.dictionary)
        modified["datasets"][1]["fields"][0]["meaning"] = "x"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_dictionary_rejects_weak_identifier_pattern(self):
        modified = copy.deepcopy(self.dictionary)
        modified["datasets"][1]["fields"][0]["pattern"] = ".*"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_dictionary(modified)

    def test_source_rows_reject_non_synthetic_id(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/cases.json"]["assets"][0]["asset_id"] = "REAL-001"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_missing_case_field(self):
        modified = copy.deepcopy(self.sources)
        del modified["fixtures/cases.json"]["records"][0]["repair_cost_usd"]
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_undeclared_pii_field(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/cases.json"]["records"][0]["worker_email"] = "person@example.org"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_boolean_as_numeric(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/cases.json"]["records"][0]["downtime_hours"] = True
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_nonfinite_cost(self):
        for value in (math.nan, math.inf, -1, 1000001):
            with self.subTest(value=str(value)):
                modified = copy.deepcopy(self.sources)
                modified["fixtures/cases.json"]["records"][0]["repair_cost_usd"] = value
                with self.assertRaises(check.FieldDictionaryError):
                    check.validate_rows(self.index, modified)

    def test_source_rows_reject_local_wall_clock(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/cases.json"]["records"][0]["occurred_at_utc"] = "2026-01-05 10:00"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_unknown_asset_fk(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/cases.json"]["records"][0]["asset_id"] = "SYN-ASSET-999"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_duplicate_work_order_reference(self):
        modified = copy.deepcopy(self.sources)
        records = modified["fixtures/cases.json"]["records"]
        records[1]["work_order_ref"] = records[0]["work_order_ref"]
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_duplicate_evidence_refs(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/cases.json"]["records"][0]["evidence_refs"] = ["SYN-EV-001", "SYN-EV-001"]
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_unknown_script_case_fk(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/demo_review_script.json"]["entries"][0]["case_id"] = "SYN-CASE-999"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_source_rows_reject_unapproved_review_action(self):
        modified = copy.deepcopy(self.sources)
        modified["fixtures/demo_review_script.json"]["entries"][0]["disposition"] = "auto_dispatch"
        with self.assertRaises(check.FieldDictionaryError):
            check.validate_rows(self.index, modified)

    def test_reference_labels_cover_every_case_exactly(self):
        records = self.sources["fixtures/reference_labels.json"]["records"]
        cases = self.sources["fixtures/cases.json"]["records"]
        self.assertEqual({r["case_id"] for r in records}, {r["case_id"] for r in cases})
        self.assertEqual(len(records), len(cases))

    def test_v10_formal_phase_decision_stays_blocked(self):
        decision = check.read_json(check.DECISION_PATH)
        self.assertFalse(decision["formal_phase_promotion_authorized"])
        self.assertEqual(decision["formal_decision"], "PENDING_HUMAN_SIGNOFF")
        self.assertEqual(decision["recommended_promotion_decision"], "BLOCKED")

    def test_draft_has_no_assigned_customer_steward(self):
        self.assertFalse(self.dictionary["field_owner_assignments_complete"])
        for dataset in self.dictionary["datasets"]:
            self.assertIsNone(dataset["assigned_dataset_owner"])
            for field in dataset["fields"]:
                self.assertIsNone(field["assigned_steward"])


if __name__ == "__main__":
    unittest.main()
