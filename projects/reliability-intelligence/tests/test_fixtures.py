"""V5 synthetic fixture provenance, schema, reference integrity and safety tests."""

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from reliability_intelligence import services
from reliability_intelligence import fixtures
from reliability_intelligence.charter import load_charter
from reliability_intelligence.web import app
from wsgiref.util import setup_testing_defaults


def request(path):
    env = {}
    setup_testing_defaults(env)
    env["PATH_INFO"] = path
    env["REQUEST_METHOD"] = "GET"
    out = {}

    def start_response(status, headers, exc_info=None):
        out["status"] = status
        out["headers"] = dict(headers)

    out["body"] = b"".join(app(env, start_response))
    return out


class V5FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((fixtures.FIXTURE_DIR / "manifest.json").read_text())
        cls.dataset = fixtures.load_fixture_set()
        cls.labels = fixtures.load_reference_labels()

    def test_manifest_declares_synthetic_origin_and_no_customer_inputs(self):
        manifest = self.manifest
        self.assertTrue(manifest["synthetic_only"])
        self.assertFalse(manifest["customer_data_used"])
        self.assertFalse(manifest["production_authorized"])
        self.assertFalse(manifest["independent_domain_validation"])
        self.assertEqual(manifest["source_systems"], [])

    def test_fixture_files_have_pinned_git_blob_ids(self):
        self.assertEqual(
            fixtures._git_blob_id((fixtures.FIXTURE_DIR / "cases.json").read_bytes()),
            self.manifest["case_git_blob_sha1"],
        )
        self.assertEqual(
            fixtures._git_blob_id((fixtures.FIXTURE_DIR / "reference_labels.json").read_bytes()),
            self.manifest["reference_labels_git_blob_sha1"],
        )

    def test_six_artificial_assets_and_twelve_case_records(self):
        self.assertEqual(len(self.dataset["assets"]), 6)
        self.assertEqual(len(self.dataset["records"]), 12)
        self.assertEqual(self.dataset["fixture_set_id"], self.manifest["fixture_set_id"])

    def test_all_ids_are_unique_and_records_reference_known_assets(self):
        assets = {a["asset_id"] for a in self.dataset["assets"]}
        cases = [r["case_id"] for r in self.dataset["records"]]
        works = [r["work_order_ref"] for r in self.dataset["records"]]
        self.assertEqual(len(assets), 6)
        self.assertEqual(len(set(cases)), 12)
        self.assertEqual(len(set(works)), 12)
        self.assertTrue(all(r["asset_id"] in assets for r in self.dataset["records"]))

    def test_all_cases_have_canonical_utc_and_bounded_numeric_fields(self):
        for row in self.dataset["records"]:
            self.assertRegex(row["occurred_at_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertGreaterEqual(row["repair_cost_usd"], 0)
            self.assertGreaterEqual(row["downtime_hours"], 0)
            self.assertTrue(row["synthetic"])
            self.assertEqual(row["review_state"], "fixture_only")

    def test_cases_cover_repeat_history_and_missing_evidence_scenarios(self):
        case_ids = {r["case_id"] for r in self.dataset["records"]}
        self.assertIn("SYN-CASE-003", case_ids)
        self.assertIn("SYN-CASE-004", case_ids)
        self.assertTrue(any(r["evidence_refs"] == [] for r in self.dataset["records"]))
        label_names = {x["expected_review_label"] for x in self.labels["records"]}
        self.assertIn("repeat_history_candidate", label_names)
        self.assertIn("missing_evidence", label_names)

    def test_reference_labels_complete_but_not_independently_validated(self):
        self.assertFalse(self.labels["independently_validated"])
        self.assertEqual({r["case_id"] for r in self.labels["records"]},
                         {r["case_id"] for r in self.dataset["records"]})

    def test_api_never_exposes_seeded_reference_labels(self):
        out = request("/api/v1/cases")
        self.assertEqual(out["status"], "200 OK")
        self.assertEqual(len(json.loads(out["body"])["data"]["items"]), 12)
        for forbidden in ("expected_review_label", "repeat_history_candidate",
                          "independently_validated", "labels_authored_for_demonstration"):
            self.assertNotIn(forbidden.encode(), out["body"])

    def test_ui_never_exposes_seeded_reference_labels(self):
        out = request("/workbench")
        self.assertEqual(out["status"], "200 OK")
        self.assertIn(b"SYN-CASE-012", out["body"])
        self.assertNotIn(b"repeat_history_candidate", out["body"])

    def test_invalid_manifest_reference_fails_closed(self):
        changed = copy.deepcopy(self.manifest)
        changed["case_git_blob_sha1"] = "0" * 40
        with mock.patch("reliability_intelligence.fixtures._manifest", return_value=changed):
            with self.assertRaises(fixtures.InvalidFixture):
                fixtures.load_fixture_set()

    def test_mutated_case_dataset_fails_closed(self):
        altered = copy.deepcopy(self.dataset)
        altered["records"][0]["synthetic"] = False
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_fixture_data(altered, self.manifest)

    def test_duplicate_case_ids_fail_closed(self):
        altered = copy.deepcopy(self.dataset)
        altered["records"][1]["case_id"] = altered["records"][0]["case_id"]
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_fixture_data(altered, self.manifest)

    def test_unknown_asset_references_fail_closed(self):
        altered = copy.deepcopy(self.dataset)
        altered["records"][0]["asset_id"] = "SYN-ASSET-999"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_fixture_data(altered, self.manifest)

    def test_non_utc_timestamp_fails_closed(self):
        altered = copy.deepcopy(self.dataset)
        altered["records"][0]["occurred_at_utc"] = "2026-01-05 12:00 local"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_fixture_data(altered, self.manifest)

    def test_bad_finite_number_or_booleans_fail_closed(self):
        for value in (-1, float("nan"), float("inf"), True, "100"):
            with self.subTest(value=str(value)):
                altered = copy.deepcopy(self.dataset)
                altered["records"][0]["repair_cost_usd"] = value
                with self.assertRaises(fixtures.InvalidFixture):
                    fixtures.validate_fixture_data(altered, self.manifest)

    def test_personal_data_field_is_not_accepted(self):
        altered = copy.deepcopy(self.dataset)
        altered["records"][0]["employee_email"] = "someone@example.org"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_fixture_data(altered, self.manifest)

    def test_unrecognized_code_or_work_order_fails_closed(self):
        for field, value in (("failure_code", "real_plant_alarm"), ("work_order_ref", "REAL-WO-001")):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.dataset)
                altered["records"][0][field] = value
                with self.assertRaises(fixtures.InvalidFixture):
                    fixtures.validate_fixture_data(altered, self.manifest)

    def test_reference_label_mismatch_fails_closed(self):
        altered = copy.deepcopy(self.labels)
        altered["records"][0]["case_id"] = "SYN-CASE-999"
        with self.assertRaises(fixtures.InvalidFixture):
            fixtures.validate_reference_labels(altered, self.dataset)

    def test_service_cannot_load_under_non_synthetic_charter(self):
        charter = copy.deepcopy(load_charter())
        charter["data_and_safety"]["data_mode"] = "CUSTOMER_DATA"
        with self.assertRaises(ValueError):
            services.cases(charter)

    def test_corrupted_fixture_returns_non_sensitive_api_503(self):
        with mock.patch("reliability_intelligence.services.load_fixture_set",
                        side_effect=fixtures.InvalidFixture("Sensitive internal path: /secret")):
            out = request("/api/v1/cases")
        self.assertEqual(out["status"], "503 Service Unavailable")
        self.assertEqual(json.loads(out["body"])["error"]["code"], "fixture_invalid")
        self.assertNotIn(b"/secret", out["body"])

    def test_corrupted_fixture_disables_browser_workbench(self):
        with mock.patch("reliability_intelligence.web.load_fixture_set",
                        side_effect=fixtures.InvalidFixture("internal details")):
            out = request("/workbench")
        self.assertEqual(out["status"], "503 Service Unavailable")
        self.assertNotIn(b"internal details", out["body"])

    def test_status_distinguishes_fixture_availability_from_real_data(self):
        data = services.status(load_charter())
        self.assertTrue(data["synthetic_fixtures_available"])
        self.assertFalse(data["operational_data_loaded"])
        self.assertFalse(data["production_ready"])
        self.assertFalse(data["model_present"])
        self.assertEqual(data["increment"], "V8")

    def test_synthetic_case_service_is_deterministic(self):
        charter = load_charter()
        self.assertEqual(services.cases(charter), services.cases(charter))


if __name__ == "__main__":
    unittest.main()
