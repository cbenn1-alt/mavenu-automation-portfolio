"""Q03 web + API tests: pages render, endpoints work, errors are clean."""
import io
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from tests.conftest import wsgi_call

NOW_ISO = "2026-10-23T12:00:00+00:00"


def _post(app, path, payload):
    return wsgi_call(app, "POST", path, json.dumps(payload).encode())


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


def _json_body(resp):
    return json.loads(resp[2].decode())


def _seed_customer(app):
    status, _, body = _post(app, "/api/reactivation/customers",
                            {"customer_name": "Acme Test Co"})
    assert status == 201
    customer = json.loads(body.decode())
    job_payload = {
        "job_ref": "JOB-1", "service_type": "hvac",
        "job_date": "2025-06-01T10:00:00+00:00", "amount_cents": 45000,
    }
    status, _, _ = _post(
        app, f"/api/reactivation/customers/{customer['public_id']}/jobs",
        job_payload)
    assert status == 201
    return customer


def test_pages_render(app):
    for path in ("/project_q03", "/project_q03/segments",
                 "/project_q03/outbox", "/project_q03/attribution",
                 "/project_q03/suppression"):
        status, headers, body = _get(app, path)
        assert status == 200, path
        assert b"Q03" in body


def test_hub_links_q03(app):
    status, _, body = _get(app, "/")
    assert status == 200
    assert b"/project_q03" in body


def test_create_customer_validation(app):
    status, _, body = _post(app, "/api/reactivation/customers",
                            {"customer_name": "   "})
    assert status == 422
    assert "validation_failed" in body.decode()


def test_full_demo_flow_through_api(app):
    customer = _seed_customer(app)
    pid = customer["public_id"]

    # Score.
    status, _, body = _post(app, "/api/reactivation/score", {})
    assert status == 200
    scored = _json_body((status, {}, body))["scored"]
    assert scored[0]["segment"] == "churned"
    assert scored[0]["dormancy_score"] == 0.925

    # Segments report.
    status, _, body = _get(app, "/api/reactivation/segments")
    segs = {s["segment"]: s for s in _json_body((status, {}, body))["segments"]}
    assert segs["churned"]["customers"] == 1

    # Win-back run queues step 1.
    status, _, body = _post(app, "/api/reactivation/winback-run", {})
    result = _json_body((status, {}, body))
    assert len(result["queued"]) == 1
    assert result["queued"][0]["public_id"] == pid

    # Outbox view.
    status, _, body = _get(app, "/api/reactivation/outbox")
    outbox = _json_body((status, {}, body))["outbox"]
    assert len(outbox) == 1 and outbox[0]["status"] == "queued"

    # Flush (stub).
    status, _, body = _post(app, "/api/reactivation/outbox/flush", {})
    flushed = _json_body((status, {}, body))["flushed"]
    assert flushed[0]["status"] == "stub-logged"

    # Customer detail carries jobs, touches, events.
    status, _, body = _get(app, f"/api/reactivation/customers/{pid}")
    detail = _json_body((status, {}, body))
    assert len(detail["jobs"]) == 1
    assert len(detail["touches"]) == 1
    assert any(e["event_type"] == "customer.scored" for e in detail["events"])


def test_suppression_endpoints_block_touches(app):
    customer = _seed_customer(app)
    pid = customer["public_id"]
    status, _, _ = _post(app, f"/api/reactivation/customers/{pid}/suppression",
                         {"do_not_contact": True})
    assert status == 200
    _post(app, "/api/reactivation/score", {})
    status, _, body = _post(app, "/api/reactivation/winback-run", {})
    assert _json_body((status, {}, body))["queued"] == []
    status, _, body = _get(app, "/api/reactivation/suppression-audit")
    audit = _json_body((status, {}, body))
    assert audit["suppressed_count"] == 1
    assert audit["suppressed_customers"][0]["reason"] == "do_not_contact"


def test_complaint_endpoint(app):
    customer = _seed_customer(app)
    pid = customer["public_id"]
    status, _, _ = _post(app, f"/api/reactivation/customers/{pid}/complaint", {})
    assert status == 200
    status, _, body = _get(app, "/api/reactivation/suppression-audit")
    assert _json_body((status, {}, body))["suppressed_customers"][0][
        "reason"] == "recent_complaint"


def test_holdout_and_attribution_endpoints(app):
    c1 = _seed_customer(app)
    _post(app, "/api/reactivation/score", {})
    status, _, body = _post(app, "/api/reactivation/holdout",
                            {"run_name": "demo-1", "holdout_pct": 50,
                             "customer_ids": [1]})
    assert status == 200
    payload = _json_body((status, {}, body))
    assert payload["treated"] + payload["control"] == 1

    status, _, body = _get_qs(app, "/api/reactivation/attribution", {
        "run_name": "demo-1",
        "window_start": "2026-10-01T00:00:00+00:00",
        "window_end": "2026-10-31T23:59:59+00:00",
    })
    assert status == 200
    report = _json_body((status, {}, body))
    assert "SYNTHETIC-DATA ILLUSTRATION" in report["label"]
    assert report["treated"]["total"] + report["control"]["total"] == 1


def test_attribution_requires_params(app):
    status, _, body = _get(app, "/api/reactivation/attribution")
    assert status == 422


def test_scoring_info_endpoint(app):
    status, _, body = _get(app, "/api/reactivation/scoring-info")
    info = _json_body((status, {}, body))
    assert info["weights"] == {"recency": 0.5, "frequency": 0.3, "monetary": 0.2}
    assert info["scorer"] == "deterministic-rfm-v1"


def test_unknown_customer_404(app):
    status, _, body = _get(app, "/api/reactivation/customers/CUS-999999")
    assert status == 404
    status, _, body = _post(app, "/api/reactivation/customers/CUS-999999/jobs",
                            {"job_ref": "J", "service_type": "hvac",
                             "job_date": NOW_ISO, "amount_cents": 100})
    assert status == 404


def test_html_forms_submit(app):
    _seed_customer(app)
    status, headers, _ = wsgi_call(app, "POST", "/project_q03/score")
    assert status == 303 and headers["Location"] == "/project_q03"
    status, headers, _ = wsgi_call(app, "POST", "/project_q03/winback-run")
    assert status == 303 and headers["Location"] == "/project_q03/outbox"
    status, headers, _ = wsgi_call(app, "POST", "/project_q03/outbox/flush")
    assert status == 303
