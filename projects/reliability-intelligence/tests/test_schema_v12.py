"""V12 required-field and allowed-value schema regression.

All mutations act on deep-copied, fictional V5/V6 fixture data.
No real customer records or signed dictionary approval are claimed.
"""

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
SPEC = importlib.util.spec_from_file_location("v12_schema_verifier", PROJECT / "scripts" / "verify_v12.py")
assert SPEC and SPEC.loader
v12 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v12)


class V12SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = v12.verify_v11.read_json(v12.CONTRACT_PATH)
        cls.dictionary = v12.verify_v11.read_json(v12.DICTIONARY_PATH)
        cls.groups = v12.validate_contract(cls.contract, cls.dictionary)
        cls.sources = v12.verify_v11.load_sources()
        cls.positive = v12.validate_rows(cls.groups, cls.sources)
        cls.negative = v12.negative_case_report(cls.groups, cls.sources)

    def test_01_objective_proof(self):
        self.assertEqual(self.contract["increment"], "V12")
        self.assertEqual(self.contract["objective"], "Validate required fields and allowed values")
        self.assertEqual(self.contract["required_proof"], "Schema validation test report")

    def test_02_unsigned_status(self):
        self.assertEqual(self.contract["contract_status"], "TECHNICALLY_CHECKABLE_DRAFT_NOT_APPROVED")
        self.assertIsNone(self.contract["approval_signature"])
        self.assertFalse(self.contract["formal_phase_02_approval"])

    def test_03_four_source_datasets(self):
        self.assertEqual(len(self.groups), 4)
        self.assertEqual(set(self.groups), set(v12.verify_v11.EXPECTED_FIELDS))

    def test_04_twenty_one_field_definitions(self):
        self.assertEqual(self.positive["fields_declared"], 21)

    def test_05_thirty_four_synthetic_rows(self):
        self.assertEqual(self.positive["records_checked"], 34)
        self.assertEqual(self.positive["record_counts"], {
            "asset_records": 6, "case_records": 12,
            "scripted_review_entries": 4, "seeded_reference_labels": 12,
        })

    def test_06_every_row_field_is_required_and_typed(self):
        self.assertEqual(self.positive["required_field_checks"], 196)
        self.assertEqual(self.positive["type_checks"], 196)

    def test_07_enumerations_are_checked(self):
        self.assertEqual(self.contract["enum_field_count"], 10)
        self.assertGreater(self.positive["allowed_value_checks"], 0)

    def test_08_patterns_are_checked(self):
        self.assertEqual(self.contract["identifier_pattern_count"], 7)
        self.assertGreater(self.positive["pattern_checks"], 0)

    def test_09_negative_matrix_rejects_sixteen_mutations(self):
        self.assertEqual(self.negative["negative_case_count"], 16)
        self.assertEqual(self.negative["negative_cases_passed"], 16)
        self.assertTrue(all(c["result"] == "REJECTED_AS_EXPECTED"
                            for c in self.negative["negative_cases"]))
        self.assertFalse(self.negative["fixture_files_modified"])

    def test_10_positive_report_is_deterministic(self):
        self.assertEqual(v12.validate_rows(self.groups, self.sources), self.positive)

    def test_11_unchanged_v10_source_freeze(self):
        frozen = v12.verify_v10.verify_freeze(v12.verify_v10.read_json(v12.verify_v10.BASELINE))
        self.assertEqual(frozen["frozen_files_verified"], 18)

    def test_12_formal_v10_promotion_remains_blocked(self):
        decision = v12.verify_v11.read_json(v12.DECISION_PATH)
        self.assertEqual(decision["recommended_promotion_decision"], "BLOCKED")
        self.assertFalse(decision["formal_phase_promotion_authorized"])

    def test_13_reject_false_v12_schema_approval(self):
        changed = copy.deepcopy(self.contract)
        changed["schema_owner_approved"] = True
        with self.assertRaises(v12.SchemaContractError):
            v12.validate_contract(changed, self.dictionary)

    def test_14_reject_customer_data_permission(self):
        changed = copy.deepcopy(self.contract)
        changed["customer_data_permitted"] = True
        with self.assertRaises(v12.SchemaContractError):
            v12.validate_contract(changed, self.dictionary)

    def test_15_reject_premature_v11_approval(self):
        changed = copy.deepcopy(self.contract)
        changed["dictionary_approval_status"] = "APPROVED"
        with self.assertRaises(v12.SchemaContractError):
            v12.validate_contract(changed, self.dictionary)

    def test_16_reject_missing_contract_dataset(self):
        changed = copy.deepcopy(self.contract)
        changed["groups"].pop()
        with self.assertRaises(v12.SchemaContractError):
            v12.validate_contract(changed, self.dictionary)

    def test_17_reject_broadened_allowed_enum(self):
        changed = copy.deepcopy(self.contract)
        changed["groups"][1]["allowed_values"]["failure_code"].append("unapproved_fault")
        with self.assertRaises(v12.SchemaContractError):
            v12.validate_contract(changed, self.dictionary)

    def test_18_reject_relaxed_extra_field_policy(self):
        changed = copy.deepcopy(self.contract)
        changed["groups"][1]["extra_fields"] = "ALLOW"
        with self.assertRaises(v12.SchemaContractError):
            v12.validate_contract(changed, self.dictionary)

    def test_19_missing_case_failure(self):
        changed = copy.deepcopy(self.sources)
        del changed["fixtures/cases.json"]["records"][0]["failure_code"]
        with self.assertRaisesRegex(v12.SchemaContractError, "missing_required_field"):
            v12.validate_rows(self.groups, changed)

    def test_20_extra_case_field(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["unapproved_email"] = 'SYN-ONLY'
        with self.assertRaisesRegex(v12.SchemaContractError, "undeclared_field"):
            v12.validate_rows(self.groups, changed)

    def test_21_unrecognized_failure_code(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["failure_code"] = 'not_in_dictionary'
        with self.assertRaisesRegex(v12.SchemaContractError, "disallowed_field_value"):
            v12.validate_rows(self.groups, changed)

    def test_22_bool_as_number(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["downtime_hours"] = True
        with self.assertRaisesRegex(v12.SchemaContractError, "wrong_required_field_type"):
            v12.validate_rows(self.groups, changed)

    def test_23_false_synthetic(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["synthetic"] = False
        with self.assertRaisesRegex(v12.SchemaContractError, "disallowed_field_value"):
            v12.validate_rows(self.groups, changed)

    def test_24_non_synthetic_id(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["case_id"] = 'REAL-123'
        with self.assertRaisesRegex(v12.SchemaContractError, "invalid_identifier_pattern"):
            v12.validate_rows(self.groups, changed)

    def test_25_invalid_work_order_id(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["work_order_ref"] = 'REAL-WO-100'
        with self.assertRaisesRegex(v12.SchemaContractError, "invalid_identifier_pattern"):
            v12.validate_rows(self.groups, changed)

    def test_26_bad_evidence_item(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["records"][0]["evidence_refs"] = ['ACTUAL-EVIDENCE']
        with self.assertRaisesRegex(v12.SchemaContractError, "invalid_element_pattern"):
            v12.validate_rows(self.groups, changed)

    def test_27_invalid_asset_class(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["assets"][0]["asset_class"] = 'unknown_machine'
        with self.assertRaisesRegex(v12.SchemaContractError, "disallowed_field_value"):
            v12.validate_rows(self.groups, changed)

    def test_28_invalid_asset_id(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["assets"][0]["asset_id"] = 'REAL-ASSET'
        with self.assertRaisesRegex(v12.SchemaContractError, "invalid_identifier_pattern"):
            v12.validate_rows(self.groups, changed)

    def test_29_unauthorized_reviewer_action(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/demo_review_script.json"]["entries"][0]["disposition"] = 'auto_repair'
        with self.assertRaisesRegex(v12.SchemaContractError, "disallowed_field_value"):
            v12.validate_rows(self.groups, changed)

    def test_30_unauthorized_reviewer_reason(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/demo_review_script.json"]["entries"][0]["reason_code"] = 'operator_approved'
        with self.assertRaisesRegex(v12.SchemaContractError, "disallowed_field_value"):
            v12.validate_rows(self.groups, changed)

    def test_31_invalid_reference_label(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/reference_labels.json"]["records"][0]["expected_review_label"] = 'real_fault'
        with self.assertRaisesRegex(v12.SchemaContractError, "disallowed_field_value"):
            v12.validate_rows(self.groups, changed)

    def test_32_integer_label_origin(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/reference_labels.json"]["records"][0]["synthetic"] = 1
        with self.assertRaisesRegex(v12.SchemaContractError, "wrong_required_field_type"):
            v12.validate_rows(self.groups, changed)

    def test_33_missing_reviewer_id(self):
        changed = copy.deepcopy(self.sources)
        del changed["fixtures/demo_review_script.json"]["entries"][0]["reviewer_id"]
        with self.assertRaisesRegex(v12.SchemaContractError, "missing_required_field"):
            v12.validate_rows(self.groups, changed)

    def test_34_extra_asset_field(self):
        changed = copy.deepcopy(self.sources)
        changed["fixtures/cases.json"]["assets"][0]["operator_email"] = 'SYN-NO-PII'
        with self.assertRaisesRegex(v12.SchemaContractError, "undeclared_field"):
            v12.validate_rows(self.groups, changed)


if __name__ == "__main__":
    unittest.main()
