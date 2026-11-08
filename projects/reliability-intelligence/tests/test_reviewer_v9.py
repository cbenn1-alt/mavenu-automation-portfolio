"""V9 reviewer runbook/replay harness regressions; not a human sign-off."""

import importlib.util
import json
import pathlib
import unittest

PROJECT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v9_replay_script", PROJECT / "scripts" / "replay_v9.py")
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class V9ReviewerHarnessTests(unittest.TestCase):
    def test_fixed_ui_and_api_routes(self):
        self.assertEqual(len(replay.UI_PATHS), 5)
        self.assertEqual(len(replay.API_PATHS), 5)
        self.assertIn("/workflow", replay.UI_PATHS)
        self.assertIn("/api/v1/demo", replay.API_PATHS)

    def test_all_network_targets_are_relative_first_party_routes(self):
        for value in replay.UI_PATHS + replay.API_PATHS:
            self.assertTrue(value.startswith("/"))
            self.assertNotIn("://", value)

    def test_unexpected_http_path_fails_before_network(self):
        with self.assertRaises(ValueError):
            replay._http(8765, "/api/v1/unknown", "GET")

    def test_unexpected_http_method_fails_before_network(self):
        with self.assertRaises(ValueError):
            replay._http(8765, "/api/v1/demo", "PUT")

    def test_valid_api_envelope_helper(self):
        payload = {
            "api_version": "v1", "schema_version": "1.3.0",
            "resource": "demo", "data": {"real_work_orders_written": False},
        }
        self.assertEqual(
            replay._json_document(200, json.dumps(payload).encode(), "demo"),
            payload["data"],
        )

    def test_api_envelope_rejects_version_drift(self):
        for key, bad in (("api_version", "v2"), ("schema_version", "2.0.0")):
            with self.subTest(key=key):
                payload = {"api_version": "v1", "schema_version": "1.3.0",
                           "resource": "status", "data": {}}
                payload[key] = bad
                with self.assertRaises(ValueError):
                    replay._json_document(200, json.dumps(payload).encode(), "status")

    def test_api_envelope_rejects_wrong_resource(self):
        payload = {"api_version": "v1", "schema_version": "1.3.0",
                   "resource": "cases", "data": {}}
        with self.assertRaises(ValueError):
            replay._json_document(200, json.dumps(payload).encode(), "demo")

    def test_api_envelope_rejects_wrong_http_status(self):
        payload = {"api_version": "v1", "schema_version": "1.3.0",
                   "resource": "demo", "data": {}}
        with self.assertRaises(ValueError):
            replay._json_document(503, json.dumps(payload).encode(), "demo")

    def test_api_envelope_rejects_malformed_json(self):
        with self.assertRaises(ValueError):
            replay._json_document(200, b"{not-a-json-object", "demo")

    def test_api_envelope_limits_response_size(self):
        with self.assertRaises(ValueError):
            replay._json_document(200, b" " * (replay.MAX_BODY_BYTES + 1), "demo")

    def test_production_source_and_v8_baseline_are_preserved(self):
        baseline = json.loads((PROJECT / "docs/releases/V8_BASELINE.json").read_text())
        self.assertGreaterEqual(baseline["minimum_test_count"], 140)
        self.assertGreaterEqual(baseline["minimum_total_percent"], 84.5)
        self.assertFalse(baseline["product_owner_signoff"])

    def test_readme_and_runbook_disclose_unapproved_customer_access(self):
        docs = [
            "README.md", "docs/SETUP_V9.md", "docs/REVIEWER_REPLAY_V9.md",
            "docs/EXCLUSIONS_V9.md", "docs/DEMO_V9.md",
        ]
        for relative in docs:
            with self.subTest(file=relative):
                content = (PROJECT / relative).read_text(encoding="utf-8").lower()
                self.assertIn("synthetic", content)
        exclusions = (PROJECT / "docs/EXCLUSIONS_V9.md").read_text().lower()
        for keyword in ("customer", "plc", "scada", "reviewer", "financial"):
            self.assertIn(keyword, exclusions)

    def test_review_record_template_is_unsigned_and_unaccepted(self):
        template = json.loads((PROJECT / "docs/V9_REVIEWER_RECORD_TEMPLATE.json").read_text())
        self.assertEqual(template["increment"], "V9")
        self.assertIsNone(template["reviewer_name"])
        self.assertIsNone(template["review_date_utc"])
        self.assertIsNone(template["reviewer_signature"])
        self.assertFalse(template["independent_human_replay_completed"])
        self.assertFalse(template["formal_acceptance_granted"])


if __name__ == "__main__":
    unittest.main()
