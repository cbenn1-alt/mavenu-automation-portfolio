"""Project P03 — API + page tests (WSGI, stdlib only). All data synthetic."""
import json

from tests.conftest import wsgi_call
from tests.test_docintel import DOCS_JSON, EXPECTED, NOW
from tests.test_reconciliation_api import wsgi_call_qs


def api(app, method, path, payload=None, query=""):
    body = b""
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    return wsgi_call_qs(app, method, path, query=query, body=body)


def load(app):
    status, _, body = api(app, "POST", "/api/docintel/upload",
                          {"format": "json", "payload": DOCS_JSON, "actor": "api-test"})
    assert status == 201, body
    status, _, body = api(app, "POST", "/api/docintel/extract", {"actor": "api-test"})
    assert status == 200, body
    return json.loads(body)


def test_upload_and_extract(app):
    stats = load(app)
    assert stats["documents"] == EXPECTED["document_count"]
    assert stats["accepted"] == EXPECTED["accepted_docs"]
    assert stats["needs_review"] == EXPECTED["needs_review_docs"]
    assert stats["exceptions_raised"] == 4  # duplicate raised at ingest
    status, _, body = api(app, "GET", "/api/docintel/summary")
    assert status == 200
    summary = json.loads(body)
    assert summary["document_count"] == EXPECTED["document_count"]
    assert summary["fields_total"] == EXPECTED["fields_total"]
    assert summary["accepted_money_cents"] == EXPECTED["accepted_money_cents"]
    assert summary["accepted_money"] == "52422.89"
    assert len(summary["review_backlog"]) == 4


def test_upload_invalid_format_rejected(app):
    status, _, body = api(app, "POST", "/api/docintel/upload",
                          {"format": "xml", "payload": "<x/>"})
    assert status == 422
    assert json.loads(body)["error"]["code"] == "validation_failed"


def test_upload_reports_row_errors(app):
    bad = json.dumps([
        {"doc_id": "DOC-OK-001", "doc_type": "invoice", "text": "Vendor: X\nTotal: $10.00\n"},
        {"doc_id": "DOC-BAD-001", "doc_type": "ledger", "text": "Vendor: X\n"},
    ])
    status, _, body = api(app, "POST", "/api/docintel/upload",
                          {"format": "json", "payload": bad})
    assert status == 201
    result = json.loads(body)
    assert result["inserted"] == 1
    assert len(result["errors"]) == 1


def test_documents_list_and_filter(app):
    load(app)
    status, _, body = api(app, "GET", "/api/docintel/documents")
    assert status == 200
    docs = json.loads(body)["documents"]
    assert len(docs) == EXPECTED["document_count"]
    status, _, body = api(app, "GET", "/api/docintel/documents", query="state=accepted")
    assert status == 200
    accepted = json.loads(body)["documents"]
    assert len(accepted) == EXPECTED["accepted_docs"]
    assert all(d["state"] == "accepted" for d in accepted)
    status, _, body = api(app, "GET", "/api/docintel/documents", query="doc_type=contract")
    assert len(json.loads(body)["documents"]) == 1


def test_document_detail_with_fields_and_history(app):
    load(app)
    status, _, body = api(app, "GET", "/api/docintel/documents/DOC-INV-002")
    assert status == 200
    payload = json.loads(body)
    doc = payload["document"]
    assert doc["state"] == "needs_review"
    assert doc["doc_confidence"] == "0.60"
    vendor = next(f for f in doc["fields"] if f["field_name"] == "vendor")
    assert vendor["status"] == "proposed"
    assert vendor["rule_id"] == "vendor_first_line"
    assert vendor["source_line"] == 1
    assert [(h["from_state"], h["to_state"]) for h in payload["history"]] == [
        ("ingested", "needs_review")]


def test_document_detail_unknown_id(app):
    status, _, body = api(app, "GET", "/api/docintel/documents/DOC-NOPE-001")
    assert status == 404


def test_field_review_flow(app):
    load(app)
    # Accept the proposed vendor field; the document becomes accepted and
    # its low_confidence exception resolves.
    status, _, body = api(
        app, "POST", "/api/docintel/documents/DOC-INV-002/fields/vendor/review",
        {"action": "accept", "actor": "api-test"})
    assert status == 200, body
    assert json.loads(body)["field"]["status"] == "accepted"
    status, _, body = api(app, "GET", "/api/docintel/documents/DOC-INV-002")
    assert json.loads(body)["document"]["state"] == "accepted"

    # Correct the missing due_date on INV-003.
    status, _, body = api(
        app, "POST", "/api/docintel/documents/DOC-INV-003/fields/due_date/review",
        {"action": "correct", "actor": "api-test", "corrected_value": "2026-10-17"})
    assert status == 200, body
    assert json.loads(body)["field"]["value_text"] == "2026-10-17"
    status, _, body = api(app, "GET", "/api/docintel/documents/DOC-INV-003")
    assert json.loads(body)["document"]["state"] == "accepted"


def test_field_review_illegal_actions(app):
    load(app)
    # Accept a missing field: nothing to accept.
    status, _, body = api(
        app, "POST", "/api/docintel/documents/DOC-INV-003/fields/due_date/review",
        {"action": "accept", "actor": "api-test"})
    assert status == 409
    # Correct an accepted, locked field.
    status, _, body = api(
        app, "POST", "/api/docintel/documents/DOC-INV-001/fields/vendor/review",
        {"action": "correct", "actor": "api-test", "corrected_value": "Other Co"})
    assert status == 409
    # Unknown action.
    status, _, body = api(
        app, "POST", "/api/docintel/documents/DOC-INV-002/fields/vendor/review",
        {"action": "shred", "actor": "api-test"})
    assert status == 409
    # Unknown field.
    status, _, body = api(
        app, "POST", "/api/docintel/documents/DOC-INV-002/fields/nope/review",
        {"action": "accept", "actor": "api-test"})
    assert status == 404


def test_document_reject_flow(app):
    load(app)
    status, _, body = api(app, "POST", "/api/docintel/documents/DOC-GARBAGE-001/reject",
                          {"actor": "api-test", "detail": "unreadable"})
    assert status == 200
    assert json.loads(body)["document"]["state"] == "rejected"
    # Rejecting again is illegal.
    status, _, body = api(app, "POST", "/api/docintel/documents/DOC-GARBAGE-001/reject",
                          {"actor": "api-test"})
    assert status == 409


def test_exceptions_list_and_transition(app):
    load(app)
    status, _, body = api(app, "GET", "/api/docintel/exceptions")
    assert status == 200
    excs = json.loads(body)["exceptions"]
    assert len(excs) == EXPECTED["open_exceptions"]
    kinds = {e["kind"] for e in excs}
    assert kinds == {"low_confidence", "missing_field", "validation_failed",
                     "duplicate_document", "unparseable_document"}
    status, _, body = api(app, "GET", "/api/docintel/exceptions",
                          query="kind=missing_field")
    assert status == 200
    missing = json.loads(body)["exceptions"]
    assert len(missing) == 1
    assert all(e["suggested_action"] for e in missing)

    exc_id = missing[0]["id"]
    status, _, body = api(app, "GET", f"/api/docintel/exceptions/{exc_id}")
    assert status == 200
    assert len(json.loads(body)["history"]) == 1

    # Illegal: open -> resolved is not a legal move.
    status, _, body = api(app, "POST", f"/api/docintel/exceptions/{exc_id}/transition",
                          {"to_state": "resolved", "actor": "api-test"})
    assert status == 409
    status, _, body = api(app, "POST", f"/api/docintel/exceptions/{exc_id}/transition",
                          {"to_state": "investigating", "actor": "api-test"})
    assert status == 200
    status, _, body = api(app, "POST", f"/api/docintel/exceptions/{exc_id}/transition",
                          {"to_state": "resolved", "actor": "api-test"})
    assert status == 200


def test_exception_transition_unknown_id(app):
    status, _, _ = api(app, "POST", "/api/docintel/exceptions/424242/transition",
                       {"to_state": "investigating"})
    assert status == 404


def test_pages_render(app):
    for path in ("/project03", "/project03/documents",
                 "/project03/exceptions", "/project03/reports"):
        status, headers, body = wsgi_call(app, "GET", path)
        assert status == 200, path
        assert b"P03" in body
    load(app)
    status, _, body = wsgi_call(app, "GET", "/project03/documents/DOC-INV-002")
    assert status == 200
    assert b"vendor" in body
    assert b"Accept" in body  # the legal next review action is offered
    status, _, body = api(app, "GET", "/api/docintel/exceptions",
                          query="state=open")
    exc_id = json.loads(body)["exceptions"][0]["id"]
    status, _, body = wsgi_call(app, "GET", f"/project03/exceptions/{exc_id}")
    assert status == 200
    assert b"Suggested next action" in body


def test_detail_page_offers_correction_only_for_flagged_accepted_field(app):
    load(app)
    # DOC-RCP-002: payment_method is accepted but flagged by an open
    # validation_failed exception — the Correct form must be offered.
    status, _, body = wsgi_call(app, "GET", "/project03/documents/DOC-RCP-002")
    assert status == 200
    assert b"flagged invalid" in body
    assert b"Correct" in body
    # DOC-INV-001: clean accepted document — every field locked, no
    # Correct form anywhere on the page.
    status, _, body = wsgi_call(app, "GET", "/project03/documents/DOC-INV-001")
    assert status == 200
    assert b"locked (accepted)" in body
    assert b"flagged invalid" not in body
    assert b"Correct" not in body


def test_form_upload_and_extract_redirect(app):
    import urllib.parse
    body = urllib.parse.urlencode({"format": "json", "actor": "web-test",
                                   "payload": DOCS_JSON}).encode()
    status, headers, _ = wsgi_call(app, "POST", "/project03/upload", body=body,
                                   content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"] == "/project03/documents"
    body = urllib.parse.urlencode({"actor": "web-test"}).encode()
    status, headers, _ = wsgi_call(app, "POST", "/project03/extract", body=body,
                                   content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"] == "/project03/documents"


def test_hub_and_nav_link_p03(app):
    status, _, body = wsgi_call(app, "GET", "/")
    assert status == 200
    assert b"P03" in body
    assert b"/project03/documents" in body
    assert b"Gate C" in body
