"""Contract tests; passing does not establish operational reliability benefit."""

import contextlib
import copy
import io
import json
import unittest

from reliability_intelligence.__main__ import main
from reliability_intelligence.charter import InvalidCharter, load_charter, validate_charter


class V2CharterTests(unittest.TestCase):
    def setUp(self):
        self.data = load_charter()

    def test_charter_is_unapproved_v2(self):
        self.assertEqual(self.data["increment"], "V2")
        self.assertEqual(self.data["approval"]["status"], "PENDING")
        self.assertFalse(self.data["approval"]["release_gate_passed"])

    def test_user_problem_and_outcome_are_declared(self):
        self.assertTrue(self.data["primary_user_role"])
        self.assertTrue(self.data["problem"]["statement"])
        self.assertTrue(self.data["primary_metric"]["evaluation_method"])

    def test_customer_data_is_forbidden(self):
        self.assertFalse(self.data["data_and_safety"]["customer_data_authorized"])
        self.assertEqual(self.data["data_and_safety"]["data_mode"], "SYNTHETIC_ONLY")

    def test_external_integrations_forbidden(self):
        self.assertFalse(self.data["data_and_safety"]["external_integrations_enabled"])

    def test_plant_and_work_order_writes_forbidden(self):
        self.assertFalse(self.data["data_and_safety"]["plc_scada_ot_writes_enabled"])
        self.assertFalse(self.data["data_and_safety"]["maintenance_order_writes_enabled"])

    def test_no_roi_claim(self):
        self.assertFalse(self.data["economics"]["cost_savings_claimed"])

    def test_customer_access_flip_fails(self):
        changed = copy.deepcopy(self.data)
        changed["data_and_safety"]["customer_data_authorized"] = True
        with self.assertRaises(InvalidCharter):
            validate_charter(changed)

    def test_unapproved_claim_flip_fails(self):
        changed = copy.deepcopy(self.data)
        changed["approval"]["status"] = "APPROVED"
        with self.assertRaises(InvalidCharter):
            validate_charter(changed)

    def test_metric_target_must_be_bounded(self):
        changed = copy.deepcopy(self.data)
        changed["primary_metric"]["proposed_relative_improvement_pct"] = 140
        with self.assertRaises(InvalidCharter):
            validate_charter(changed)

    def test_no_measured_baseline_can_be_asserted(self):
        changed = copy.deepcopy(self.data)
        changed["primary_metric"]["baseline_minutes_per_case"] = 10
        with self.assertRaises(InvalidCharter):
            validate_charter(changed)

    def test_cli_emits_safe_machine_readable_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["status", "--json"]), 0)
        status = json.loads(out.getvalue())
        self.assertFalse(status["business_approved"])
        self.assertFalse(status["production_ready"])
        self.assertFalse(status["ot_writes_enabled"])

    def test_cli_contract_validation_does_not_claim_business_approval(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["validate", "--json"]), 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["valid_contract"])
        self.assertFalse(result["business_approved"])


if __name__ == "__main__":
    unittest.main()
