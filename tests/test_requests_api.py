"""HTTP-level tests for Project 02: intake API, decisions, sweep, dashboard.

All names, emails, and amounts below are synthetic fixtures.
"""
import json

from mavenu.config import Settings

from .conftest import wsgi_call
from .test_request_validation import GOOD_REQUEST


def _post_json(app, path, payload, headers=None):
    body = json.dumps(payload).encode()
    return wsgi_call(app, "POST", path, body, headers=headers)


def _create(app, **overrides):
    payload = dict(GOOD_REQUEST)
    payload.update(overrides)
    status, _, body = _post_json(app, "/api/requests", payload)
    assert status == 201, body
    return json.loads(body)["public_id"]


def _submit(app, public_id):
    status, _, body = _post_json(app, f"/api/requests/{public_id}/submit",
                                {"actor": "requester:dana"})
    assert status == 200, body
    return json.loads(body)


# -- intake --------------------------------------------------------------------

def test_api_create_request_201(app, settings):
    status, _, body = _post_json(app, "/api/requests", GOOD_REQUEST)
    assert status == 201
    data = json.loads(body)
    assert data["public_id"].startswith("RQ-")
    assert data["state"] == "draft"


def test_api_create_request_idempotent_replay(app, settings):
    headers = {"Idempotency-Key": "p02-key-abc"}
    first = _post_json(app, "/api/requests", GOOD_REQUEST, headers=headers)
    second = _post_json(app, "/api/requests", GOOD_REQUEST, headers=headers)
    assert first[0] == 201
    assert second[0] == 200
    body = json.loads(second[2])
    assert body["replayed"] is True
    assert body["public_id"] == json.loads(first[2])["public_id"]


def test_api_create_request_422_with_field_errors(app):
    status, _, body = _post_json(app, "/api/requests",
                                {"request_type": "nope", "title": ""})
    assert status == 422
    data = json.loads(body)
    assert data["error"]["code"] == "validation_failed"
    assert "request_type" in data["error"]["fields"]


def test_api_create_request_422_on_bad_json(app):
    status, _, body = wsgi_call(app, "POST", "/api/requests", b"{not json")
    assert status == 422


def test_api_get_request_includes_chain_and_events(app):
    public_id = _create(app)
    status, _, body = wsgi_call(app, "GET", f"/api/requests/{public_id}")
    assert status == 200
    data = json.loads(body)
    assert data["public_id"] == public_id
    assert data["allowed_transitions"] == ["cancelled", "submitted"]
    assert any(e["event_type"] == "request.created" for e in data["events"])


def test_api_get_request_404(app):
    status, _, body = wsgi_call(app, "GET", "/api/requests/RQ-999999")
    assert status == 404


# -- approval flow ------------------------------------------------------------------

def test_api_full_approval_flow(app):
    public_id = _create(app)
    _submit(app, public_id)

    # Wrong role is refused.
    status, _, body = _post_json(
        app, f"/api/requests/{public_id}/decision",
        {"decision": "approve", "role": "finance", "actor": "reviewer:omar"},
    )
    assert status == 409
    assert json.loads(body)["error"]["code"] == "decision_rejected"

    # Manager approves step 1; finance approves step 2 -> approved.
    status, _, body = _post_json(
        app, f"/api/requests/{public_id}/decision",
        {"decision": "approve", "role": "manager", "actor": "reviewer:mara"},
    )
    assert status == 200
    assert json.loads(body)["state"] == "in_review"

    status, _, body = _post_json(
        app, f"/api/requests/{public_id}/decision",
        {"decision": "approve", "role": "finance", "actor": "reviewer:omar"},
    )
    assert status == 200
    assert json.loads(body)["state"] == "approved"

    # Fulfill the approved request.
    status, _, body = _post_json(
        app, f"/api/requests/{public_id}/fulfill", {"actor": "ops:lee"}
    )
    assert status == 200
    assert json.loads(body)["state"] == "fulfilled"


def test_api_double_submit_is_rejected(app):
    public_id = _create(app)
    _submit(app, public_id)
    status, _, body = _post_json(app, f"/api/requests/{public_id}/submit",
                                {"actor": "requester:dana"})
    assert status == 409


def test_api_cancel_request(app):
    public_id = _create(app)
    status, _, body = _post_json(app, f"/api/requests/{public_id}/cancel",
                                {"actor": "requester:dana"})
    assert status == 200
    assert json.loads(body)["state"] == "cancelled"


def test_api_resubmit_after_changes_requested(app):
    public_id = _create(app, request_type="access", amount="")
    _submit(app, public_id)
    status, _, body = _post_json(
        app, f"/api/requests/{public_id}/decision",
        {"decision": "request_changes", "role": "manager", "actor": "reviewer:mara"},
    )
    assert json.loads(body)["state"] == "changes_requested"
    status, _, body = _post_json(app, f"/api/requests/{public_id}/resubmit",
                                {"actor": "requester:dana"})
    assert status == 200
    assert json.loads(body)["state"] == "in_review"


def test_api_sla_sweep_escalates(tmp_path):
    # A zero-hour SLA makes the sweep deterministic at the HTTP layer.
    settings = Settings(
        db_path=str(tmp_path / "sweep.db"),
        port=8080,
        idempotency_ttl_hours=72,
        review_confidence_threshold=0.65,
        log_level="INFO",
        finance_threshold_cents=100_000,
        approval_sla_hours=0,
    )
    from mavenu.web import App

    app = App(settings)
    public_id = _create(app)
    _submit(app, public_id)

    status, _, body = _post_json(app, "/api/requests/sla-sweep", {})
    assert status == 200
    data = json.loads(body)
    assert data["escalated"] == [public_id]

    status, _, body = wsgi_call(app, "GET", f"/api/requests/{public_id}")
    assert json.loads(body)["state"] == "escalated"


# -- HTML --------------------------------------------------------------------------

def test_html_intake_form_renders(app):
    status, _, body = wsgi_call(app, "GET", "/project02")
    assert status == 200
    assert b"Request type" in body
    assert b"SYNTHETIC DEMO DATA" in body


def test_html_form_submit_redirects_to_detail(app):
    from urllib.parse import urlencode

    payload = dict(GOOD_REQUEST)
    payload["amount"] = str(payload["amount"])
    body = urlencode(payload).encode()
    status, headers, _ = wsgi_call(
        app, "POST", "/project02/requests", body,
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 303
    assert headers["Location"].startswith("/project02/requests/RQ-")
    status, _, detail = wsgi_call(app, "GET", headers["Location"])
    assert status == 200
    assert b"draft" in detail


def test_html_form_invalid_rerenders_422(app):
    from urllib.parse import urlencode

    body = urlencode({"title": ""}).encode()
    status, _, out = wsgi_call(
        app, "POST", "/project02/requests", body,
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 422
    assert b"request_type" in out


def test_html_dashboard_reconciles(app):
    _create(app)
    _create(app, request_type="access", amount="")
    status, _, body = wsgi_call(app, "GET", "/project02/dashboard")
    assert status == 200
    assert b"Total" in body
    # Both draft requests appear in the totals rendered from the DB.
    assert body.count(b"RQ-") >= 2


def test_hub_lists_project_02_implemented(app):
    status, _, body = wsgi_call(app, "GET", "/")
    assert status == 200
    assert b"Project 02" in body
    assert b"Gate B" in body
