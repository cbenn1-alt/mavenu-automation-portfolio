"""Project Q05 — API + page tests (WSGI, stdlib only). All data synthetic."""
import io
import json

from tests.conftest import wsgi_call
from tests.test_reconciliation import EXPECTED, INVOICES_CSV, NOW, PAYMENTS_CSV


def wsgi_call_qs(app, method, path, query="", body=b"", content_type="application/json"):
    """wsgi_call variant that sets QUERY_STRING (the conftest client drops it)."""
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


def api(app, method, path, payload=None, query=""):
    body = b""
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    return wsgi_call_qs(app, method, path, query=query, body=body)


def load(app):
    status, _, body = api(app, "POST", "/api/reconciliation/upload",
                          {"kind": "invoices", "csv": INVOICES_CSV, "actor": "api-test"})
    assert status == 201, body
    status, _, body = api(app, "POST", "/api/reconciliation/upload",
                          {"kind": "payments", "csv": PAYMENTS_CSV, "actor": "api-test"})
    assert status == 201, body
    status, _, body = api(app, "POST", "/api/reconciliation/run-match",
                          {"actor": "api-test"})
    assert status == 200, body
    return json.loads(body)


def test_upload_invoices_and_payments(app):
    load(app)
    status, _, body = api(app, "GET", "/api/reconciliation/summary")
    assert status == 200
    summary = json.loads(body)
    assert summary["invoice_count"] == EXPECTED["invoice_count"]
    assert summary["payment_count"] == EXPECTED["payment_count"]
    assert summary["total_invoiced_cents"] == EXPECTED["total_invoiced_cents"]
    assert summary["outstanding_cents"] == EXPECTED["outstanding_cents"]
    assert summary["overpaid_cents"] == EXPECTED["overpaid_cents"]
    # Money serialized as strings (JSON has no Decimal).
    assert summary["outstanding"] == "3000.00"


def test_upload_invalid_kind_rejected(app):
    status, _, body = api(app, "POST", "/api/reconciliation/upload",
                          {"kind": "ledgers", "csv": "a\n"})
    assert status == 422
    assert json.loads(body)["error"]["code"] == "validation_failed"


def test_upload_reports_row_errors(app):
    bad = "invoice_id,customer,amount,issued_date,due_date\nINV-X,Nope,abc,2026-09-01,2026-10-01\n"
    status, _, body = api(app, "POST", "/api/reconciliation/upload",
                          {"kind": "invoices", "csv": bad})
    assert status == 201
    result = json.loads(body)
    assert result["inserted"] == 0
    assert len(result["errors"]) == 1


def test_run_match_stats(app):
    stats = load(app)
    assert stats["exact_matches"] == EXPECTED["exact_matches"]
    assert stats["fuzzy_matches"] == EXPECTED["fuzzy_matches"]
    assert stats["review_routed"] == EXPECTED["review_routed"]
    assert stats["exceptions_open"] == EXPECTED["open_exceptions"]


def test_exceptions_list_and_filter(app):
    load(app)
    status, _, body = api(app, "GET", "/api/reconciliation/exceptions")
    assert status == 200
    excs = json.loads(body)["exceptions"]
    assert len(excs) == EXPECTED["open_exceptions"]
    kinds = {e["kind"] for e in excs}
    assert kinds == {"partial_payment", "overpaid_invoice", "unmatched_invoice",
                     "unmatched_payment", "review_candidate", "duplicate_payment"}
    status, _, body = api(app, "GET", "/api/reconciliation/exceptions",
                          query="kind=partial_payment")
    assert status == 200
    partials = json.loads(body)["exceptions"]
    assert len(partials) == 2
    assert all(e["suggested_action"] for e in partials)


def test_exception_transition_flow(app):
    load(app)
    status, _, body = api(app, "GET", "/api/reconciliation/exceptions",
                          query="kind=unmatched_invoice")
    exc = json.loads(body)["exceptions"][0]
    exc_id = exc["id"]

    status, _, body = api(app, "GET", f"/api/reconciliation/exceptions/{exc_id}")
    assert status == 200
    assert len(json.loads(body)["history"]) == 1

    status, _, body = api(app, "POST", f"/api/reconciliation/exceptions/{exc_id}/transition",
                          {"to_state": "investigating", "actor": "api-test"})
    assert status == 200
    assert json.loads(body)["exception"]["state"] == "investigating"

    # Illegal: investigating -> open.
    status, _, body = api(app, "POST", f"/api/reconciliation/exceptions/{exc_id}/transition",
                          {"to_state": "open", "actor": "api-test"})
    assert status == 409

    status, _, body = api(app, "POST", f"/api/reconciliation/exceptions/{exc_id}/transition",
                          {"to_state": "resolved", "actor": "api-test"})
    assert status == 200

    status, _, body = api(app, "GET", f"/api/reconciliation/exceptions/{exc_id}")
    hist = json.loads(body)["history"]
    assert [(h["from_state"], h["to_state"]) for h in hist] == [
        (None, "open"), ("open", "investigating"), ("investigating", "resolved")]


def test_exception_transition_unknown_id(app):
    status, _, _ = api(app, "POST", "/api/reconciliation/exceptions/424242/transition",
                       {"to_state": "investigating"})
    assert status == 404


def test_aging_endpoint(app):
    load(app)
    status, _, body = api(app, "GET", "/api/reconciliation/aging")
    assert status == 200
    payload = json.loads(body)
    buckets = payload["aging"]
    assert buckets["current"]["outstanding_cents"] == 60_000
    assert buckets["1-30"]["outstanding_cents"] == 150_000
    assert buckets["31-60"]["outstanding_cents"] == 60_000
    assert buckets["61-90"]["outstanding_cents"] == 0
    assert buckets["90+"]["outstanding_cents"] == 30_000
    assert buckets["current"]["outstanding"] == "600.00"
    assert sum(b["outstanding_cents"] for b in buckets.values()) == 300_000


def test_pages_render(app):
    for path in ("/project_q05", "/project_q05/exceptions", "/project_q05/reports"):
        status, headers, body = wsgi_call(app, "GET", path)
        assert status == 200, path
        assert b"Q05" in body
    # Detail page for a real exception.
    load(app)
    status, _, body = api(app, "GET", "/api/reconciliation/exceptions",
                          query="state=open")
    exc_id = json.loads(body)["exceptions"][0]["id"]
    status, _, body = wsgi_call(app, "GET", f"/project_q05/exceptions/{exc_id}")
    assert status == 200
    assert b"Suggested next action" in body
    assert b"investigating" in body  # the legal next transition is offered


def test_form_upload_and_match_redirect(app):
    form = "kind=invoices&actor=web-test&csv=".replace("&", "&")
    import urllib.parse
    body = urllib.parse.urlencode({"kind": "invoices", "actor": "web-test",
                                   "csv": INVOICES_CSV}).encode()
    status, headers, _ = wsgi_call(app, "POST", "/project_q05/upload", body=body,
                                   content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"] == "/project_q05/exceptions"


def test_hub_and_nav_link_q05(app):
    status, _, body = wsgi_call(app, "GET", "/")
    assert status == 200
    assert b"Q05" in body
    assert b"/project_q05/exceptions" in body
