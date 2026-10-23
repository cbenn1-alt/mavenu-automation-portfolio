"""HTTP-level tests: routes, API contracts, dashboard reconciliation."""
import json
from urllib.parse import urlencode

from .conftest import GOOD_LEAD, LOW_CONFIDENCE_LEAD, db_count, wsgi_call


def _post_json(app, path, payload, headers=None):
    body = json.dumps(payload).encode()
    return wsgi_call(app, "POST", path, body, headers=headers)


def test_hub_lists_project_01(app):
    status, _, body = wsgi_call(app, "GET", "/")
    assert status == 200
    assert b"Project 01" in body


def test_health(app):
    status, _, body = wsgi_call(app, "GET", "/api/health")
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_api_create_lead_201(app, settings):
    status, _, body = _post_json(app, "/api/leads", GOOD_LEAD)
    assert status == 201
    data = json.loads(body)
    assert data["public_id"].startswith("LD-")
    assert data["state"] == "booked"
    assert db_count(settings) == 1


def test_api_invalid_payload_422_with_field_errors(app, settings):
    status, _, body = _post_json(app, "/api/leads", {"name": "", "service": "nope"})
    assert status == 422
    data = json.loads(body)
    assert data["error"]["code"] == "validation_failed"
    assert "name" in data["error"]["fields"]
    assert db_count(settings) == 0


def test_api_idempotency_key_replays(app, settings):
    headers = {"Idempotency-Key": "web-key-1"}
    s1, _, b1 = _post_json(app, "/api/leads", GOOD_LEAD, headers)
    s2, _, b2 = _post_json(app, "/api/leads", GOOD_LEAD, headers)
    assert (s1, s2) == (201, 200)
    assert json.loads(b2)["replayed"] is True
    assert json.loads(b1)["public_id"] == json.loads(b2)["public_id"]
    assert db_count(settings) == 1


def test_api_stats_reconcile_with_database(app, settings):
    _post_json(app, "/api/leads", GOOD_LEAD)
    _post_json(app, "/api/leads", LOW_CONFIDENCE_LEAD)
    status, _, body = wsgi_call(app, "GET", "/api/stats")
    assert status == 200
    data = json.loads(body)
    assert data["total"] == db_count(settings) == 2
    assert sum(data["by_state"].values()) == data["total"]


def test_api_get_lead_includes_events_and_transitions(app):
    _, _, b1 = _post_json(app, "/api/leads", LOW_CONFIDENCE_LEAD)
    pid = json.loads(b1)["public_id"]
    status, _, body = wsgi_call(app, "GET", f"/api/leads/{pid}")
    assert status == 200
    data = json.loads(body)
    assert data["state"] == "needs_review"
    assert len(data["events"]) >= 2
    assert "qualified" in data["allowed_transitions"]


def test_api_get_missing_lead_404(app):
    status, _, body = wsgi_call(app, "GET", "/api/leads/LD-999999")
    assert status == 404


def test_api_transition_moves_state(app):
    _, _, b1 = _post_json(app, "/api/leads", LOW_CONFIDENCE_LEAD)
    pid = json.loads(b1)["public_id"]
    status, _, body = _post_json(
        app, f"/api/leads/{pid}/transition",
        {"to_state": "qualified", "actor": "reviewer:ann"},
    )
    assert status == 200
    assert json.loads(body)["state"] == "qualified"


def test_api_illegal_transition_409(app):
    _, _, b1 = _post_json(app, "/api/leads", GOOD_LEAD)  # booked
    pid = json.loads(b1)["public_id"]
    status, _, body = _post_json(
        app, f"/api/leads/{pid}/transition", {"to_state": "received"}
    )
    assert status == 409
    assert json.loads(body)["error"]["code"] == "invalid_transition"


def test_form_submit_redirects_to_lead_page(app, settings):
    form = dict(GOOD_LEAD, idempotency_key="form-key-1")
    body = urlencode(form).encode()
    status, headers, _ = wsgi_call(
        app, "POST", "/project01/leads", body, content_type="application/x-www-form-urlencoded"
    )
    assert status == 303
    location = headers["Location"]
    assert location.startswith("/project01/leads/LD-")
    status2, _, page = wsgi_call(app, "GET", location)
    assert status2 == 200
    assert b"booked" in page
    assert db_count(settings) == 1


def test_form_invalid_rerenders_with_errors(app, settings):
    form = {"name": "", "service": "hvac", "zip": "58102", "phone": "7015550142"}
    body = urlencode(form).encode()
    status, _, page = wsgi_call(
        app, "POST", "/project01/leads", body, content_type="application/x-www-form-urlencoded"
    )
    assert status == 422
    assert b"Name is required" in page
    assert db_count(settings) == 0


def test_dashboard_renders_counts(app):
    _post_json(app, "/api/leads", GOOD_LEAD)
    status, _, page = wsgi_call(app, "GET", "/project01/dashboard")
    assert status == 200
    assert b"booked" in page and b"Total" in page


def test_unknown_route_404(app):
    status, _, _ = wsgi_call(app, "GET", "/nope")
    assert status == 404
