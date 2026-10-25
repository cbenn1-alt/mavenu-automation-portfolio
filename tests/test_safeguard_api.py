"""N03 Safeguard — API and page tests.

All data is synthetic. Exercises the /project_n03* pages and the
/api/safeguard* endpoints through the WSGI test client.
"""
import json

import pytest

from tests.conftest import wsgi_call

# conftest.wsgi_call does not carry QUERY_STRING; this variant does.
import io as _io


def _get_qs(app, path, qs):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": qs,
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": "0",
        "wsgi.input": _io.BytesIO(b""),
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
    }
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    out = b"".join(app(environ, start_response))
    return int(captured["status"].split()[0]), captured["headers"], out

INTAKE = {
    "case_ref": "API-CB-1",
    "category": "cyberbullying",
    "reporter_role": "synthetic test parent",
    "summary": "SYNTHETIC TEST SCENARIO. Non-graphic API test summary.",
    "involves_minor": True,
}


def _post(app, path, payload):
    return wsgi_call(app, "POST", path, body=json.dumps(payload).encode())


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _new_case(app):
    status, _, body = _post(app, "/api/safeguard/cases", INTAKE)
    assert status == 201, body
    return json.loads(body)["case"]


class TestPages:
    def test_framework_page(self, app):
        status, _, body = _get(app, "/project_n03")
        assert status == 200
        text = body.decode()
        assert "N03" in text
        assert "SYNTHETIC CASES ONLY" in text
        assert "refers — it does not pursue" in text

    def test_playbooks_page_lists_eight(self, app):
        status, _, body = _get(app, "/project_n03/playbooks")
        assert status == 200
        text = body.decode()
        for cat in ("cyberbullying", "sextortion", "swatting",
                    "child_sexual_exploitation"):
            assert f"/project_n03/playbooks/{cat}" in text

    def test_playbook_detail_page(self, app):
        status, _, body = _get(app, "/project_n03/playbooks/cyberstalking")
        assert status == 200
        assert "Cyberstalking" in body.decode()

    def test_playbook_detail_404(self, app):
        status, _, _ = _get(app, "/project_n03/playbooks/nope")
        assert status == 404

    def test_preservation_page(self, app):
        status, _, body = _get(app, "/project_n03/preservation")
        assert status == 200
        assert "Do not delete anything" in body.decode()
        status, _, body = _get_qs(app, "/project_n03/preservation",
                                "category=sextortion")
        assert status == 200
        assert "Preserve threats before blocking" in body.decode()

    def test_reporting_page(self, app):
        status, _, body = _get(app, "/project_n03/reporting")
        assert status == 200
        text = body.decode()
        assert "NCMEC CyberTipline" in text
        assert "FBI IC3" in text

    def test_referrals_page(self, app):
        status, _, body = _get(app, "/project_n03/referrals")
        assert status == 200
        assert "Referral Directory" in body.decode()

    def test_cases_page_empty(self, app):
        status, _, body = _get(app, "/project_n03/cases")
        assert status == 200
        assert "No cases yet" in body.decode()

    def test_demo_submit_page(self, app):
        status, _, body = wsgi_call(app, "POST", "/project_n03/demo")
        assert status == 200
        text = body.decode()
        assert "guided demo complete" in text
        # The demo case page renders.
        status, _, body = _get(app, "/project_n03/cases")
        assert status == 200
        assert "DEMO-CB-" in body.decode()


class TestApi:
    def test_playbooks_list(self, app):
        status, _, body = _get(app, "/api/safeguard/playbooks")
        assert status == 200
        data = json.loads(body)
        assert data["synthetic"] is True
        assert len(data["playbooks"]) == 8

    def test_playbook_detail_has_cited_steps(self, app):
        status, _, body = _get(app, "/api/safeguard/playbooks/sextortion")
        assert status == 200
        steps = json.loads(body)["playbook"]["steps"]
        assert steps
        assert all(s["authority"].strip() for s in steps)

    def test_intake_and_detail(self, app):
        case = _new_case(app)
        assert case["safety_status"] == "minor-safeguarding"
        assert case["stage"] == "triaged"
        status, _, body = _get(app, f"/api/safeguard/cases/{case['id']}")
        assert status == 200
        detail = json.loads(body)["case"]
        assert len(detail["checklist"]) == len(detail["playbook"]["steps"])
        assert detail["guidance"]

    def test_intake_validation_422(self, app):
        status, _, body = _post(app, "/api/safeguard/cases",
                                {**INTAKE, "category": "nope"})
        assert status == 422
        # Duplicate case_ref within the same database → 422.
        status, _, _ = _post(app, "/api/safeguard/cases",
                             {**INTAKE, "case_ref": "API-DUP-1"})
        assert status == 201
        status, _, _ = _post(app, "/api/safeguard/cases",
                             {**INTAKE, "case_ref": "API-DUP-1"})
        assert status == 422

    def test_intake_rejects_graphic_summary_422(self, app):
        status, _, _ = _post(
            app, "/api/safeguard/cases",
            {**INTAKE, "case_ref": "API-GRAPHIC",
             "summary": "SYNTHETIC TEST with pornographic detail."})
        assert status == 422

    def test_emergency_triage_first(self, app):
        status, _, body = _post(app, "/api/safeguard/cases",
                                {**INTAKE, "case_ref": "API-SW-1",
                                 "category": "swatting",
                                 "immediate_danger": True,
                                 "involves_minor": False})
        assert status == 201
        case = json.loads(body)["case"]
        assert case["safety_status"] == "emergency"
        assert "EMERGENCY FIRST" in case["guidance"][0]

    def test_csam_intake_auto_refers_ncmec(self, app):
        status, _, body = _post(app, "/api/safeguard/cases",
                                {**INTAKE, "case_ref": "API-CSE-1",
                                 "category": "child_sexual_exploitation"})
        assert status == 201
        case = json.loads(body)["case"]
        status, _, body = _get(app, f"/api/safeguard/cases/{case['id']}")
        detail = json.loads(body)["case"]
        assert [r["org_key"] for r in detail["referrals"]] == ["ncmec_cybertipline"]

    def test_checklist_complete_and_skip(self, app):
        case = _new_case(app)
        step_id = json.loads(
            _get(app, f"/api/safeguard/cases/{case['id']}")[2]
        )["case"]["checklist"][0]["step_id"]
        status, _, body = _post(
            app, f"/api/safeguard/cases/{case['id']}/checklist/{step_id}",
            {"status": "done", "note": "screenshot saved"})
        assert status == 200
        assert json.loads(body)["item"]["status"] == "done"
        # Skip without reason → 422.
        step2 = json.loads(
            _get(app, f"/api/safeguard/cases/{case['id']}")[2]
        )["case"]["checklist"][1]["step_id"]
        status, _, _ = _post(
            app, f"/api/safeguard/cases/{case['id']}/checklist/{step2}",
            {"status": "skipped"})
        assert status == 422

    def test_referral_endpoint(self, app):
        case = _new_case(app)
        status, _, body = _post(app, f"/api/safeguard/cases/{case['id']}/referrals",
                                {"org_key": "fbi_ic3"})
        assert status == 201
        ref = json.loads(body)["referral"]
        assert "no outreach" in ref["guidance"]
        status, _, _ = _post(app, f"/api/safeguard/cases/{case['id']}/referrals",
                             {"org_key": "nope"})
        assert status == 422

    def test_findings_endpoint_attribution(self, app):
        case = _new_case(app)
        # unknown accepted
        status, _, body = _post(app, f"/api/safeguard/cases/{case['id']}/findings",
                                {"statement": "The sender's identity.",
                                 "claim_type": "inference",
                                 "status": "unknown",
                                 "confidence": "low"})
        assert status == 201
        # verified without evidence → 422
        status, _, _ = _post(app, f"/api/safeguard/cases/{case['id']}/findings",
                             {"statement": "A claim.",
                              "claim_type": "fact",
                              "status": "verified"})
        assert status == 422

    def test_preservation_api(self, app):
        status, _, body = _get(app, "/api/safeguard/preservation")
        assert status == 200
        assert json.loads(body)["checklist"]
        status, _, body = _get_qs(app, "/api/safeguard/preservation",
                                "category=nc_ii_abuse")
        assert status == 200
        items = json.loads(body)["checklist"]
        assert any("BEFORE filing" in i["detail"] for i in items)

    def test_reporting_guide_api(self, app):
        status, _, body = _get(app, "/api/safeguard/reporting-guide")
        assert status == 200
        assert len(json.loads(body)["guide"]) == 9

    def test_referral_directory_api(self, app):
        status, _, body = _get(app, "/api/safeguard/referral-directory")
        assert status == 200
        assert len(json.loads(body)["directory"]) == 10

    def test_demo_api(self, app):
        status, _, body = wsgi_call(app, "POST", "/api/safeguard/demo")
        assert status == 201
        demo = json.loads(body)["demo"]
        assert demo["synthetic"] is True
        assert demo["stage"] == "closed"

    def test_case_404(self, app):
        status, _, _ = _get(app, "/api/safeguard/cases/999999")
        assert status == 404

    def test_nav_links_n03(self, app):
        status, _, body = _get(app, "/project_n03")
        assert status == 200
        text = body.decode()
        for link in ("/project_n03/playbooks", "/project_n03/cases",
                     "/project_n03/preservation", "/project_n03/reporting",
                     "/project_n03/referrals"):
            assert link in text, link
