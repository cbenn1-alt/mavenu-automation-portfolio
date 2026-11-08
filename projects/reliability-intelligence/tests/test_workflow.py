"""V6 end-to-end synthetic workflow regression and fail-closed safety tests."""

import contextlib
import copy
import hashlib
import io
import json
import unittest
from unittest import mock
from wsgiref.util import setup_testing_defaults

from reliability_intelligence import api_v1, fixtures, services, workflow
from reliability_intelligence.__main__ import main
from reliability_intelligence.charter import load_charter
from reliability_intelligence.web import app


def request(path, method="GET"):
    env = {}
    setup_testing_defaults(env)
    env["PATH_INFO"] = path
    env["REQUEST_METHOD"] = method
    result = {}

    def respond(status, headers, exc_info=None):
        result["status"] = status
        result["headers"] = dict(headers)

    result["body"] = b"".join(app(env, respond))
    return result


class V6WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.charter = load_charter()
        cls.report = workflow.run_demo(cls.charter)

    def test_script_is_pinned_to_manifest(self):
        manifest = fixtures._manifest()
        raw = (fixtures.FIXTURE_DIR / manifest["demo_review_script_file"]).read_bytes()
        self.assertEqual(fixtures._git_blob_id(raw), manifest["demo_review_script_git_blob_sha1"])

    def test_script_provenance_explicitly_does_not_claim_real_human(self):
        script = fixtures.load_demo_review_script()
        self.assertTrue(script["scripted_only"])
        self.assertIs(script["human_execution"], False)
        self.assertIn("not an actual approval", script["purpose"])
        self.assertEqual(len(script["entries"]), 4)

    def test_full_fixture_population_is_replayed(self):
        self.assertEqual(self.report["case_count"], 12)
        self.assertEqual(len(self.report["cases"]), 12)
        self.assertEqual(self.report["fixture_set_id"], "SYN-RI-V5-20261107-A")

    def test_four_scripted_dispositions_and_eight_unreviewed(self):
        self.assertEqual(self.report["scripted_disposition_count"], 4)
        self.assertEqual(self.report["not_dispositioned_count"], 8)
        scripted = [row for row in self.report["cases"] if row["simulated_disposition"]]
        self.assertEqual({row["case_id"] for row in scripted},
                         {"SYN-CASE-001", "SYN-CASE-004", "SYN-CASE-009", "SYN-CASE-010"})
        for row in scripted:
            disposition = row["simulated_disposition"]
            self.assertTrue(disposition["scripted_synthetic"])
            self.assertFalse(disposition["performed_by_real_human"])
            self.assertFalse(disposition["operational_approval"])

    def test_end_to_end_case_has_ordered_stages(self):
        events = [x["stage"] for x in self.report["events"] if x["case_id"] == "SYN-CASE-004"]
        self.assertEqual(events, [
            "intake", "evidence_check", "rules_review",
            "simulated_reviewer_disposition", "in_memory_export",
        ])

    def test_undispositioned_case_stops_in_demo_queue(self):
        events = [x["stage"] for x in self.report["events"] if x["case_id"] == "SYN-CASE-003"]
        self.assertEqual(events, [
            "intake", "evidence_check", "rules_review", "awaiting_demo_review",
        ])
        case = next(x for x in self.report["cases"] if x["case_id"] == "SYN-CASE-003")
        self.assertIsNone(case["simulated_disposition"])

    def test_recurrence_uses_only_preceding_history(self):
        cases = {row["case_id"]: row for row in self.report["cases"]}
        self.assertNotIn("repeat_within_30_days", cases["SYN-CASE-003"]["synthetic_flags"])
        self.assertIn("repeat_within_30_days", cases["SYN-CASE-004"]["synthetic_flags"])
        self.assertEqual(cases["SYN-CASE-004"]["preceding_matching_case_ids"], ["SYN-CASE-003"])
        self.assertNotIn("SYN-CASE-004", cases["SYN-CASE-003"]["preceding_matching_case_ids"])

    def test_missing_reference_is_flagged_without_fake_evidence(self):
        case = next(row for row in self.report["cases"] if row["case_id"] == "SYN-CASE-009")
        self.assertEqual(case["synthetic_evidence_refs"], [])
        self.assertIn("missing_evidence_reference", case["synthetic_flags"])
        self.assertEqual(case["simulated_disposition"]["value"], "request_evidence")
        evidence_event = next(x for x in self.report["events"]
                              if x["case_id"] == "SYN-CASE-009" and x["stage"] == "evidence_check")
        self.assertFalse(evidence_event["detail"]["evidence_documents_present"])

    def test_example_rule_counts_are_not_real_incidence_rates(self):
        self.assertEqual(self.report["synthetic_flag_counts"], {
            "missing_evidence_reference": 1,
            "repeat_within_30_days": 6,
        })
        self.assertFalse(self.report["measured_business_outcome"])
        self.assertEqual(self.report["mode"], "deterministic_synthetic_replay")

    def test_event_sequences_are_monotonic_and_trace_reconstructable(self):
        events = self.report["events"]
        self.assertEqual(self.report["event_count"], 52)
        self.assertEqual([x["sequence"] for x in events], list(range(1, 53)))
        expected = hashlib.sha256(workflow._canonical(events)).hexdigest()
        self.assertEqual(self.report["trace_sha256"], expected)

    def test_replayed_trace_checksum_is_deterministic(self):
        rerun = workflow.run_demo(self.charter)
        self.assertEqual(self.report, rerun)
        self.assertEqual(self.report["trace_sha256"], rerun["trace_sha256"])

    def test_trace_checksum_is_not_misrepresented_as_signature(self):
        self.assertFalse(self.report["trace_persisted"])
        self.assertIn("not_cryptographic_attestation", self.report["trace_checksum_kind"])
        self.assertIn("not real human sign-off", self.report["explanation"])

    def test_no_external_or_ot_actions(self):
        for key in ("real_human_review_performed", "actual_customer_data_used",
                    "operational_approval_granted", "real_work_orders_written",
                    "external_actions_executed", "measured_business_outcome"):
            self.assertIs(self.report[key], False, key)

    def test_script_rejects_external_or_real_reviewers(self):
        original = fixtures.load_demo_review_script()
        mutated = copy.deepcopy(original)
        mutated["entries"][0]["reviewer_id"] = "REAL-OPERATOR"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_demo_review_script(mutated, fixtures.load_fixture_set())

    def test_script_rejects_nonfiction_human_execution(self):
        original = fixtures.load_demo_review_script()
        altered = copy.deepcopy(original)
        altered["human_execution"] = True
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_demo_review_script(altered, fixtures.load_fixture_set())

    def test_script_rejects_duplicate_case(self):
        original = fixtures.load_demo_review_script()
        altered = copy.deepcopy(original)
        altered["entries"][1]["case_id"] = altered["entries"][0]["case_id"]
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_demo_review_script(altered, fixtures.load_fixture_set())

    def test_script_rejects_unrecognized_disposition(self):
        original = fixtures.load_demo_review_script()
        altered = copy.deepcopy(original)
        altered["entries"][0]["disposition"] = "repair_equipment_now"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_demo_review_script(altered, fixtures.load_fixture_set())

    def test_script_rejects_unexpected_personnel_fields(self):
        original = fixtures.load_demo_review_script()
        altered = copy.deepcopy(original)
        altered["entries"][0]["employee_email"] = "realperson@example.org"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_demo_review_script(altered, fixtures.load_fixture_set())

    def test_script_mismatch_to_fixture_flags_fails_closed(self):
        original = fixtures.load_demo_review_script()
        altered = copy.deepcopy(original)
        altered["entries"][1]["disposition"] = "request_evidence"
        altered["entries"][1]["reason_code"] = "missing_evidence_reference"
        with mock.patch("reliability_intelligence.workflow.load_demo_review_script", return_value=altered):
            with self.assertRaises(fixtures.InvalidFixture):
                workflow.run_demo(self.charter)

    def test_non_synthetic_charter_rejected_before_replay(self):
        invalid = copy.deepcopy(self.charter)
        invalid["data_and_safety"]["data_mode"] = "CUSTOMER_DATA"
        with self.assertRaises(ValueError):
            workflow.run_demo(invalid)

    def test_api_demo_is_versioned_read_only_and_has_no_reference_labels(self):
        result = request("/api/v1/demo")
        self.assertEqual(result["status"], "200 OK")
        self.assertEqual(result["headers"]["Content-Type"], api_v1.API_MEDIA_TYPE)
        payload = json.loads(result["body"])
        self.assertEqual(payload["schema_version"], "1.2.0")
        self.assertEqual(payload["resource"], "demo")
        self.assertEqual(payload["data"]["trace_sha256"], self.report["trace_sha256"])
        self.assertNotIn(b"expected_review_label", result["body"])
        self.assertNotIn(b"repeat_history_candidate", result["body"])

    def test_demo_endpoint_unsafe_methods_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            result = request("/api/v1/demo", method)
            self.assertEqual(result["status"], "405 Method Not Allowed")
            self.assertEqual(result["headers"]["Allow"], "GET, HEAD")

    def test_demo_head_has_no_body(self):
        get_result = request("/api/v1/demo")
        head_result = request("/api/v1/demo", "HEAD")
        self.assertEqual(head_result["status"], "200 OK")
        self.assertEqual(head_result["body"], b"")
        self.assertEqual(head_result["headers"]["Content-Length"], str(len(get_result["body"])))

    def test_corrupted_script_yields_sanitized_api_failure(self):
        with mock.patch("reliability_intelligence.workflow.load_demo_review_script",
                        side_effect=fixtures.InvalidFixture("sensitive internal path /secret")):
            response = request("/api/v1/demo")
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertEqual(json.loads(response["body"])["error"]["code"], "fixture_invalid")
        self.assertNotIn(b"/secret", response["body"])

    def test_ui_has_workflow_page_with_scripted_disclosure(self):
        response = request("/workflow")
        self.assertEqual(response["status"], "200 OK")
        body = response["body"]
        self.assertIn(b"End-to-end synthetic workflow", body)
        self.assertIn(b"Fictional reviewer role only", body)
        self.assertIn(self.report["trace_sha256"].encode(), body)
        self.assertNotIn(b"expected_review_label", body)

    def test_cli_demo_json_is_identical_to_service(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["demo", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue()), self.report)

    def test_cli_status_tracks_v6_with_no_production_access(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["status", "--json"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["increment"], "V6")
        self.assertEqual(data["api_schema_version"], "1.2.0")
        self.assertFalse(data["production_ready"])
        self.assertFalse(data["ot_writes_enabled"])


if __name__ == "__main__":
    unittest.main()
