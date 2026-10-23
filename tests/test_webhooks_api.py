"""Q10 — Webhook Integration Hub: web/API tests (WSGI, stdlib only).

Exercises /project_q10* pages and /api/webhooks* endpoints end to end,
including HMAC-signed ingest through the real HTTP layer.
"""
import io
import json
from urllib.parse import urlencode

from tests.conftest import wsgi_call

from mavenu import webhooks as wh


def _signed_post(app, payload, source="demo-form", secret=None, raw_body=None):
    body = raw_body if raw_body is not None else json.dumps(payload).encode()
    secret = secret if secret is not None else wh.TEST_WEBHOOK_SECRETS[source]
    sig = wh.sign(secret, body)
    return wsgi_call(app, "POST", "/api/webhooks/events", body=body,
                     headers={"X-Webhook-Signature": sig})


def _post(app, path, payload=None, headers=None):
    body = json.dumps(payload or {}).encode()
    return wsgi_call(app, "POST", path, body=body, headers=headers)


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _get_qs(app, path, params):
    """GET with a real QUERY_STRING (conftest's wsgi_call passes PATH_INFO
    through verbatim, so query strings need their own helper)."""
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": urlencode(params),
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
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


def _put(app, path, payload):
    return wsgi_call(app, "PUT", path, body=json.dumps(payload).encode())


def _delete(app, path):
    return wsgi_call(app, "DELETE", path)


def _json_body(raw):
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Ingest through HTTP
# ---------------------------------------------------------------------------

def test_receive_signed_event_201_routed(app):
    status, _, raw = _signed_post(app, {
        "source": "demo-form", "event_type": "lead.created",
        "event_id": "api-1", "payload": {"name": "API Lead", "amount": 42},
    })
    assert status == 201
    data = _json_body(raw)
    assert data["accepted"] is True
    assert data["verified"] is True
    assert data["event_id"] == "api-1"
    assert data["public_id"].startswith("EVT-")


def test_receive_unsigned_strict_401(app):
    body = json.dumps({"source": "demo-form", "event_type": "lead.created",
                       "event_id": "api-2", "payload": {}}).encode()
    status, _, raw = wsgi_call(app, "POST", "/api/webhooks/events", body=body)
    assert status == 401
    data = _json_body(raw)
    assert data["accepted"] is False
    assert data["reason"] == "missing_signature"


def test_receive_invalid_signature_401(app):
    status, _, raw = _signed_post(
        app, {"source": "demo-form", "event_type": "lead.created",
              "event_id": "api-3", "payload": {}}, secret="wrong-secret")
    assert status == 401
    assert _json_body(raw)["reason"] == "invalid_signature"


def test_receive_duplicate_200(app):
    payload = {"source": "demo-form", "event_type": "lead.created",
               "event_id": "api-4", "payload": {}}
    assert _signed_post(app, payload)[0] == 201
    status, _, raw = _signed_post(app, payload)
    assert status == 200
    assert _json_body(raw)["duplicate"] is True


def test_receive_poison_201_dead_lettered(app):
    status, _, raw = _signed_post(
        app, {"source": "demo-form"},  # missing event_type -> poison
        raw_body=json.dumps({"source": "demo-form"}).encode())
    assert status == 201
    data = _json_body(raw)
    assert data["poison"] is True and data["dead_lettered"] is True
    status, _, raw = _get(app, "/api/webhooks/dead-letters")
    dead = _json_body(raw)["dead_letters"]
    assert any(d["reason"] == "malformed_envelope" for d in dead)


def test_receive_invalid_json_422(app):
    status, _, _ = wsgi_call(app, "POST", "/api/webhooks/events",
                             body=b"{nope", headers={"X-Webhook-Signature": "x"})
    assert status == 422


# ---------------------------------------------------------------------------
# Events API
# ---------------------------------------------------------------------------

def test_list_events_and_status_filter(app):
    _signed_post(app, {"source": "demo-form", "event_type": "lead.created",
                       "event_id": "api-list-1", "payload": {}})
    status, _, raw = _get(app, "/api/webhooks/events")
    assert status == 200
    events = _json_body(raw)["events"]
    assert any(e["event_id"] == "api-list-1" for e in events)
    assert all("status" in e for e in events)
    # unsigned -> rejected; filter finds it
    body = json.dumps({"source": "demo-form", "event_type": "lead.created",
                       "event_id": "api-list-2", "payload": {}}).encode()
    wsgi_call(app, "POST", "/api/webhooks/events", body=body)
    status, _, raw = _get_qs(app, "/api/webhooks/events",
                             {"status": "rejected"})
    assert status == 200
    events = _json_body(raw)["events"]
    assert all(e["status"] == "rejected" for e in events)
    assert any(e["event_id"] == "api-list-2" for e in events)


def test_event_detail_includes_lineage(app):
    status, _, raw = _signed_post(app, {
        "source": "demo-form", "event_type": "lead.created",
        "event_id": "api-detail-1", "payload": {}})
    public_id = _json_body(raw)["public_id"]
    status, _, raw = _get(app, f"/api/webhooks/events/{public_id}")
    assert status == 200
    data = _json_body(raw)
    assert data["event"]["event_id"] == "api-detail-1"
    assert data["event"]["envelope"]["payload"] == {}
    assert [l["to_state"] for l in data["lineage"]][0] == "received"
    status, _, _ = _get(app, "/api/webhooks/events/EVT-999999")
    assert status == 404


# ---------------------------------------------------------------------------
# Routes CRUD + dry-run
# ---------------------------------------------------------------------------

def test_routes_crud(app):
    status, _, raw = _post(app, "/api/webhooks/routes", {
        "name": "api-rule", "event_type": "lead.created",
        "conditions": [{"field": "payload.amount", "op": "gte", "value": 10}],
        "actions": [{"type": "log", "message": "big lead"}],
        "priority": 5,
    })
    assert status == 201
    rule = _json_body(raw)["rule"]
    assert rule["version"] == 1
    rid = rule["id"]
    status, _, raw = _get(app, "/api/webhooks/routes")
    assert any(r["name"] == "api-rule" for r in _json_body(raw)["routes"])
    status, _, raw = _get(app, f"/api/webhooks/routes/{rid}")
    assert status == 200 and _json_body(raw)["rule"]["name"] == "api-rule"
    status, _, raw = _put(app, f"/api/webhooks/routes/{rid}",
                          {"priority": 1, "enabled": False})
    assert status == 200
    updated = _json_body(raw)["rule"]
    assert updated["version"] == 2  # updates bump the version
    assert updated["enabled"] == 0
    status, _, _ = _delete(app, f"/api/webhooks/routes/{rid}")
    assert status == 200
    assert _get(app, f"/api/webhooks/routes/{rid}")[0] == 404


def test_routes_create_validates(app):
    status, _, raw = _post(app, "/api/webhooks/routes",
                           {"name": "bad", "actions": [{"type": "nope"}]})
    assert status == 422
    status, _, raw = _post(app, "/api/webhooks/routes",
                           {"name": "bad2",
                            "actions": [{"type": "forward"}]})
    assert status == 422


def test_dry_run_endpoint(app):
    _post(app, "/api/webhooks/routes", {
        "name": "dry-rule", "event_type": "lead.created",
        "actions": [{"type": "forward", "endpoint": "stub:crm-sink"}]})
    status, _, raw = _post(app, "/api/webhooks/routes/dry-run", {
        "source": "demo-form", "event_type": "lead.created",
        "event_id": "dry-1", "payload": {}})
    assert status == 200
    data = _json_body(raw)
    assert any(r["name"] == "dry-rule" for r in data["matched_rules"])
    assert data["would_forward_to"] == ["stub:crm-sink"]
    assert data["payload_summary"]["keys"] == []


def test_dry_run_invalid_envelope_422(app):
    status, _, _ = _post(app, "/api/webhooks/routes/dry-run",
                         {"source": "demo-form"})
    assert status == 422


def test_seed_routes_idempotent(app):
    status, _, raw = _post(app, "/api/webhooks/routes/seed")
    assert status == 200
    first = _json_body(raw)["seeded"]
    assert len(first) == 3
    status, _, raw = _post(app, "/api/webhooks/routes/seed")
    assert _json_body(raw)["seeded"] == []
    assert _json_body(raw)["skipped_existing"] is True


# ---------------------------------------------------------------------------
# Delivery loop, dead letters, replay, endpoints
# ---------------------------------------------------------------------------

def test_deliver_run_and_queue_view(app):
    _post(app, "/api/webhooks/routes", {
        "name": "fwd-rule", "event_type": "lead.created",
        "actions": [{"type": "forward", "endpoint": "stub:crm-sink"}]})
    _signed_post(app, {"source": "demo-form", "event_type": "lead.created",
                       "event_id": "api-del-1", "payload": {}})
    status, _, raw = _get_qs(app, "/api/webhooks/deliveries",
                             {"state": "queued"})
    assert status == 200
    assert any(d["event_id"] == "api-del-1"
               for d in _json_body(raw)["deliveries"])
    status, _, raw = _post(app, "/api/webhooks/deliver/run")
    assert status == 200
    loop = _json_body(raw)["delivery_loop"]
    assert loop["delivered"] == 1
    status, _, raw = _get_qs(app, "/api/webhooks/deliveries",
                             {"state": "delivered"})
    assert any(d["event_id"] == "api-del-1"
               for d in _json_body(raw)["deliveries"])
    assert _get_qs(app, "/api/webhooks/deliveries",
                   {"state": "bogus"})[0] == 422


def test_dead_letter_replay_via_api(app):
    # forward to an unregistered stub -> unknown_endpoint dead letter
    _post(app, "/api/webhooks/routes", {
        "name": "bad-fwd", "event_type": "lead.created",
        "actions": [{"type": "forward", "endpoint": "stub:ghost"}]})
    _signed_post(app, {"source": "demo-form", "event_type": "lead.created",
                       "event_id": "api-dl-1", "payload": {}})
    _post(app, "/api/webhooks/deliver/run")
    status, _, raw = _get(app, "/api/webhooks/dead-letters")
    dead = [d for d in _json_body(raw)["dead_letters"]
            if d["event_id"] == "api-dl-1" and not d["replayed"]]
    assert len(dead) == 1 and dead[0]["reason"] == "unknown_endpoint"
    # replay re-queues; the endpoint is still unknown, so it dead-letters
    # again — the replay mechanism itself is what this test pins
    status, _, raw = _post(app, f"/api/webhooks/dead-letters/{dead[0]['id']}/replay")
    assert status == 200
    assert _json_body(raw)["replayed"] is True
    status, _, raw = _get(app, "/api/webhooks/dead-letters")
    fresh = [d for d in _json_body(raw)["dead_letters"]
             if d["event_id"] == "api-dl-1" and not d["replayed"]]
    assert len(fresh) == 1 and fresh[0]["reason"] == "unknown_endpoint"
    assert _post(app, "/api/webhooks/dead-letters/999999/replay")[0] == 404


def test_endpoints_view(app):
    status, _, raw = _get(app, "/api/webhooks/endpoints")
    assert status == 200
    data = _json_body(raw)
    assert "stub:crm-sink" in data["registered"]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def test_q10_pages_render(app):
    status, headers, raw = _get(app, "/project_q10")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    text = raw.decode("utf-8")
    assert "SYNTHETIC DEMO DATA" in text
    assert "stub endpoints only" in text.lower()
    assert "HMAC" in text
    status, headers, raw = _get(app, "/project_q10/dead-letters")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    text = raw.decode("utf-8")
    assert "SYNTHETIC DEMO DATA" in text
    assert "Dead-letter queue" in text
