"""V10 frozen-source and blocked-prototype-decision regression tests.

These tests verify that a *technical* baseline is pinned and open risks are
truthfully recorded. They do not sign the decision or authorize progression.
"""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("v10_verify", PROJECT / "scripts" / "verify_v10.py")
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class V10DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = check.read_json(check.BASELINE)
        cls.risks = check.read_json(check.RISKS)
        cls.decision = check.read_json(check.DECISION)
        cls.v8 = check.read_json(check.V8_BASELINE)
        cls.v9 = check.read_json(check.V9_REVIEWER_RECORD)
        cls.risk_summary = check.verify_risks(cls.risks)

    def test_v10_baseline_objective_and_proof_are_exact(self):
        self.assertEqual(self.baseline["objective"], "Freeze prototype baseline and open risk list")
        self.assertEqual(self.baseline["required_proof"], "Prototype decision record")

    def test_v9_snapshot_pinned_to_verified_git_commit(self):
        self.assertEqual(self.baseline["baseline_commit"], "704123eca45628bf504594af39a66036cc0451c5")
        self.assertEqual(self.baseline["baseline_runtime_version"], "0.9.0")
        self.assertEqual(self.baseline["baseline_api_schema_version"], "1.3.0")

    def test_eighteen_source_and_fixture_files_have_verified_git_blobs(self):
        result = check.verify_freeze(self.baseline)
        self.assertEqual(result["frozen_files_verified"], 18)
        self.assertEqual(len(self.baseline["frozen_paths_git_blob_sha1"]), 18)

    def test_git_blob_id_uses_git_object_header(self):
        raw = b"synthetic test bytes only"
        import hashlib
        expected = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        self.assertEqual(check.git_blob_id(raw), expected)

    def test_baseline_fails_if_frozen_git_blob_changes(self):
        altered = copy.deepcopy(self.baseline)
        key = "src/reliability_intelligence/workflow.py"
        altered["frozen_paths_git_blob_sha1"][key] = "0" * 40
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_freeze(altered)

    def test_baseline_fails_if_pinned_path_removed(self):
        altered = copy.deepcopy(self.baseline)
        del altered["frozen_paths_git_blob_sha1"]["fixtures/cases.json"]
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_freeze(altered)

    def test_baseline_rejects_false_live_authorization(self):
        altered = copy.deepcopy(self.baseline)
        altered["customer_live_data_authorized"] = True
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_freeze(altered)

    def test_baseline_requires_verified_v9_evidence(self):
        altered = copy.deepcopy(self.baseline)
        altered["v9_ci"]["conclusion"] = "pending"
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_freeze(altered)

    def test_baseline_contains_original_153_test_and_coverage_evidence(self):
        v9 = self.baseline["v9_ci"]
        self.assertEqual(v9["tests_passed"], 153)
        self.assertEqual(v9["measured_combined_coverage_percent"], 84.951)
        self.assertEqual(v9["minimum_coverage_percent"], 84.5)
        self.assertEqual(v9["automated_socket_replay_checks_passed"], 12)

    def test_risk_register_has_open_unassigned_items(self):
        result = check.verify_risks(self.risks)
        self.assertEqual(result["risk_count"], 11)
        self.assertEqual(result["unassigned_owners"], 11)
        self.assertGreaterEqual(len(result["formal_promotion_blockers"]), 4)

    def test_risk_register_rejects_duplicate_ids(self):
        altered = copy.deepcopy(self.risks)
        altered["risks"][1]["risk_id"] = altered["risks"][0]["risk_id"]
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_risks(altered)

    def test_risk_register_rejects_unsupported_closed_status(self):
        altered = copy.deepcopy(self.risks)
        altered["risks"][0]["status"] = "CLOSED"
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_risks(altered)

    def test_risk_register_rejects_invented_owner_assignment(self):
        altered = copy.deepcopy(self.risks)
        altered["risks"][0]["assigned_owner"] = "Invented Owner"
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_risks(altered)

    def test_risk_register_rejects_removed_formal_blocker(self):
        altered = copy.deepcopy(self.risks)
        altered["formal_v10_blocker_ids"].remove("RI-V10-R04")
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_risks(altered)

    def test_decision_is_draft_pending_signoff_and_recommends_block(self):
        result = check.verify_decision(
            self.decision, self.baseline, self.risk_summary, self.v8, self.v9
        )
        self.assertEqual(result["recommended_promotion_decision"], "BLOCKED")
        self.assertEqual(result["formal_decision"], "PENDING_HUMAN_SIGNOFF")
        self.assertFalse(result["formal_phase_promotion_authorized"])

    def test_decision_rejects_false_signed_owner(self):
        altered = copy.deepcopy(self.decision)
        altered["owner_signature"] = "Fake approval"
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_decision(altered, self.baseline, self.risk_summary, self.v8, self.v9)

    def test_decision_rejects_premature_phase_promotion(self):
        altered = copy.deepcopy(self.decision)
        altered["formal_phase_promotion_authorized"] = True
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_decision(altered, self.baseline, self.risk_summary, self.v8, self.v9)

    def test_decision_rejects_falsified_human_v9_review(self):
        altered = copy.deepcopy(self.v9)
        altered["independent_human_replay_completed"] = True
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_decision(self.decision, self.baseline, self.risk_summary, self.v8, altered)

    def test_decision_rejects_missing_blocking_risk(self):
        altered = copy.deepcopy(self.decision)
        altered["blocking_risk_ids"] = []
        with self.assertRaises(check.DecisionEvidenceError):
            check.verify_decision(altered, self.baseline, self.risk_summary, self.v8, self.v9)

    def test_decision_preserves_scope_for_synthetic_research_only(self):
        self.assertTrue(self.decision["next_phase_internal_synthetic_experiments_allowed"])
        self.assertFalse(self.decision["customer_data_or_ot_access"])
        self.assertFalse(self.decision["deployment_authorization"])
        self.assertFalse(self.decision["economic_benefit_verified"])

    def test_v9_review_template_is_unsigned(self):
        self.assertIsNone(self.v9["reviewer_signature"])
        self.assertFalse(self.v9["formal_acceptance_granted"])
        self.assertFalse(self.v9["independent_human_replay_completed"])

    def test_risks_include_customer_and_industrial_controls(self):
        scopes = {r["blocking_scope"] for r in self.risks["risks"]}
        self.assertIn("customer_data_or_pilot", scopes)
        self.assertIn("commercial_build_decision", scopes)
        self.assertIn("formal_v10_acceptance", scopes)

    def test_no_invented_promotions_in_machine_decision(self):
        self.assertIsNone(self.decision["named_decision_owner"])
        self.assertIsNone(self.decision["decision_date"])
        self.assertEqual(self.decision["formal_decision"], "PENDING_HUMAN_SIGNOFF")


if __name__ == "__main__":
    unittest.main()
