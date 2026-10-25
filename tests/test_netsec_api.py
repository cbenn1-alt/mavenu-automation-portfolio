"""S01 — Network Security: web pages + /api/netsec* endpoints (WSGI)."""
import json
from urllib.parse import urlencode
import io

from tests.conftest import wsgi_call

from mavenu import firewall as fw


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


class TestS01Pages:
    def test_dashboard_200(self, app):
        status, _, body = _get(app, "/project_s01")
        assert status == 200
        text = body.decode("utf-8")
        assert "S01" in text
        assert "Do not scan, probe, or test any network you do not own" in text

    def test_ruleset_page_200(self, app):
        status, _, body = _get(app, "/project_s01/ruleset")
        assert status == 200
        text = body.decode("utf-8")
        assert "allow-established" in text
        assert "deny-inter-vlan" in text

    def test_runbook_page_200(self, app):
        status, _, body = _get(app, "/project_s01/runbook")
        assert status == 200
        assert b"critical" in body

    def test_incidents_page_200(self, app):
        status, _, body = _get(app, "/project_s01/incidents")
        assert status == 200
        assert b"Incident tickets" in body

    def test_nav_links_present(self, app):
        _, _, body = _get(app, "/")
        text = body.decode("utf-8")
        assert "/project_s01" in text


class TestNetsecApi:
    def test_topology(self, app):
        status, _, body = _get(app, "/api/netsec/topology")
        assert status == 200
        data = _body_json((status, _, body))
        assert data["zones"]["OFFICE"]["subnet"] == "10.10.10.0/24"
        assert data["zones"]["GUEST"]["vlan"] == 20
        assert data["default_deny"] is True

    def test_rules_lint_clean(self, app):
        status, _, body = _get(app, "/api/netsec/rules")
        data = _body_json((status, _, body))
        assert status == 200
        assert data["lint"] == []
        assert len(data["rules"]) == len(fw.RULESET) == 13
        allows = [r for r in data["rules"] if r["action"] == "allow"]
        assert all(r["exception_reason"] for r in allows)

    def test_evaluate_allow(self, app):
        status, _, body = _post_json(app, "/api/netsec/evaluate", {
            "src_ip": "10.10.10.20", "dst_ip": "93.184.216.34",
            "proto": "tcp", "dst_port": 443})
        data = _body_json((status, _, body))
        assert status == 200
        assert data["verdict"]["action"] == "allow"
        assert data["verdict"]["rule_id"] == "allow-office-web"
        assert data["packet"]["src_zone"] == "OFFICE"
        assert data["packet"]["dst_zone"] == "WAN"

    def test_evaluate_deny(self, app):
        status, _, body = _post_json(app, "/api/netsec/evaluate", {
            "src_ip": "10.10.20.5", "dst_ip": "10.10.10.10",
            "proto": "tcp", "dst_port": 445})
        data = _body_json((status, _, body))
        assert data["verdict"]["action"] == "deny"
        assert data["verdict"]["rule_id"] == "deny-guest-internal"

    def test_evaluate_rejects_bad_input(self, app):
        status, _, _ = _post_json(app, "/api/netsec/evaluate",
                                  {"src_ip": "not-an-ip"})
        assert status == 422
        status, _, _ = _post_json(app, "/api/netsec/evaluate", "nope")
        assert status == 422

    def test_matrix_matches_test_plan(self, app):
        status, _, body = _get(app, "/api/netsec/matrix")
        data = _body_json((status, _, body))
        assert status == 200
        assert data["coverage"]["unhit_allow"] == []
        assert data["coverage"]["unhit_deny"] == []
        assert len(data["matrix"]) == len(fw.LAB_TEST_PACKETS)

    def test_runbook_endpoint(self, app):
        status, _, body = _get(app, "/api/netsec/runbook")
        data = _body_json((status, _, body))
        assert status == 200
        assert len(data["runbook"]["critical"]) == 4
        assert len(data["alert_types"]) == 9

    def test_alert_ingest_and_list(self, app):
        status, _, body = _post_json(app, "/api/netsec/alerts", {
            "alert_type": "port_scan_detected"})
        data = _body_json((status, _, body))
        assert status == 201
        assert data["alert"]["severity"] == "high"
        assert data["walkthrough"]["all_within_timebox"] is True
        status, _, body = _get(app, "/api/netsec/alerts")
        assert any(a["alert_type"] == "port_scan_detected"
                   for a in _body_json((status, _, body))["alerts"])

    def test_alert_ingest_rejects_unknown_type(self, app):
        status, _, _ = _post_json(app, "/api/netsec/alerts",
                                  {"alert_type": "bogus"})
        assert status == 422

    def test_tuning_create_and_list(self, app):
        status, _, body = _post_json(app, "/api/netsec/tuning", {
            "alert_type": "wan_inbound_blocked", "action": "threshold",
            "reason": "background noise"})
        assert status == 201
        status, _, body = _get(app, "/api/netsec/tuning")
        rows = _body_json((status, _, body))["tuning"]
        assert any(r["reason"] == "background noise" for r in rows)

    def test_tuning_create_rejects_bad_action(self, app):
        status, _, _ = _post_json(app, "/api/netsec/tuning", {
            "alert_type": "wan_inbound_blocked", "action": "delete",
            "reason": "x"})
        assert status == 422

    def test_incident_lifecycle_via_api(self, app):
        status, _, body = _post_json(app, "/api/netsec/incidents", {
            "title": "API probe", "severity": "medium"})
        data = _body_json((status, _, body))
        assert status == 201
        iid = data["incident"]["id"]
        assert data["incident"]["status"] == "open"
        status, _, body = _get(app, f"/api/netsec/incidents/{iid}")
        assert _body_json((status, _, body))["incident"]["title"] == "API probe"
        status, _, body = _post_json(
            app, f"/api/netsec/incidents/{iid}/transition",
            {"to_status": "triaged", "note": "api test"})
        assert status == 200
        assert _body_json((status, _, body))["incident"]["status"] == "triaged"
        # illegal jump is rejected
        status, _, _ = _post_json(
            app, f"/api/netsec/incidents/{iid}/transition",
            {"to_status": "closed"})
        assert status == 422

    def test_incident_create_rejects_empty_title(self, app):
        status, _, _ = _post_json(app, "/api/netsec/incidents",
                                  {"title": " ", "severity": "low"})
        assert status == 422

    def test_incident_detail_404(self, app):
        status, _, _ = _get(app, "/api/netsec/incidents/424242")
        assert status == 404

    def test_seed_endpoint(self, app):
        status, _, body = _post_json(app, "/api/netsec/seed", {"seed": 7})
        data = _body_json((status, _, body))
        assert status == 200
        assert data["seeded"]["tuning"] == 3
        assert data["seeded"]["alerts"] == 3

    def test_incident_form_post(self, app):
        status, headers, _ = _post_form(app, "/api/netsec/incidents",
                                       {"title": "form ticket",
                                        "severity": "low"})
        assert status == 201
