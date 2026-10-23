"""Q02 web + API tests: pages, JSON endpoints, error envelopes.

All fixture data is synthetic.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest

from mavenu import estimates as es
from tests.conftest import wsgi_call

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

GOOD_JSON = {
    "customer_name": "Acme Test Co",
    "service_type": "hvac",
    "estimator": "Rosa",
    "amount_cents": 125000,
}


def api(app, method, path, payload=None, headers=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    return wsgi_call(app, method, path, body=body, headers=headers)


def create_sent(app, settings, days_ago=10):
    from mavenu.db import get_connection
    conn = get_connection(settings.db_path)
    try:
        sent_at = T0 - timedelta(days=days_ago)
        e = es.create_estimate(conn, GOOD_JSON, actor="test", now=sent_at)
        return es.transition_estimate(conn, e["public_id"], "sent", "test", now=sent_at)
    finally:
        conn.close()


# -- pages -----------------------------------------------------------------------------------

def test_hub_lists_q02(app):
    status, _, body = wsgi_call(app, "GET", "/")
    assert status == 200
    assert b"/project_q02" in body


def test_q02_pages_render(app):
    for path in ("/project_q02", "/project_q02/outbox", "/project_q02/reports",
                 "/project_q02/templates"):
        status, _, body = wsgi_call(app, "GET", path)
        assert status == 200, path
        assert b"SYNTHETIC" in body or b"synthetic" in body


def test_q02_form_create_redirects_to_detail(app):
    form = urlencode({
        "customer_name": "Acme Test Co", "service": "plumbing",
        "estimator": "Theo", "amount": "99.99", "notes": "",
        "idempotency_key": "form-key-1",
    })
    status, headers, _ = wsgi_call(app, "POST", "/project_q02/estimates",
                                  body=form.encode(),
                                  content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"].startswith("/project_q02/estimates/EST-")
    status, _, body = wsgi_call(app, "GET", headers["Location"])
    assert status == 200
    assert b"Acme Test Co" in body


def test_q02_form_validation_error_rerenders(app):
    form = urlencode({"customer_name": "", "service": "hvac",
                      "estimator": "", "amount": "0"})
    status, _, body = wsgi_call(app, "POST", "/project_q02/estimates",
                                body=form.encode(),
                                content_type="application/x-www-form-urlencoded")
    assert status == 422
    assert b"customer_name" in body


def test_q02_detail_transition_form(app, settings):
    e = create_sent(app, settings, days_ago=1)
    form = urlencode({"action": "transition", "to_state": "viewed", "actor": "Rosa"})
    status, headers, _ = wsgi_call(app, "POST", f"/project_q02/estimates/{e['public_id']}",
                                  body=form.encode(),
                                  content_type="application/x-www-form-urlencoded")
    assert status == 303
    status, _, body = wsgi_call(app, "GET", f"/project_q02/estimates/{e['public_id']}")
    assert b"viewed" in body


def test_q02_run_cadence_and_flush_buttons(app, settings):
    create_sent(app, settings, days_ago=10)
    status, headers, _ = wsgi_call(app, "POST", "/project_q02/cadence-run")
    assert status == 303 and headers["Location"] == "/project_q02/outbox"
    status, _, body = wsgi_call(app, "GET", "/project_q02/outbox")
    assert b"est:1:step:1" in body
    status, headers, _ = wsgi_call(app, "POST", "/project_q02/outbox/flush")
    assert status == 303
    status, _, body = wsgi_call(app, "GET", "/project_q02/outbox")
    assert b"stub-logged" in body


# -- estimate API ------------------------------------------------------------------------------

def test_api_create_estimate_201(app):
    status, _, body = api(app, "POST", "/api/estimates", GOOD_JSON)
    assert status == 201
    data = json.loads(body)
    assert data["public_id"] == "EST-000001"
    assert data["state"] == "draft"


def test_api_create_idempotent_replay(app):
    status, _, body = api(app, "POST", "/api/estimates", GOOD_JSON,
                          headers={"Idempotency-Key": "api-k1"})
    assert status == 201
    status, _, body = api(app, "POST", "/api/estimates", GOOD_JSON,
                          headers={"Idempotency-Key": "api-k1"})
    assert status == 200
    assert json.loads(body)["replayed"] is True


def test_api_create_invalid_payload_422(app):
    status, _, body = api(app, "POST", "/api/estimates",
                          {"customer_name": "", "service_type": "hvac",
                           "estimator": "R", "amount_cents": -5})
    assert status == 422
    fields = json.loads(body)["error"]["fields"]
    assert "customer_name" in fields and "amount_cents" in fields


def test_api_get_estimate_includes_transitions_and_events(app, settings):
    e = create_sent(app, settings, days_ago=1)
    status, _, body = api(app, "GET", f"/api/estimates/{e['public_id']}")
    assert status == 200
    data = json.loads(body)
    assert sorted(data["allowed_transitions"]) == ["accepted", "declined", "expired",
                                                  "followed_up", "viewed"]
    assert any(ev["event_type"] == "estimate.sent" for ev in data["events"])


def test_api_get_unknown_estimate_404(app):
    status, _, body = api(app, "GET", "/api/estimates/EST-999999")
    assert status == 404
    assert json.loads(body)["error"]["code"] == "not_found"


def test_api_transition_and_illegal_transition(app, settings):
    e = create_sent(app, settings, days_ago=1)
    status, _, body = api(app, "POST", f"/api/estimates/{e['public_id']}/transition",
                          {"to_state": "viewed", "actor": "Rosa"})
    assert status == 200
    assert json.loads(body)["state"] == "viewed"
    status, _, body = api(app, "POST", f"/api/estimates/{e['public_id']}/transition",
                          {"to_state": "draft"})
    assert status == 409


def test_api_decline_requires_reason(app, settings):
    e = create_sent(app, settings, days_ago=1)
    status, _, body = api(app, "POST", f"/api/estimates/{e['public_id']}/transition",
                          {"to_state": "declined"})
    assert status == 422
    status, _, body = api(app, "POST", f"/api/estimates/{e['public_id']}/transition",
                          {"to_state": "declined", "decline_reason": "timing"})
    assert status == 200
    assert json.loads(body)["state"] == "declined"


def test_api_unsubscribe_stops_cadence(app, settings):
    e = create_sent(app, settings, days_ago=20)
    status, _, body = api(app, "POST", f"/api/estimates/{e['public_id']}/unsubscribe",
                          {"actor": "Rosa"})
    assert status == 200
    assert json.loads(body)["unsubscribed"] == 1
    status, _, body = api(app, "POST", "/api/cadence/run")
    assert json.loads(body)["queued"] == []


# -- templates API -------------------------------------------------------------------------------

def test_api_templates_list_create_test_send(app):
    status, _, body = api(app, "GET", "/api/estimate-templates")
    assert status == 200
    names = [t["name"] for t in json.loads(body)["templates"]]
    assert "followup_step1" in names
    status, _, body = api(app, "POST", "/api/estimate-templates",
                          {"name": "web_nudge", "subject": "Hi {{customer_name}}",
                           "body": "Estimate {{estimate_id}}: {{amount}}."})
    assert status == 201
    assert json.loads(body)["version"] == 1
    ctx = {"customer_name": "Acme Test Co", "estimate_id": "EST-000001",
           "amount": "$10.00"}
    status, _, body = api(app, "POST", "/api/estimate-templates/web_nudge/test-send",
                          {"context": ctx})
    assert status == 200
    assert json.loads(body)["subject"] == "Hi Acme Test Co"
    # Missing variable -> 409, never queued.
    status, _, body = api(app, "POST", "/api/estimate-templates/web_nudge/test-send",
                          {"context": {"customer_name": "x"}})
    assert status == 409


# -- cadence API -----------------------------------------------------------------------------------

def test_api_cadence_rules_get_and_replace(app):
    status, _, body = api(app, "GET", "/api/cadence/rules")
    assert status == 200
    assert len(json.loads(body)["rules"]) == 3
    status, _, body = api(app, "POST", "/api/cadence/rules",
                          {"rules": [{"step_index": 1, "days_after_sent": 1,
                                      "template_name": "followup_step1"}]})
    assert status == 200
    assert len(json.loads(body)["rules"]) == 1
    status, _, body = api(app, "POST", "/api/cadence/rules", {"rules": []})
    assert status == 422


def test_api_cadence_run_queues_due_steps(app, settings):
    create_sent(app, settings, days_ago=10)
    status, _, body = api(app, "POST", "/api/cadence/run")
    assert status == 200
    data = json.loads(body)
    assert len(data["queued"]) == 2
    # Replay: nothing new.
    status, _, body = api(app, "POST", "/api/cadence/run")
    assert json.loads(body)["queued"] == []


def test_api_outbox_and_flush(app, settings):
    create_sent(app, settings, days_ago=20)
    api(app, "POST", "/api/cadence/run")
    status, _, body = api(app, "GET", "/api/estimates/outbox")
    assert status == 200
    assert len(json.loads(body)["outbox"]) == 3
    status, _, body = api(app, "POST", "/api/cadence/flush")
    assert status == 200
    assert len(json.loads(body)["flushed"]) == 3
    status, _, body = api(app, "GET", "/api/estimates/outbox")
    data = json.loads(body)
    assert all(r["status"] == "sent" for r in data["outbox"])
    assert len(data["send_log"]) == 3


# -- reports API -------------------------------------------------------------------------------------

def test_api_reports_reconcile(app, settings):
    create_sent(app, settings, days_ago=10)
    for path in ("/api/estimates/reports/aging",
                 "/api/estimates/reports/win-loss",
                 "/api/estimates/reports/effectiveness"):
        status, _, body = api(app, "GET", path)
        assert status == 200, path
    aging = json.loads(wsgi_call(app, "GET", "/api/estimates/reports/aging")[2])
    assert aging["open_count"] == 1
    assert sum(b["count"] for b in aging["buckets"]) == 1
