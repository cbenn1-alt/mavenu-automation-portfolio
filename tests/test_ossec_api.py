"""S02 — web pages + /api/ossec* endpoints (WSGI)."""
import json
from urllib.parse import urlencode

from tests.conftest import wsgi_call

from mavenu import ossec


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _post_json(app, path, payload):
    return wsgi_call(app, "POST", path, body=json.dumps(payload).encode())


def _post_form(app, path, fields):
    return wsgi_call(
        app, "POST", path, body=urlencode(fields).encode(),
        content_type="application/x-www-form-urlencoded")


def _body_json(resp):
    return json.loads(resp[2].decode("utf-8"))


class TestS02Pages:
    def test_dashboard_200(self, app):
        status, _, body = _get(app, "/project_s02")
        assert status == 200
        text = body.decode("utf-8")
        assert "S02" in text
        assert "must never be applied to systems without authorization" in text

    def test_concepts_page_200(self, app):
        status, _, body = _get(app, "/project_s02/concepts")
        assert status == 200
        text = body.decode("utf-8")
        assert "Privilege rings" in text
        assert "Process isolation" in text
        assert "Authentication flow" in text

    def test_lab_page_200(self, app):
        status, _, body = _get(app, "/project_s02/lab")
        assert status == 200
        text = body.decode("utf-8")
        assert "lab-vm-vulnerable" in text
        assert "Host-only" in text

    def test_findings_page_200(self, app):
        status, _, body = _get(app, "/project_s02/findings")
        assert status == 200
        text = body.decode("utf-8")
        assert "Weak credentials" in text
        assert "DETECTED" in text

    def test_baselines_page_200(self, app):
        status, _, body = _get(app, "/project_s02/baselines")
        assert status == 200
        text = body.decode("utf-8")
        assert "acct-02" in text
        assert "FAIL" in text and "PASS" in text

    def test_nav_links_present(self, app):
        _, _, body = _get(app, "/")
        text = body.decode("utf-8")
        assert "/project_s02" in text

    def test_seed_form(self, app):
        status, _, body = _post_form(app, "/project_s02/seed", {"seed": "7"})
        assert status == 200
        assert b"S02 demo seeded" in body


class TestOssecApi:
    def test_baselines_catalog(self, app):
        status, _, body = _get(app, "/api/ossec/baselines")
        data = _body_json((status, _, body))
        assert status == 200
        assert len(data["items"]) == 15
        assert data["coverage_gaps"] == []
        assert data["lab_only"] is True
        ids = {i["id"] for i in data["items"]}
        assert "acct-02" in ids and "perm-02" in ids

    def test_findings_catalog(self, app):
        status, _, body = _get(app, "/api/ossec/findings")
        data = _body_json((status, _, body))
        assert status == 200
        assert len(data["findings"]) == 6
        assert all(f["detected_on_vulnerable_fixture"]
                   for f in data["findings"])
        for f in data["findings"]:
            for field in ("description", "detection_method", "remediation",
                          "verification_method"):
                assert f[field], field

    def test_coverage(self, app):
        status, _, body = _get(app, "/api/ossec/coverage")
        data = _body_json((status, _, body))
        assert status == 200
        assert data["full_coverage"] is True
        assert data["baseline_items"] == 15

    def test_evaluate_vulnerable(self, app):
        status, _, body = _post_json(
            app, "/api/ossec/evaluate",
            {"state": ossec.vulnerable_state()})
        data = _body_json((status, _, body))
        assert status == 200
        assert data["summary"]["passed"] == 0
        assert data["summary"]["total"] == 15

    def test_evaluate_hardened(self, app):
        status, _, body = _post_json(
            app, "/api/ossec/evaluate",
            {"state": ossec.hardened_state()})
        data = _body_json((status, _, body))
        assert status == 200
        assert data["summary"]["passed"] == 15

    def test_evaluate_rejects_bad_state(self, app):
        status, _, body = _post_json(
            app, "/api/ossec/evaluate", {"state": {"label": "broken"}})
        assert status == 422

    def test_evaluate_rejects_non_object(self, app):
        status, _, _ = _post_json(app, "/api/ossec/evaluate", {"state": "x"})
        assert status == 422

    def test_remediate_full(self, app):
        status, _, body = _post_json(
            app, "/api/ossec/remediate",
            {"state": ossec.vulnerable_state()})
        data = _body_json((status, _, body))
        assert status == 200
        assert data["summary_before"]["passed"] == 0
        assert data["summary_after"]["passed"] == 15
        assert len(data["findings"]) == 6

    def test_remediate_rejects_unknown_finding(self, app):
        status, _, _ = _post_json(
            app, "/api/ossec/remediate",
            {"state": ossec.vulnerable_state(), "finding_ids": ["nope"]})
        assert status == 422

    def test_seed_api(self, app):
        status, _, body = _post_json(app, "/api/ossec/seed", {"seed": 7})
        data = _body_json((status, _, body))
        assert status == 200
        assert data["seeded"]["findings"] == 6
        assert data["seeded"]["baseline_runs"] == 2
