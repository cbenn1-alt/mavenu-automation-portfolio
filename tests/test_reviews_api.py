"""API + web tests for Q08 — Review & Reputation Monitor.

All data is synthetic fixture data. Uses the shared WSGI test client from
conftest (plus a query-string variant, since the conftest client drops
QUERY_STRING — same workaround as the Q06/Q07 API tests).
"""
import io
import json

import pytest

from tests.conftest import wsgi_call


def wsgi_call_qs(app, method, path, query="", body=b"",
                 content_type="application/json"):
    """wsgi_call variant that sets QUERY_STRING."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
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


def _post(app, path, payload):
    return wsgi_call(app, "POST", path, body=json.dumps(payload).encode())


EVENTS = [
    {
        "source": "api-test", "external_id": "a1", "stars": 1,
        "title": "Awful", "body": "Terrible mess, they were hours late.",
        "reviewed_at": "2026-10-23T10:00:00Z", "author": "Casey Lee",
    },
    {
        "source": "api-test", "external_id": "a2", "stars": 5,
        "title": "Great", "body": "Excellent work, friendly and professional crew.",
        "reviewed_at": "2026-10-23T11:00:00Z", "author": "Jordan Kim",
    },
]


def test_api_ingest(app):
    status, _, body = _post(app, "/api/reviews/ingest", {"events": EVENTS})
    assert status == 200
    data = json.loads(body)
    assert data["ingested"] == 2
    assert data["duplicates"] == 0
    # Re-post is idempotent.
    status, _, body = _post(app, "/api/reviews/ingest", {"events": EVENTS})
    assert json.loads(body)["duplicates"] == 2


def test_api_ingest_rejects_bad_events(app):
    status, _, body = _post(
        app, "/api/reviews/ingest",
        {"events": [{"source": "x"}]})
    data = json.loads(body)
    assert status == 200
    assert data["skipped"] == 1
    assert data["errors"]


def test_api_ingest_requires_event_list(app):
    status, _, _ = _post(app, "/api/reviews/ingest", {"events": "nope"})
    assert status == 400


def test_api_reviews_list_with_tags(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    status, _, body = wsgi_call(app, "GET", "/api/reviews")
    assert status == 200
    reviews = json.loads(body)["reviews"]
    assert len(reviews) == 2
    neg = next(r for r in reviews if r["external_id"] == "a1")
    sent = [t for t in neg["tags"] if t["kind"] == "sentiment"][0]
    assert sent["label"] == "negative"
    assert neg["queue"] == "owner_alert"
    assert neg["severity"] == "critical"
    pos = next(r for r in reviews if r["external_id"] == "a2")
    assert pos["queue"] is None
    assert all(t["lexicon_version"] == "1.0" for t in neg["tags"])


def test_api_reviews_list_sentiment_filter(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    status, _, body = wsgi_call_qs(
        app, "GET", "/api/reviews", query="sentiment=negative")
    assert status == 200
    reviews = json.loads(body)["reviews"]
    assert {r["external_id"] for r in reviews} == {"a1"}


def test_api_queues_and_sla(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    status, _, body = wsgi_call(app, "GET", "/api/reviews/queues")
    assert status == 200
    data = json.loads(body)
    assert data["counts"] == {"owner_alert/open": 1}
    assert data["queues"][0]["severity"] == "critical"
    status, _, body = wsgi_call(app, "GET", "/api/reviews/sla")
    assert status == 200
    sla = json.loads(body)
    assert sla["open"] == 1
    assert sla["as_of_utc"].endswith("+00:00")


def test_api_draft_lifecycle(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    status, _, body = wsgi_call(app, "GET", "/api/reviews")
    review_id = next(
        r["id"] for r in json.loads(body)["reviews"]
        if r["external_id"] == "a1")
    # Generate.
    status, _, body = _post(
        app, f"/api/reviews/{review_id}/draft",
        {"tone": "brief", "actor": "tester"})
    assert status == 201
    draft = json.loads(body)
    assert draft["status"] == "draft"
    draft_id = draft["draft_id"]
    # Approve (human gate).
    status, _, body = _post(
        app, f"/api/reviews/drafts/{draft_id}/approve",
        {"approver": "owner@example.com"})
    assert status == 200
    assert json.loads(body)["status"] == "approved"
    # Drafts list reflects it.
    status, _, body = wsgi_call_qs(
        app, "GET", "/api/reviews/drafts", query="status=approved")
    assert any(d["id"] == draft_id for d in json.loads(body)["drafts"])
    # Re-approving is rejected.
    status, _, body = _post(
        app, f"/api/reviews/drafts/{draft_id}/approve",
        {"approver": "owner@example.com"})
    assert status == 422


def test_api_draft_reject(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    _, _, body = wsgi_call(app, "GET", "/api/reviews")
    review_id = json.loads(body)["reviews"][0]["id"]
    _, _, body = _post(app, f"/api/reviews/{review_id}/draft", {})
    draft_id = json.loads(body)["draft_id"]
    status, _, body = _post(
        app, f"/api/reviews/drafts/{draft_id}/reject", {"approver": "owner"})
    assert status == 200
    assert json.loads(body)["status"] == "rejected"


def test_api_draft_bad_tone_rejected(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    _, _, body = wsgi_call(app, "GET", "/api/reviews")
    review_id = json.loads(body)["reviews"][0]["id"]
    status, _, _ = _post(
        app, f"/api/reviews/{review_id}/draft", {"tone": "sarcastic"})
    assert status == 422


def test_api_has_no_send_path(app):
    """There is deliberately no endpoint that posts a response anywhere."""
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    _, _, body = wsgi_call(app, "GET", "/api/reviews")
    review_id = json.loads(body)["reviews"][0]["id"]
    _, _, body = _post(app, f"/api/reviews/{review_id}/draft", {})
    draft_id = json.loads(body)["draft_id"]
    for method, path in (
        ("POST", f"/api/reviews/drafts/{draft_id}/send"),
        ("POST", f"/api/reviews/{review_id}/send"),
        ("GET", f"/api/reviews/drafts/{draft_id}/send"),
    ):
        status, _, _ = wsgi_call(app, method, path)
        assert status == 404, (method, path)


def test_api_lexicon_inspectable(app):
    status, _, body = wsgi_call(app, "GET", "/api/reviews/lexicons/1.0")
    assert status == 200
    data = json.loads(body)
    assert "sentiment_positive" in data["categories"]
    assert "excellent" in data["categories"]["sentiment_positive"]
    status, _, _ = wsgi_call(app, "GET", "/api/reviews/lexicons/9.9")
    assert status == 404


def test_pages_render(app):
    for path in ("/project_q08", "/project_q08/reviews",
                 "/project_q08/queues", "/project_q08/drafts"):
        status, headers, body = wsgi_call(app, "GET", path)
        assert status == 200, path
        assert b"SYNTHETIC DEMO DATA" in body, path


def test_page_ingest_form(app):
    csv_text = ("external_id,stars,title,body,reviewed_at,author\n"
                "w1,1,Awful,Terrible mess.,2026-10-23T10:00:00Z,Casey\n")
    body = f"csv={csv_text}".encode()
    # parse_qsl needs urlencoding; use the query form of the helper.
    from urllib.parse import urlencode
    status, _, out = wsgi_call(
        app, "POST", "/project_q08/ingest",
        body=urlencode({"csv": csv_text}).encode(),
        content_type="application/x-www-form-urlencoded")
    assert status == 200
    assert b"Ingested 1" in out


def test_page_queue_resolve_redirects(app):
    _post(app, "/api/reviews/ingest", {"events": EVENTS})
    _, _, body = wsgi_call(app, "GET", "/api/reviews/queues")
    queue_id = json.loads(body)["queues"][0]["id"]
    from urllib.parse import urlencode
    status, headers, _ = wsgi_call(
        app, "POST", "/project_q08/queues/resolve",
        body=urlencode({"queue_id": str(queue_id),
                        "actor": "owner"}).encode(),
        content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"] == "/project_q08/queues"
