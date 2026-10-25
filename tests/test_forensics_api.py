"""S03 Digital Forensic Applications — web + API tests (WSGI test client).

All cases, fixtures, and evidence are synthetic. The synthetic-cases
directory is monkeypatched to a tmp dir so no repo files are touched.
"""
import json
import os

import pytest

import mavenu.web as web_module
from mavenu import forensics as f
from tests.conftest import wsgi_call


@pytest.fixture
def syndir(tmp_path, monkeypatch):
    d = str(tmp_path / "synthetic_cases")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(web_module, "SYNTHETIC_CASES_DIR", d)
    return d


def _post(app, path, payload):
    return wsgi_call(app, "POST", path, json.dumps(payload).encode())


def _get(app, path):
    return wsgi_call(app, "GET", path)


INTAKE = {
    "title": "Suspicious installer (synthetic API test)",
    "description": "API-level intake of a synthetic case.",
    "authorizer_name": "Synthetic API Authorizer",
    "authorization_ref": "AUTH-API-0001",
    "handling_plan": ["Intake", "Acquire", "Examine", "Analyze", "Report"],
}


def _intake_case(app):
    status, _, body = _post(app, "/api/forensics/cases", INTAKE)
    assert status == 201, body.decode()
    return json.loads(body)["case"]


class TestCaseIntakeApi:
    def test_intake_ok(self, app):
        status, _, body = _post(app, "/api/forensics/cases", INTAKE)
        assert status == 201
        data = json.loads(body)
        assert data["synthetic"] is True
        assert data["case"]["case_ref"].startswith("FOR-")
        assert data["case"]["status"] == "intake"

    def test_intake_invalid(self, app):
        bad = dict(INTAKE, authorizer_name="")
        status, _, body = _post(app, "/api/forensics/cases", bad)
        assert status == 422
        assert json.loads(body)["error"]["code"] == "validation_failed"

    def test_intake_bad_json(self, app):
        status, _, _ = wsgi_call(app, "POST", "/api/forensics/cases",
                                 b"{not json", content_type="application/json")
        assert status == 422

    def test_list_cases(self, app):
        _intake_case(app)
        status, _, body = _get(app, "/api/forensics/cases")
        assert status == 200
        assert len(json.loads(body)["cases"]) == 1

    def test_case_detail_404(self, app):
        status, _, body = _get(app, "/api/forensics/cases/9999")
        assert status == 404


class TestAcquireApi:
    def test_acquire_from_fixture(self, app, syndir):
        case = _intake_case(app)
        f.generate_synthetic_case(os.path.join(syndir, "manual1"))
        status, _, body = _post(
            app, f"/api/forensics/cases/{case['id']}/acquire",
            {"fixture": "manual1"})
        assert status == 201, body.decode()
        acq = json.loads(body)["acquisition"]
        assert acq["file_count"] == 3

    def test_acquire_unknown_fixture(self, app):
        case = _intake_case(app)
        status, _, _ = _post(
            app, f"/api/forensics/cases/{case['id']}/acquire",
            {"fixture": "does-not-exist"})
        assert status == 404

    def test_acquire_rejects_path_traversal(self, app):
        case = _intake_case(app)
        status, _, _ = _post(
            app, f"/api/forensics/cases/{case['id']}/acquire",
            {"fixture": "../secrets"})
        assert status == 422

    def test_second_acquire_conflicts(self, app, syndir):
        case = _intake_case(app)
        f.generate_synthetic_case(os.path.join(syndir, "manual2"))
        url = f"/api/forensics/cases/{case['id']}/acquire"
        assert _post(app, url, {"fixture": "manual2"})[0] == 201
        status, _, body = _post(app, url, {"fixture": "manual2"})
        assert status == 409
        assert json.loads(body)["error"]["code"] == "conflict"


def _run_demo(app, syndir):
    status, _, body = _post(app, "/api/forensics/demo", {})
    assert status == 201, body.decode()
    return json.loads(body)["demo"]


class TestDemoApi:
    def test_demo_runs_full_workflow(self, app, syndir):
        demo = _run_demo(app, syndir)
        assert demo["timeline_score"] == 1.0
        assert demo["timeline_matched"] == "5/5"
        assert demo["chain_ok"] is True
        assert demo["stage"] == "analyzed"
        assert demo["artifacts"] == {"files": 3, "log_events": 5, "carved": 1}

    def test_verify_endpoint_ok(self, app, syndir):
        demo = _run_demo(app, syndir)
        status, _, body = _get(
            app, f"/api/forensics/cases/{demo['case_id']}"
                 f"/acquisitions/{demo['acquisition_id']}/verify")
        assert status == 200
        integrity = json.loads(body)["integrity"]
        assert integrity["ok"] is True
        assert integrity["mismatches"] == []

    def test_artifacts_endpoint(self, app, syndir):
        demo = _run_demo(app, syndir)
        status, _, body = _get(app, f"/api/forensics/cases/{demo['case_id']}/artifacts")
        assert status == 200
        arts = json.loads(body)["artifacts"]
        assert len(arts) == 9
        assert {a["kind"] for a in arts} == {"file", "log_event", "carved"}

    def test_timeline_endpoint(self, app, syndir):
        demo = _run_demo(app, syndir)
        status, _, body = _get(app, f"/api/forensics/cases/{demo['case_id']}/timeline")
        assert status == 200
        tl = json.loads(body)["timeline"]
        assert len(tl) == 12
        assert tl[0]["ts"] <= tl[-1]["ts"]

    def test_chain_endpoint(self, app, syndir):
        demo = _run_demo(app, syndir)
        status, _, body = _get(app, f"/api/forensics/cases/{demo['case_id']}/chain")
        assert status == 200
        data = json.loads(body)
        assert data["verification"]["ok"] is True
        assert data["verification"]["entries"] == 7
        steps = [e["step"] for e in data["chain"]]
        assert steps[0] == "case.opened"
        assert "acquisition.complete" in steps


class TestHypothesisApi:
    def test_add_hypothesis_ok(self, app):
        case = _intake_case(app)
        status, _, body = _post(
            app, f"/api/forensics/cases/{case['id']}/hypotheses",
            {"statement": "The installer was executed.",
             "supporting": ["var/log/app.log#L3"],
             "contradicting": ["none-found-after-review"]})
        assert status == 201
        assert json.loads(body)["hypothesis"]["status"] == "open"

    def test_missing_contradicting_rejected(self, app):
        case = _intake_case(app)
        status, _, body = _post(
            app, f"/api/forensics/cases/{case['id']}/hypotheses",
            {"statement": "One-sided.", "supporting": ["a"], "contradicting": []})
        assert status == 422


class TestReportApi:
    def test_report_flow(self, app, syndir):
        status, _, body = _post(app, "/api/forensics/demo", {})
        demo = json.loads(body)["demo"]
        cid = demo["case_id"]

        # inference without confidence -> 422
        status, _, body = _post(
            app, f"/api/forensics/cases/{cid}/report",
            {"findings": [{"kind": "inference", "text": "Guess.",
                           "evidence": ["var/log/app.log#L1"]}]})
        assert status == 422

        findings = [
            {"kind": "fact",
             "text": "installer_update.exe was downloaded at 2026-10-20T14:02:11Z.",
             "evidence": ["var/log/app.log#L2"]},
            {"kind": "inference",
             "text": "The demo user executed the installer.",
             "evidence": ["var/log/app.log#L3"], "confidence": "high"},
            {"kind": "inference",
             "text": "Attribution beyond the demo user is unresolved.",
             "evidence": ["var/log/app.log#L1"], "confidence": "low"},
        ]
        status, _, body = _post(app, f"/api/forensics/cases/{cid}/report",
                                {"findings": findings})
        assert status == 201, body.decode()
        report = json.loads(body)["report"]
        assert report["audit"] == []
        assert "## Facts" in report["text"]
        assert "unresolved" in report["text"].lower()

        # GET latest report
        status, _, body = _get(app, f"/api/forensics/cases/{cid}/report")
        assert status == 200
        assert json.loads(body)["report"]["id"] == report["report_id"]

    def test_report_before_analysis_conflicts(self, app):
        case = _intake_case(app)  # stage: intake, not analyzed
        status, _, body = _post(
            app, f"/api/forensics/cases/{case['id']}/report",
            {"findings": [{"kind": "fact", "text": "t", "evidence": ["e"]}]})
        assert status == 409


class TestPages:
    def test_s03_page(self, app):
        status, _, body = _get(app, "/project_s03")
        assert status == 200
        text = body.decode()
        assert "S03" in text and "Synthetic data only" in text

    def test_cases_page(self, app):
        status, _, body = _get(app, "/project_s03/cases")
        assert status == 200
        assert "Cases" in body.decode()

    def test_case_page(self, app):
        case = _intake_case(app)
        status, _, body = _get(app, f"/project_s03/cases/{case['id']}")
        assert status == 200
        text = body.decode()
        assert case["case_ref"] in text
        assert "Synthetic authorization record" in text

    def test_case_page_404(self, app):
        status, _, _ = _get(app, "/project_s03/cases/9999")
        assert status == 404

    def test_demo_page(self, app, syndir):
        status, _, body = _post(app, "/project_s03/demo", {})
        assert status == 200
        assert "timeline_score" in body.decode()

    def test_nav_links_s03(self, app):
        status, _, body = _get(app, "/")
        assert status == 200
        assert 'href="/project_s03"' in body.decode()
