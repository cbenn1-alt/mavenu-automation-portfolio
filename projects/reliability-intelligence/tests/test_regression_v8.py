"""V8 cross-layer smoke contract: safety, deterministic V6 trace, and V7 failures.

These are regression checks of the synthetic local prototype, NOT customer,
industrial safety, cybersecurity certification or measured business value.
"""

import json
import unittest
from unittest import mock
from wsgiref.util import setup_testing_defaults

from reliability_intelligence import api_v1, diagnostics, fixtures, workflow
from reliability_intelligence.charter import load_charter
from reliability_intelligence.web import ROUTES, app


def request(path, method="GET"):
    env = {}
    setup_testing_defaults(env)
    env["PATH_INFO"] = path
    env["REQUEST_METHOD"] = method
    response = {}

    def start_response(status, headers, exc_info=None):
        response["status"] = status
        response["headers"] = dict(headers)
    response["body"] = b"".join(app(env, start_response))
    return response


class V8CrossLayerSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.charter = load_charter()

    def test_all_ui_routes_smoke(self):
        self.assertEqual(len(ROUTES), 5)
        for path, label in ROUTES:
            with self.subTest(path=path):
                response = request(path)
                self.assertEqual(response["status"], "200 OK")
                self.assertIn(b"<main ", response["body"])
                self.assertIn(label.encode(), response["body"])
                self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_all_api_routes_smoke(self):
        self.assertEqual(len(api_v1.ROUTE_DESCRIPTIONS), 5)
        for path in api_v1.ROUTE_DESCRIPTIONS:
            with self.subTest(path=path):
                response = request(path)
                self.assertEqual(response["status"], "200 OK")
                doc = json.loads(response["body"])
                self.assertEqual(doc["api_version"], "v1")
                self.assertEqual(doc["schema_version"], "1.3.0")
                self.assertEqual(int(response["headers"]["Content-Length"]), len(response["body"]))

    def test_api_contract_lists_actual_supported_routes(self):
        response = request("/api/v1/contract")
        contract = json.loads(response["body"])["data"]
        self.assertEqual(set(contract["routes"]), set(api_v1.ROUTE_DESCRIPTIONS))
        self.assertTrue(all(value["methods"] == ["GET", "HEAD"]
                            for value in contract["routes"].values()))
        self.assertFalse(contract["limits"]["write_endpoints"])

    def test_synthetic_fixture_provenance_smoke(self):
        dataset = fixtures.load_fixture_set()
        script = fixtures.load_demo_review_script()
        self.assertEqual(dataset["fixture_set_id"], script["fixture_set_id"])
        self.assertEqual(len(dataset["assets"]), 6)
        self.assertEqual(len(dataset["records"]), 12)
        self.assertIs(dataset["synthetic_only"], True)
        self.assertIs(script["human_execution"], False)

    def test_end_to_end_replay_is_deterministic(self):
        first = workflow.run_demo(self.charter)
        second = workflow.run_demo(self.charter)
        self.assertEqual(first["trace_sha256"], second["trace_sha256"])
        self.assertEqual(first["events"], second["events"])
        self.assertEqual(first["case_count"], 12)
        self.assertEqual(first["scripted_disposition_count"], 4)

    def test_workflow_remains_human_unapproved(self):
        data = json.loads(request("/api/v1/demo")["body"])["data"]
        for key in ("real_human_review_performed", "operational_approval_granted",
                    "real_work_orders_written", "actual_customer_data_used",
                    "external_actions_executed", "measured_business_outcome"):
            self.assertFalse(data[key], key)

    def test_status_cannot_be_mistaken_for_live_asset_health(self):
        data = json.loads(request("/api/v1/status")["body"])["data"]
        for key in ("validated_customer_problem", "production_ready",
                    "operational_data_loaded", "model_present",
                    "external_integrations_enabled", "ot_or_cmms_writes_enabled",
                    "measured_effectiveness"):
            self.assertIs(data[key], False, key)

    def test_reference_labels_not_leaked_into_demo_or_case_api(self):
        for path in ("/api/v1/cases", "/api/v1/demo", "/workbench", "/workflow"):
            with self.subTest(path=path):
                body = request(path)["body"]
                self.assertNotIn(b"expected_review_label", body)
                self.assertNotIn(b"repeat_history_candidate", body)

    def test_post_is_rejected_for_every_api_endpoint(self):
        for path in api_v1.ROUTE_DESCRIPTIONS:
            with self.subTest(path=path), mock.patch.object(diagnostics.LOGGER, "log"):
                response = request(path, "POST")
                self.assertEqual(response["status"], "405 Method Not Allowed")
                self.assertEqual(response["headers"]["Allow"], "GET, HEAD")

    def test_future_api_versions_do_not_alias_v1(self):
        with mock.patch.object(diagnostics.LOGGER, "log"):
            for path in ("/api/v2/status", "/api/v3/demo", "/api/v1/not-a-resource"):
                with self.subTest(path=path):
                    response = request(path)
                    self.assertEqual(response["status"], "404 Not Found")
                    self.assertEqual(response["headers"]["X-Diagnostic-Code"], "not_found")

    def test_head_preserves_content_length_and_has_no_body(self):
        for path in ("/", "/workflow", "/api/v1/status", "/api/v1/demo"):
            with self.subTest(path=path):
                get_result = request(path)
                head_result = request(path, "HEAD")
                self.assertEqual(get_result["status"], head_result["status"])
                self.assertEqual(head_result["body"], b"")
                self.assertEqual(get_result["headers"]["Content-Length"],
                                 head_result["headers"]["Content-Length"])

    def test_missing_fixture_yields_sanitized_failure(self):
        with (mock.patch("reliability_intelligence.services.load_fixture_set",
                         side_effect=fixtures.InvalidFixture("secret key and internal path")),
              mock.patch.object(diagnostics.LOGGER, "log")):
            response = request("/api/v1/cases")
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "fixture_invalid")
        self.assertNotIn(b"secret key", response["body"])

    def test_unexpected_service_exception_is_not_exposed(self):
        with (mock.patch("reliability_intelligence.api_v1.data_for_path",
                         side_effect=RuntimeError("sensitive stack detail")),
              mock.patch.object(diagnostics.LOGGER, "log")):
            response = request("/api/v1/demo")
        self.assertEqual(response["status"], "500 Internal Server Error")
        self.assertNotIn(b"sensitive stack detail", response["body"])
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "internal_failure")

    def test_diagnostics_are_category_not_unique_request_ids(self):
        a = diagnostics.event("not_found", stage="routing", surface="api")
        b = diagnostics.event("not_found", stage="routing", surface="api")
        self.assertEqual(a["diagnostic_id"], b["diagnostic_id"])
        self.assertFalse(a["request_contents_recorded"])
        self.assertFalse(a["persistent_log_storage"])

    def test_unsafe_deployment_is_still_prohibited(self):
        self.assertFalse(self.charter["data_and_safety"]["customer_data_authorized"])
        self.assertFalse(self.charter["data_and_safety"]["production_deployment_allowed"])
        self.assertFalse(self.charter["data_and_safety"]["plc_scada_ot_writes_enabled"])
        self.assertFalse(self.charter["data_and_safety"]["maintenance_order_writes_enabled"])


if __name__ == "__main__":
    unittest.main()
