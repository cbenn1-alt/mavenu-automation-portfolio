"""V7 structured failures and safe diagnostic negative-path verification.

No actual errors, personal data, real customers, external integrations or
persistent logs are required. A single run exercises synthetic injections.
"""

import contextlib
import io
import json
import logging
import re
import unittest
from unittest import mock
from wsgiref.util import setup_testing_defaults

from reliability_intelligence import api_v1, diagnostics, services
from reliability_intelligence.__main__ import main
from reliability_intelligence.charter import InvalidCharter, load_charter
from reliability_intelligence.fixtures import InvalidFixture
from reliability_intelligence.web import app


def request(path="/", method="GET", query="", secret=None):
    env = {}
    setup_testing_defaults(env)
    env["REQUEST_METHOD"] = method
    env["PATH_INFO"] = path
    env["QUERY_STRING"] = query
    if secret is not None:
        env["HTTP_AUTHORIZATION"] = "Bearer " + secret
    response = {}

    def respond(status, headers, exc_info=None):
        response["status"] = status
        response["headers"] = dict(headers)

    response["body"] = b"".join(app(env, respond))
    return response


class V7DiagnosticTests(unittest.TestCase):
    def test_catalog_is_nonempty_and_bounded(self):
        self.assertGreaterEqual(len(diagnostics.CATALOG), 10)
        self.assertTrue(all(re.fullmatch(r"[a-z_]+", code) for code in diagnostics.CATALOG))

    def test_diagnostics_have_exact_allowlisted_structure(self):
        record = diagnostics.event("fixture_invalid", stage="fixture", surface="api")
        self.assertEqual(set(record), {
            "schema_version", "diagnostic_id", "id_semantics", "code",
            "level", "stage", "surface", "status", "message",
            "synthetic_only", "simulated_injection",
            "exception_details_recorded", "request_contents_recorded",
            "persistent_log_storage",
        })
        self.assertEqual(record["status"], 503)
        self.assertEqual(record["level"], "error")
        self.assertTrue(record["synthetic_only"])

    def test_diagnostic_fingerprints_are_reproducible_not_unique(self):
        a = diagnostics.event("not_found", stage="routing", surface="api")
        b = diagnostics.event("not_found", stage="routing", surface="api")
        c = diagnostics.event("not_found", stage="routing", surface="ui")
        self.assertEqual(a["diagnostic_id"], b["diagnostic_id"])
        self.assertNotEqual(a["diagnostic_id"], c["diagnostic_id"])
        self.assertRegex(a["diagnostic_id"], r"^SYN-DIAG-[a-f0-9]{16}$")
        self.assertIn("not_unique_occurrence", a["id_semantics"])

    def test_unknown_diagnostic_code_rejected(self):
        with self.assertRaises(ValueError):
            diagnostics.event("user_supplied_exfiltrate", stage="routing", surface="api")

    def test_unknown_stage_or_surface_rejected(self):
        for stage, surface in (("/etc/passwd", "api"), ("routing", "customer"), ("routing", "https://secret")):
            with self.subTest(stage=stage, surface=surface):
                with self.assertRaises(ValueError):
                    diagnostics.event("not_found", stage=stage, surface=surface)

    def test_non_boolean_simulation_flag_rejected(self):
        with self.assertRaises(ValueError):
            diagnostics.event("not_found", stage="routing", surface="api", simulated="true")

    def test_logger_emits_one_valid_json_line_without_exceptions(self):
        with mock.patch.object(diagnostics.LOGGER, "log") as log:
            event = diagnostics.emit("fixture_invalid", stage="fixture", surface="api")
        log.assert_called_once()
        args, kwargs = log.call_args
        self.assertEqual(args[0], logging.ERROR)
        self.assertEqual(json.loads(args[1]), event)
        self.assertEqual(kwargs, {})
        self.assertNotIn("traceback", args[1].lower())

    def test_no_persistent_file_or_request_payload_in_demo(self):
        demo = diagnostics.diagnostic_demo()
        self.assertEqual(demo["sample_count"], 6)
        self.assertTrue(demo["simulated"])
        self.assertFalse(demo["persistent_log_created"])
        self.assertFalse(demo["customer_data_used"])
        self.assertFalse(demo["actual_incidents_observed"])
        self.assertTrue(all(event["simulated_injection"] for event in demo["samples"]))

    def test_diagnostic_demo_is_deterministic(self):
        self.assertEqual(diagnostics.diagnostic_demo(), diagnostics.diagnostic_demo())

    def test_cli_diagnose_json_synthetic_report(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["diagnose", "--json"])
        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report, diagnostics.diagnostic_demo())

    def test_cli_diagnose_readable_output(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["diagnose"])
        self.assertEqual(result, 0)
        self.assertIn("simulated negative-path catalog", stdout.getvalue())
        self.assertIn("No customer data", stdout.getvalue())

    def test_api_not_found_has_structured_diagnostic(self):
        with mock.patch.object(diagnostics.LOGGER, "log") as log:
            response = request("/api/v9/sensitive?token=should-not-appear", query="password=secret-value")
        self.assertEqual(response["status"], "404 Not Found")
        self.assertEqual(json.loads(response["body"])["error"]["code"], "not_found")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "not_found")
        recorded = json.loads(log.call_args.args[1])
        self.assertEqual(recorded["code"], "not_found")
        self.assertNotIn("secret-value", log.call_args.args[1])
        self.assertNotIn("should-not-appear", log.call_args.args[1])

    def test_http_method_rejection_has_diagnostic(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method), mock.patch.object(diagnostics.LOGGER, "log") as log:
                response = request("/api/v1/demo", method)
                self.assertEqual(response["status"], "405 Method Not Allowed")
                self.assertEqual(response["headers"]["Allow"], "GET, HEAD")
                self.assertEqual(response["headers"]["X-Diagnostic-Code"], "method_not_allowed")
                self.assertEqual(json.loads(log.call_args.args[1])["status"], 405)

    def test_fixture_integrity_failure_is_sanitized_and_logged(self):
        with (mock.patch("reliability_intelligence.services.load_fixture_set",
                         side_effect=InvalidFixture("credential=secret-key /private/workorders")),
              mock.patch.object(diagnostics.LOGGER, "log") as log):
            response = request("/api/v1/cases", secret="super-secret-token")
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "fixture_invalid")
        emitted = log.call_args.args[1]
        combined = emitted + response["body"].decode() + json.dumps(response["headers"])
        for forbidden in ("secret-key", "super-secret-token", "/private/workorders"):
            self.assertNotIn(forbidden, combined)

    def test_invalid_charter_fail_closed_api_and_ui(self):
        with mock.patch("reliability_intelligence.web.load_charter", side_effect=InvalidCharter("real-person-email")):
            for path, code in (("/api/v1/status", "charter_invalid"), ("/", "charter_invalid")):
                with self.subTest(path=path), mock.patch.object(diagnostics.LOGGER, "log") as log:
                    response = request(path)
                    self.assertEqual(response["status"], "503 Service Unavailable")
                    self.assertEqual(response["headers"]["X-Diagnostic-Code"], code)
                    self.assertNotIn("real-person-email", response["body"].decode())
                    self.assertNotIn("real-person-email", log.call_args.args[1])

    def test_contract_shape_failure_gets_structured_503(self):
        with (mock.patch("reliability_intelligence.api_v1.data_for_path", side_effect=ValueError("raw customer key")),
              mock.patch.object(diagnostics.LOGGER, "log") as log):
            response = request("/api/v1/demo")
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "contract_failure")
        self.assertEqual(json.loads(response["body"])["error"]["code"], "contract_failure")
        self.assertNotIn("raw customer key", log.call_args.args[1])

    def test_unexpected_api_runtime_failure_gets_sanitized_500(self):
        with (mock.patch("reliability_intelligence.api_v1.data_for_path", side_effect=RuntimeError("secret_internal_exception")),
              mock.patch.object(diagnostics.LOGGER, "log") as log):
            response = request("/api/v1/demo")
        self.assertEqual(response["status"], "500 Internal Server Error")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "internal_failure")
        self.assertEqual(json.loads(response["body"])["error"]["code"], "internal_failure")
        self.assertNotIn("secret_internal_exception", log.call_args.args[1])

    def test_unexpected_browser_runtime_failure_gets_sanitized_500(self):
        with (mock.patch("reliability_intelligence.web.render_page", side_effect=RuntimeError("private stack trace")),
              mock.patch.object(diagnostics.LOGGER, "log") as log):
            response = request("/workflow")
        self.assertEqual(response["status"], "500 Internal Server Error")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "internal_failure")
        self.assertNotIn(b"private stack trace", response["body"])
        self.assertNotIn("private stack trace", log.call_args.args[1])

    def test_static_stylesheet_error_returns_stable_metadata(self):
        with (mock.patch("reliability_intelligence.web.CSS_PATH") as path,
              mock.patch.object(diagnostics.LOGGER, "log")):
            path.read_bytes.side_effect = OSError("secret local location")
            response = request("/assets/style.css")
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "stylesheet_unavailable")
        self.assertNotIn("secret local location", response["body"].decode())

    def test_unknown_ui_path_logged_without_path_in_event(self):
        with mock.patch.object(diagnostics.LOGGER, "log") as log:
            response = request("/private/unapproved/tenant-secret", query="api_key=EXFIL")
        self.assertEqual(response["status"], "404 Not Found")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "ui_route_not_found")
        self.assertNotIn("EXFIL", log.call_args.args[1])
        self.assertNotIn("tenant-secret", log.call_args.args[1])

    def test_head_error_retains_length_without_response_body(self):
        for path in ("/api/v9/status", "/does-not-exist"):
            with self.subTest(path=path), mock.patch.object(diagnostics.LOGGER, "log"):
                get_response = request(path)
                head_response = request(path, "HEAD")
                self.assertEqual(head_response["body"], b"")
                self.assertEqual(get_response["headers"]["Content-Length"],
                                 head_response["headers"]["Content-Length"])
                self.assertEqual(get_response["headers"]["X-Diagnostic-Code"],
                                 head_response["headers"]["X-Diagnostic-Code"])

    def test_successful_api_response_does_not_claim_diagnostic_failure(self):
        response = request("/api/v1/status")
        self.assertEqual(response["status"], "200 OK")
        self.assertNotIn("X-Diagnostic-Code", response["headers"])

    def test_status_explicitly_discloses_nonpersistent_diagnostics(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["status", "--json"]), 0)
        status = json.loads(stdout.getvalue())
        self.assertEqual(status["increment"], "V9")
        self.assertEqual(status["api_schema_version"], "1.3.0")
        self.assertEqual(status["diagnostic_schema_version"], "1.0.0")
        self.assertFalse(status["diagnostic_logs_persistent"])
        self.assertFalse(status["production_ready"])

    def test_service_status_is_not_equipment_health(self):
        s = services.status(load_charter())
        self.assertEqual(s["increment"], "V9")
        self.assertTrue(s["structured_failure_diagnostics_available"])
        self.assertFalse(s["operational_data_loaded"])
        self.assertFalse(s["ot_or_cmms_writes_enabled"])

    def test_fixture_failure_on_ui_is_sanitized_with_diagnostic(self):
        with (mock.patch("reliability_intelligence.web.load_fixture_set",
                         side_effect=InvalidFixture("employee_id=42")),
              mock.patch.object(diagnostics.LOGGER, "log") as log):
            response = request("/workbench")
        self.assertEqual(response["status"], "503 Service Unavailable")
        self.assertEqual(response["headers"]["X-Diagnostic-Code"], "fixture_invalid")
        self.assertNotIn("employee_id", log.call_args.args[1])

    def test_diagnostic_level_warning_for_client_errors(self):
        with mock.patch.object(diagnostics.LOGGER, "log") as log:
            request("/api/v3/status")
        self.assertEqual(log.call_args.args[0], logging.WARNING)

    def test_allowlisted_json_is_ascii_single_line(self):
        with mock.patch.object(diagnostics.LOGGER, "log") as log:
            diagnostics.emit("ui_route_not_found", stage="routing", surface="ui")
        message = log.call_args.args[1]
        self.assertEqual(len(message.splitlines()), 1)
        self.assertTrue(message.isascii())
        self.assertEqual(json.loads(message)["exception_details_recorded"], False)


if __name__ == "__main__":
    unittest.main()
