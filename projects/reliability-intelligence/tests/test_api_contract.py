"""V4 versioned API contract, boundaries, and negative-path smoke tests."""

import json
import unittest
from unittest import mock

from reliability_intelligence import api_v1, services
from reliability_intelligence.charter import InvalidCharter, load_charter
from reliability_intelligence.web import app
from wsgiref.util import setup_testing_defaults


def request(path, method="GET", query=""):
    env = {}
    setup_testing_defaults(env)
    env["PATH_INFO"] = path
    env["REQUEST_METHOD"] = method
    env["QUERY_STRING"] = query
    result = {}

    def start_response(status, headers, exc_info=None):
        result["status"] = status
        result["headers"] = dict(headers)

    body = b"".join(app(env, start_response))
    return result["status"], result["headers"], body


class V4APIContractTests(unittest.TestCase):
    def setUp(self):
        self.charter = load_charter()

    def test_supported_versioned_routes(self):
        for path, resource in [
            ("/api/v1/status", "status"),
            ("/api/v1/scope", "scope"),
            ("/api/v1/cases", "cases"),
            ("/api/v1/demo", "demo"),
            ("/api/v1/contract", "contract"),
        ]:
            with self.subTest(path=path):
                status, headers, body = request(path)
                self.assertEqual(status, "200 OK")
                self.assertEqual(headers["Content-Type"], api_v1.API_MEDIA_TYPE)
                self.assertEqual(int(headers["Content-Length"]), len(body))
                doc = json.loads(body)
                self.assertEqual(doc["api_version"], "v1")
                self.assertEqual(doc["schema_version"], "1.3.0")
                self.assertEqual(doc["resource"], resource)
                self.assertIsInstance(doc["data"], dict)

    def test_response_envelope_is_stable(self):
        for path in api_v1.ROUTE_DESCRIPTIONS:
            with self.subTest(path=path):
                _, _, body = request(path)
                self.assertEqual(set(json.loads(body)), {"api_version", "schema_version", "resource", "data"})

    def test_declared_required_fields_present(self):
        for path, (resource, _) in api_v1.RESOURCES.items():
            with self.subTest(path=path):
                _, _, body = request(path)
                self.assertEqual(set(json.loads(body)["data"]), set(api_v1.REQUIRED_FIELDS[resource]))

    def test_service_status_explicitly_not_operational(self):
        _, _, body = request("/api/v1/status")
        data = json.loads(body)["data"]
        self.assertEqual(data["increment"], "V9")
        self.assertIs(data["synthetic_fixtures_available"], True)
        self.assertEqual(data["business_approval"], "pending")
        self.assertFalse(data["validated_customer_problem"])
        for key in ("production_ready", "operational_data_loaded", "model_present",
                    "external_integrations_enabled", "ot_or_cmms_writes_enabled",
                    "measured_effectiveness"):
            self.assertIs(data[key], False)

    def test_scope_is_candidate_and_has_no_baseline(self):
        _, _, body = request("/api/v1/scope")
        data = json.loads(body)["data"]
        self.assertFalse(data["customer_partner_authorized"])
        self.assertIsNone(data["evaluation"]["baseline"])
        self.assertEqual(data["evaluation"]["result"], "not_measured")
        self.assertEqual(data["boundary"]["data_mode"], "synthetic_only")
        self.assertEqual(data["boundary"]["work_order_writes"], "disabled")

    def test_cases_are_synthetic_fixtures_not_customer_failures(self):
        _, _, body = request("/api/v1/cases")
        data = json.loads(body)["data"]
        self.assertEqual(data["count"], 12)
        self.assertEqual(len(data["items"]), 12)
        self.assertTrue(all(row["synthetic"] is True for row in data["items"]))
        self.assertTrue(all(row["review_state"] == "fixture_only" for row in data["items"]))
        self.assertEqual(data["source"], "versioned_local_synthetic_fixture")
        self.assertEqual(data["population_status"], "synthetic_fixtures_loaded")
        self.assertIn("not real failures", data["explanation"])
        self.assertNotIn("expected_review_label", body.decode())

    def test_separate_pure_services_match_wire_contract(self):
        for path, builder in [
            ("/api/v1/status", services.status),
            ("/api/v1/scope", services.scope),
            ("/api/v1/cases", services.cases),
        ]:
            with self.subTest(path=path):
                _, _, body = request(path)
                self.assertEqual(json.loads(body)["data"], builder(self.charter))

    def test_contract_lists_only_real_routes_and_get_head(self):
        _, _, body = request("/api/v1/contract")
        data = json.loads(body)["data"]
        self.assertEqual(set(data["routes"]), set(api_v1.ROUTE_DESCRIPTIONS))
        self.assertEqual(data["allowed_methods"], ["GET", "HEAD"])
        self.assertFalse(data["limits"]["write_endpoints"])
        self.assertTrue(data["limits"]["case_fixtures_loaded"])
        for route in data["routes"].values():
            self.assertEqual(route["methods"], ["GET", "HEAD"])
            self.assertTrue(route["read_only"])

    def test_unspecified_version_and_resources_do_not_alias_v1(self):
        for path in ("/api", "/api/", "/api/v2/status", "/api/v1", "/api/v1/",
                     "/api/v1/workorders", "/api/v1/status/"):
            with self.subTest(path=path):
                status, headers, body = request(path)
                if path.startswith("/api/"):
                    self.assertEqual(headers["Content-Type"], api_v1.API_MEDIA_TYPE)
                    self.assertEqual(json.loads(body)["error"]["code"], "not_found")
                self.assertEqual(status, "404 Not Found")

    def test_unsupported_methods_fail_closed_with_json(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, body = request("/api/v1/cases", method)
                self.assertEqual(status, "405 Method Not Allowed")
                self.assertEqual(headers["Content-Type"], api_v1.API_MEDIA_TYPE)
                self.assertEqual(headers["Allow"], "GET, HEAD")
                self.assertEqual(json.loads(body)["error"]["code"], "method_not_allowed")

    def test_head_returns_no_body_with_get_content_length(self):
        for path in api_v1.ROUTE_DESCRIPTIONS:
            with self.subTest(path=path):
                gs, gh, gb = request(path)
                hs, hh, hb = request(path, "HEAD")
                self.assertEqual((gs, hs), ("200 OK", "200 OK"))
                self.assertEqual(hb, b"")
                self.assertEqual(gh["Content-Length"], hh["Content-Length"])
                self.assertEqual(int(gh["Content-Length"]), len(gb))

    def test_json_security_headers_no_cors(self):
        _, headers, _ = request("/api/v1/status")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_invalid_charter_fails_closed_with_non_sensitive_503(self):
        with mock.patch("reliability_intelligence.web.load_charter",
                        side_effect=InvalidCharter("secret=NEVER_DISCLOSE")):
            status, headers, body = request("/api/v1/status")
        self.assertEqual(status, "503 Service Unavailable")
        self.assertEqual(headers["Content-Type"], api_v1.API_MEDIA_TYPE)
        self.assertEqual(json.loads(body)["error"]["code"], "charter_invalid")
        self.assertNotIn(b"NEVER_DISCLOSE", body)

    def test_query_string_does_not_enable_filters_or_data(self):
        _, _, plain = request("/api/v1/cases")
        _, _, with_query = request("/api/v1/cases", query="tenant=minn-dak&include=private")
        self.assertEqual(with_query, plain)

    def test_contract_serializer_is_deterministic(self):
        payload = api_v1.data_for_path("/api/v1/status", self.charter)
        self.assertEqual(api_v1.serialize(payload), api_v1.serialize(payload))
        self.assertTrue(api_v1.serialize(payload).endswith(b"\n"))

    def test_no_endpoint_provides_mutation_path(self):
        for route in api_v1.ROUTE_DESCRIPTIONS:
            self.assertTrue(route.startswith("/api/v1/"))
        for method in ("POST", "DELETE"):
            status, _, _ = request("/api/v1/scope", method)
            self.assertEqual(status, "405 Method Not Allowed")

    def test_ui_is_unchanged_and_not_an_api_client(self):
        status, headers, body = request("/")
        self.assertEqual(status, "200 OK")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"Maintenance intelligence that keeps people in control", body)
        self.assertNotIn(b"fetch(", body)


if __name__ == "__main__":
    unittest.main()
