"""Project P03 — AI Document Intelligence & Exception Management: service tests.

All data is synthetic. Amounts are invented; names are fictional stand-ins.
Extraction here is deterministic and rule-based — no model, no black box.
"""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.docintel import (
    ACCEPT_THRESHOLD,
    doc_history,
    exception_aging,
    exception_history,
    extract_all,
    extract_document,
    extraction_summary,
    field_history,
    get_document,
    ingest_csv,
    ingest_json,
    ingest_text,
    list_documents,
    list_exceptions,
    reject_document,
    review_backlog,
    review_field,
    transition_exception,
)
from mavenu.extraction import (
    document_confidence,
    extract_fields,
    validate_corrected_value,
    validate_document,
)
from mavenu.workflow import DOC_WORKFLOW, EXCEPTION_WORKFLOW, InvalidTransition

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Hand-built fixture — every expectation below is hand-computed.
# ---------------------------------------------------------------------------

DOCS = [
    {
        "doc_id": "DOC-INV-001",
        "doc_type": "invoice",
        "text": (
            "Vendor: Acme Test Co\n"
            "Invoice No: INV-2026-1042\n"
            "Invoice Date: 2026-09-15\n"
            "Due Date: 2026-10-15\n"
            "Total: $1,250.00\n"
        ),
    },
    {
        "doc_id": "DOC-INV-002",
        "doc_type": "invoice",
        "text": (
            "Brightfield Services\n"
            "Invoice No: INV-2026-1043\n"
            "Invoice Date: 2026-09-16\n"
            "Due Date: 2026-10-16\n"
            "Total: $875.50\n"
        ),
    },
    {
        "doc_id": "DOC-INV-003",
        "doc_type": "invoice",
        "text": (
            "Vendor: Cedar Works LLC\n"
            "Invoice No: INV-2026-1044\n"
            "Invoice Date: 2026-09-17\n"
            "Total: $2,100.00\n"
        ),
    },
    {
        "doc_id": "DOC-RCP-001",
        "doc_type": "receipt",
        "text": (
            "Merchant: Harborlight Cafe\n"
            "Date: 2026-10-02\n"
            "Total: $64.99\n"
            "Payment Method: card\n"
        ),
    },
    {
        "doc_id": "DOC-RCP-002",
        "doc_type": "receipt",
        "text": (
            "Merchant: Granite Supply\n"
            "Date: 2026-10-03\n"
            "Total: $132.40\n"
            "Payment Method: crypto\n"
        ),
    },
    {
        "doc_id": "DOC-CTR-001",
        "doc_type": "contract",
        "text": (
            "Counterparty: Dovetail Partners\n"
            "Title: Master Services Agreement\n"
            "Effective Date: October 1, 2026\n"
            "Term: 12 months\n"
            "Total: $48,000.00\n"
        ),
    },
    {
        "doc_id": "DOC-GARBAGE-001",
        "doc_type": "invoice",
        "text": "lorem ipsum dolor sit amet\nconsectetur adipiscing elit\n",
    },
    # Within-batch duplicate of DOC-INV-001: skipped, raises an exception.
    {
        "doc_id": "DOC-INV-001",
        "doc_type": "invoice",
        "text": (
            "Vendor: Acme Test Co\n"
            "Invoice No: INV-2026-1042\n"
            "Invoice Date: 2026-09-15\n"
            "Due Date: 2026-10-15\n"
            "Total: $1,250.00\n"
        ),
    },
]

DOCS_JSON = json.dumps(DOCS)

CSV_FIXTURE = (
    "doc_id,doc_type,text\n"
    'DOC-CSV-001,invoice,"Vendor: Foxglove Inc\n'
    "Invoice No: INV-2026-2001\n"
    "Invoice Date: 2026-09-20\n"
    "Due Date: 2026-10-20\n"
    'Total: $300.00"\n'
    'DOC-CSV-002,receipt,"Merchant: Elm Street Co-op\n'
    "Date: 2026-10-04\n"
    "Total: $45.10\n"
    'Payment Method: cash"\n'
)

# Hand-computed expectations (see EVIDENCE_MATRIX.md for the arithmetic).
EXPECTED = {
    "document_count": 7,
    "accepted_docs": 3,          # INV-001, RCP-001, CTR-001
    "needs_review_docs": 4,      # INV-002, INV-003, RCP-002, GARBAGE-001
    "fields_total": 33,          # invoice 5x4 + receipt 4x2 + contract 5
    "fields_accepted": 26,
    "fields_proposed": 1,        # INV-002 vendor at 0.60
    "fields_rejected": 0,
    "fields_missing": 6,         # INV-003 due_date + GARBAGE 5 fields
    "accepted_money_cents": 5_242_289,  # 1250.00+875.50+2100.00+64.99+132.40+48000.00
    "open_exceptions": 5,        # low_confidence + missing_field +
                                 # validation_failed + duplicate_document +
                                 # unparseable_document
}


def load_fixture(conn):
    result = ingest_json(conn, DOCS_JSON, actor="test", now=NOW)
    assert result["inserted"] == EXPECTED["document_count"], result
    return extract_all(conn, actor="test", now=NOW)


def doc_state(conn, doc_id):
    return get_document(conn, doc_id)["state"]


def field_status(conn, doc_id, field_name):
    doc = get_document(conn, doc_id)
    field = next(f for f in doc["fields"] if f["field_name"] == field_name)
    return field


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def test_ingest_json_happy_path_counts(conn):
    result = ingest_json(conn, DOCS_JSON, actor="test", now=NOW)
    assert result["inserted"] == 7
    assert result["skipped_idempotent"] == 0
    assert result["errors"] == []
    assert result["batch"].startswith("doc:")
    assert list_documents(conn) != []
    assert len(list_documents(conn)) == 7
    assert all(d["state"] == "ingested" for d in list_documents(conn))


def test_ingest_json_row_errors_do_not_abort_batch(conn):
    bad = json.dumps([
        {"doc_id": "DOC-OK-001", "doc_type": "invoice",
         "text": "Vendor: Acme Test Co\nTotal: $10.00\n"},
        {"doc_id": "DOC-BAD-001", "doc_type": "ledger", "text": "Vendor: X\n"},
        {"doc_id": "DOC-BAD-002", "doc_type": "invoice", "text": "   "},
        {"doc_id": "", "doc_type": "invoice", "text": "Vendor: X\n"},
        {"doc_id": "DOC-OK-002", "doc_type": "receipt",
         "text": "Merchant: Y\nTotal: $5.00\n"},
    ])
    result = ingest_json(conn, bad, actor="test", now=NOW)
    assert result["inserted"] == 2
    assert len(result["errors"]) == 3
    rows = {e["row"] for e in result["errors"]}
    assert rows == {2, 3, 4}
    assert any("doc_type" in e for e in result["errors"])
    assert any("text" in e for e in result["errors"])
    assert any("doc_id" in e for e in result["errors"])


def test_ingest_json_invalid_json_is_fatal(conn):
    result = ingest_json(conn, "{not json", actor="test", now=NOW)
    assert result["inserted"] == 0
    assert len(result["errors"]) == 1
    assert "fatal" in result["errors"][0]


def test_ingest_json_non_array_is_fatal(conn):
    result = ingest_json(conn, '{"doc_id": "X"}', actor="test", now=NOW)
    assert result["inserted"] == 0
    assert "fatal" in result["errors"][0]


def test_ingest_reingest_is_idempotent(conn):
    first = ingest_json(conn, DOCS_JSON, actor="test", now=NOW)
    assert first["inserted"] == 7
    second = ingest_json(conn, DOCS_JSON, actor="test", now=NOW)
    assert second["inserted"] == 0
    # 8 rows in the batch (7 unique + the within-batch repeat): every one
    # is an idempotent skip on re-ingest, and no second duplicate
    # exception is raised — re-ingest is fully idempotent.
    assert second["skipped_idempotent"] == 8
    assert len(list_documents(conn)) == 7
    assert len(list_exceptions(conn)) == 1  # the one duplicate_document row


def test_ingest_csv_happy_path(conn):
    result = ingest_csv(conn, CSV_FIXTURE, actor="test", now=NOW)
    assert result["inserted"] == 2
    assert result["errors"] == []
    stats = extract_all(conn, actor="test", now=NOW)
    assert stats["documents"] == 2
    assert stats["accepted"] == 2
    assert stats["needs_review"] == 0


def test_ingest_csv_missing_columns_is_fatal(conn):
    result = ingest_csv(conn, "doc_id,doc_type\nDOC-X,invoice\n", actor="test", now=NOW)
    assert result["inserted"] == 0
    assert "fatal" in result["errors"][0]


def test_ingest_text_single_document(conn):
    result = ingest_text(conn, "DOC-TXT-001", "invoice",
                         "Vendor: Acme Test Co\nTotal: $10.00\n",
                         actor="test", now=NOW)
    assert result["inserted"] == 1
    assert result["kind"] == "ingest_text"


def test_formula_doc_id_sanitized_text_untouched(conn):
    # Metadata (doc_id) is sanitized like any CSV cell; the document TEXT
    # is content and is stored exactly as submitted so extraction sees it.
    result = ingest_text(conn, "=cmd|'/C calc'!A0", "invoice",
                         "Vendor: Acme Test Co\nTotal: $10.00\n",
                         actor="test", now=NOW)
    assert result["inserted"] == 1
    assert result["sanitized"] == 1
    docs = list_documents(conn)
    assert docs[0]["doc_id"] == "'=cmd|'/C calc'!A0"
    stored = get_document(conn, docs[0]["doc_id"])
    assert stored["source_format"] == "text"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_extract_clean_invoice_all_fields_provenance():
    text = DOCS[0]["text"]
    ex = extract_fields("invoice", text)
    assert ex["vendor"].value == "Acme Test Co"
    assert ex["vendor"].confidence == Decimal("0.90")
    assert ex["vendor"].rule_id == "vendor_labeled"
    assert ex["vendor"].source_line == 1
    assert ex["vendor"].raw_text == "Vendor: Acme Test Co"
    assert ex["invoice_number"].value == "INV-2026-1042"
    assert ex["invoice_number"].confidence == Decimal("0.95")
    assert ex["invoice_number"].source_line == 2
    assert ex["invoice_date"].value == "2026-09-15"
    assert ex["due_date"].value == "2026-10-15"
    assert ex["total_amount"].value == "1250.00"
    assert ex["total_amount"].value_cents == 125_000
    assert ex["total_amount"].rule_id == "total_strict"
    assert ex["total_amount"].source_line == 5
    assert document_confidence(ex) == Decimal("0.90")


def test_extract_vendor_first_line_fallback_below_threshold():
    ex = extract_fields("invoice", DOCS[1]["text"])
    assert ex["vendor"].value == "Brightfield Services"
    assert ex["vendor"].confidence == Decimal("0.60")
    assert ex["vendor"].rule_id == "vendor_first_line"
    assert ex["vendor"].confidence < ACCEPT_THRESHOLD


def test_extract_date_formats_and_boundary():
    iso = extract_fields("invoice", "Invoice Date: 2026-09-15\nVendor: X\n")
    assert iso["invoice_date"].value == "2026-09-15"
    assert iso["invoice_date"].confidence == Decimal("0.95")
    us = extract_fields("invoice", "Invoice Date: 09/16/2026\nVendor: X\n")
    assert us["invoice_date"].value == "2026-09-16"
    assert us["invoice_date"].confidence == Decimal("0.85")
    longf = extract_fields("invoice", "Invoice Date: September 17, 2026\nVendor: X\n")
    assert longf["invoice_date"].value == "2026-09-17"
    # 0.80 is the accept boundary: at threshold means auto-accepted.
    assert longf["invoice_date"].confidence == Decimal("0.80")
    assert longf["invoice_date"].confidence >= ACCEPT_THRESHOLD


def test_extract_total_largest_fallback_below_threshold():
    text = (
        "Vendor: Test Vendor LLC\n"
        "Invoice No: INV-2026-9001\n"
        "Invoice Date: 2026-09-01\n"
        "Due Date: 2026-10-01\n"
        "Please remit $250.00 at your earliest convenience.\n"
    )
    ex = extract_fields("invoice", text)
    assert ex["total_amount"].value == "250.00"
    assert ex["total_amount"].value_cents == 25_000
    assert ex["total_amount"].rule_id == "total_largest"
    assert ex["total_amount"].confidence == Decimal("0.70")
    assert ex["total_amount"].confidence < ACCEPT_THRESHOLD


def test_extract_bare_invoice_number():
    text = "Vendor: Acme Test Co\nPlease reference INV 1042 for payment.\nTotal: $10.00\n"
    ex = extract_fields("invoice", text)
    assert ex["invoice_number"].value == "INV 1042"
    assert ex["invoice_number"].rule_id == "invnum_bare"
    assert ex["invoice_number"].confidence == Decimal("0.80")


def test_extract_garbage_document_zero_fields():
    ex = extract_fields("invoice", DOCS[6]["text"])
    assert all(v is None for v in ex.values())
    assert document_confidence(ex) is None


def test_extract_determinism():
    text = DOCS[0]["text"]
    first = {k: (v.as_dict() if v else None) for k, v in extract_fields("invoice", text).items()}
    second = {k: (v.as_dict() if v else None) for k, v in extract_fields("invoice", text).items()}
    assert first == second


def test_extract_unknown_doc_type_rejected():
    with pytest.raises(ValueError):
        extract_fields("ledger", "Vendor: X\n")


def test_extract_twice_rejected(conn):
    ingest_text(conn, "DOC-TXT-001", "invoice",
                "Vendor: Acme Test Co\nTotal: $10.00\n", actor="test", now=NOW)
    extract_document(conn, "DOC-TXT-001", actor="test", now=NOW)
    with pytest.raises(ValueError, match="only 'ingested' documents"):
        extract_document(conn, "DOC-TXT-001", actor="test", now=NOW)


def test_extract_unknown_doc_id(conn):
    with pytest.raises(KeyError):
        extract_document(conn, "DOC-NOPE-001", actor="test", now=NOW)


def test_document_confidence_weakest_link():
    ex = extract_fields("contract", DOCS[5]["text"])
    # counterparty 0.90, title 0.90, effective_date 0.80, term 0.95, total 0.95
    assert document_confidence(ex) == Decimal("0.80")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_validation_payment_method_unknown():
    ex = extract_fields("receipt", DOCS[4]["text"])
    failures = validate_document("receipt", ex, today=NOW.date())
    assert len(failures) == 1
    assert failures[0]["rule_id"] == "payment_method_known"
    assert failures[0]["field"] == "payment_method"


def test_validation_due_before_issued():
    text = (
        "Vendor: Acme Test Co\n"
        "Invoice No: INV-2026-1042\n"
        "Invoice Date: 2026-10-15\n"
        "Due Date: 2026-09-15\n"
        "Total: $100.00\n"
    )
    ex = extract_fields("invoice", text)
    failures = validate_document("invoice", ex, today=NOW.date())
    assert any(f["rule_id"] == "due_not_before_issued" for f in failures)


def test_validation_receipt_date_future():
    text = (
        "Merchant: Harborlight Cafe\n"
        "Date: 2026-12-25\n"
        "Total: $64.99\n"
        "Payment Method: card\n"
    )
    ex = extract_fields("receipt", text)
    failures = validate_document("receipt", ex, today=NOW.date())
    assert any(f["rule_id"] == "receipt_date_not_future" for f in failures)


def test_validation_term_zero():
    text = (
        "Counterparty: Dovetail Partners\n"
        "Title: Master Services Agreement\n"
        "Effective Date: 2026-10-01\n"
        "Term: 0 months\n"
        "Total: $100.00\n"
    )
    ex = extract_fields("contract", text)
    failures = validate_document("contract", ex, today=NOW.date())
    assert any(f["rule_id"] == "term_positive" for f in failures)


def test_validation_skips_missing_fields():
    # INV-003 has no due_date: no due_not_before_issued failure is raised
    # for a field that does not exist — the missing field has its own
    # exception instead.
    ex = extract_fields("invoice", DOCS[2]["text"])
    failures = validate_document("invoice", ex, today=NOW.date())
    assert failures == []


# ---------------------------------------------------------------------------
# End-to-end fixture: extraction, exceptions, states
# ---------------------------------------------------------------------------

def test_fixture_extract_all_counts(conn):
    stats = load_fixture(conn)
    assert stats["documents"] == 7
    assert stats["accepted"] == EXPECTED["accepted_docs"]
    assert stats["needs_review"] == EXPECTED["needs_review_docs"]
    assert stats["exceptions_raised"] == 4  # duplicate raised at ingest, not here
    assert doc_state(conn, "DOC-INV-001") == "accepted"
    assert doc_state(conn, "DOC-RCP-001") == "accepted"
    assert doc_state(conn, "DOC-CTR-001") == "accepted"
    assert doc_state(conn, "DOC-INV-002") == "needs_review"
    assert doc_state(conn, "DOC-INV-003") == "needs_review"
    assert doc_state(conn, "DOC-RCP-002") == "needs_review"
    assert doc_state(conn, "DOC-GARBAGE-001") == "needs_review"


def test_fixture_exception_queue_contents(conn):
    load_fixture(conn)
    excs = list_exceptions(conn)
    assert len(excs) == EXPECTED["open_exceptions"]
    by_kind = {}
    for e in excs:
        by_kind.setdefault(e["kind"], []).append(e)
    assert set(by_kind) == {
        "low_confidence", "missing_field", "validation_failed",
        "duplicate_document", "unparseable_document",
    }
    assert by_kind["low_confidence"][0]["field_name"] == "vendor"
    assert by_kind["low_confidence"][0]["ref_public_id"] == "DOC-INV-002"
    assert by_kind["low_confidence"][0]["detail"]["confidence"] == "0.60"
    assert by_kind["missing_field"][0]["field_name"] == "due_date"
    assert by_kind["missing_field"][0]["ref_public_id"] == "DOC-INV-003"
    assert by_kind["validation_failed"][0]["detail"]["rule_id"] == "payment_method_known"
    assert by_kind["duplicate_document"][0]["ref_public_id"] == "DOC-INV-001"
    assert by_kind["unparseable_document"][0]["ref_public_id"] == "DOC-GARBAGE-001"
    assert all(e["state"] == "open" for e in excs)
    assert all(e["suggested_action"] for e in excs)


def test_unparseable_document_has_no_missing_field_exceptions(conn):
    load_fixture(conn)
    garbage_missing = [
        e for e in list_exceptions(conn)
        if e["ref_public_id"] == "DOC-GARBAGE-001" and e["kind"] == "missing_field"
    ]
    assert garbage_missing == []


def test_fixture_field_statuses(conn):
    load_fixture(conn)
    assert field_status(conn, "DOC-INV-002", "vendor")["status"] == "proposed"
    assert field_status(conn, "DOC-INV-002", "vendor")["confidence"] == "0.60"
    assert field_status(conn, "DOC-INV-003", "due_date")["status"] == "missing"
    assert field_status(conn, "DOC-INV-003", "due_date")["value_text"] is None
    assert field_status(conn, "DOC-CTR-001", "effective_date")["status"] == "accepted"
    assert field_status(conn, "DOC-CTR-001", "effective_date")["confidence"] == "0.80"
    doc = get_document(conn, "DOC-GARBAGE-001")
    assert all(f["status"] == "missing" for f in doc["fields"])
    assert doc["doc_confidence"] is None


# ---------------------------------------------------------------------------
# Exception state machine
# ---------------------------------------------------------------------------

def test_exception_legal_transitions(conn):
    load_fixture(conn)
    exc = next(e for e in list_exceptions(conn) if e["kind"] == "missing_field")
    exc_id = exc["id"]
    assert len(exception_history(conn, exc_id)) == 1
    transition_exception(conn, exc_id, "investigating", actor="op-1", now=NOW)
    transition_exception(conn, exc_id, "written_off", actor="op-1",
                         detail="accepted loss", now=NOW)
    hist = exception_history(conn, exc_id)
    assert [(h["from_state"], h["to_state"]) for h in hist] == [
        (None, "open"), ("open", "investigating"), ("investigating", "written_off")]
    assert all(h["actor"] == "op-1" for h in hist[1:])


@pytest.mark.parametrize("from_to", [
    ("open", "resolved"),
    ("open", "written_off"),
    ("investigating", "open"),
    ("resolved", "investigating"),
    ("written_off", "resolved"),
    ("resolved", "written_off"),
])
def test_exception_illegal_transitions(conn, from_to):
    load_fixture(conn)
    exc = next(e for e in list_exceptions(conn) if e["kind"] == "missing_field")
    exc_id = exc["id"]
    from_state, to_state = from_to
    if from_state == "investigating":
        transition_exception(conn, exc_id, "investigating", actor="test", now=NOW)
    elif from_state in ("resolved", "written_off"):
        transition_exception(conn, exc_id, "investigating", actor="test", now=NOW)
        transition_exception(conn, exc_id, from_state, actor="test", now=NOW)
    with pytest.raises(InvalidTransition):
        transition_exception(conn, exc_id, to_state, actor="test", now=NOW)


def test_exception_unknown_id(conn):
    with pytest.raises(KeyError):
        transition_exception(conn, 424242, "investigating", actor="test", now=NOW)


def test_doc_workflow_states():
    assert DOC_WORKFLOW.can("ingested", "needs_review")
    assert DOC_WORKFLOW.can("ingested", "accepted")
    assert DOC_WORKFLOW.can("needs_review", "accepted")
    assert not DOC_WORKFLOW.can("accepted", "needs_review")
    assert not DOC_WORKFLOW.can("rejected", "accepted")
    assert EXCEPTION_WORKFLOW.can("open", "investigating")
    assert not EXCEPTION_WORKFLOW.can("open", "resolved")


# ---------------------------------------------------------------------------
# Human review of fields
# ---------------------------------------------------------------------------

def test_review_accept_proposed_field_resolves_doc(conn):
    load_fixture(conn)
    field = review_field(conn, "DOC-INV-002", "vendor", "accept",
                         actor="op-1", now=NOW)
    assert field["status"] == "accepted"
    assert field["corrected"] is False
    assert doc_state(conn, "DOC-INV-002") == "accepted"
    # The low_confidence exception resolved itself through the workflow.
    excs = [e for e in list_exceptions(conn)
            if e["kind"] == "low_confidence" and e["ref_public_id"] == "DOC-INV-002"]
    assert excs[0]["state"] == "resolved"
    hist = field_history(conn, "DOC-INV-002", "vendor")
    assert [(h["action"], h["from_status"], h["to_status"]) for h in hist] == [
        ("accept", "proposed", "accepted")]


def test_review_correct_missing_field_resolves_doc(conn):
    load_fixture(conn)
    field = review_field(conn, "DOC-INV-003", "due_date", "correct",
                         actor="op-1", corrected_value="2026-10-17", now=NOW)
    assert field["status"] == "accepted"
    assert field["value_text"] == "2026-10-17"
    assert field["corrected"] is True
    assert field["corrected_value_text"] == "2026-10-17"
    assert doc_state(conn, "DOC-INV-003") == "accepted"
    excs = [e for e in list_exceptions(conn)
            if e["kind"] == "missing_field" and e["ref_public_id"] == "DOC-INV-003"]
    assert excs[0]["state"] == "resolved"


def test_review_correct_accepted_but_invalid_field(conn):
    # RCP-002's payment_method was extracted at 0.95 (auto-accepted) yet
    # fails validation ('crypto'). The lock has one exception: a field
    # flagged by an open validation_failed exception is correctable.
    load_fixture(conn)
    field = review_field(conn, "DOC-RCP-002", "payment_method", "correct",
                         actor="op-1", corrected_value="card", now=NOW)
    assert field["status"] == "accepted"
    assert field["value_text"] == "card"
    assert doc_state(conn, "DOC-RCP-002") == "accepted"
    excs = [e for e in list_exceptions(conn)
            if e["kind"] == "validation_failed" and e["ref_public_id"] == "DOC-RCP-002"]
    assert excs[0]["state"] == "resolved"


def test_review_correct_locked_accepted_field_rejected(conn):
    load_fixture(conn)
    with pytest.raises(ValueError, match="locked"):
        review_field(conn, "DOC-INV-001", "vendor", "correct",
                     actor="op-1", corrected_value="Other Co", now=NOW)


def test_review_correct_rejects_bad_value(conn):
    load_fixture(conn)
    with pytest.raises(ValueError, match="Corrected value rejected"):
        review_field(conn, "DOC-RCP-002", "payment_method", "correct",
                     actor="op-1", corrected_value="bitcoin", now=NOW)
    with pytest.raises(ValueError, match="Corrected value rejected"):
        review_field(conn, "DOC-INV-003", "due_date", "correct",
                     actor="op-1", corrected_value="17/10/2026", now=NOW)


def test_review_reject_proposed_field_keeps_doc_open(conn):
    load_fixture(conn)
    field = review_field(conn, "DOC-INV-002", "vendor", "reject",
                         actor="op-1", now=NOW)
    assert field["status"] == "rejected"
    # The document cannot become accepted with a rejected field.
    assert doc_state(conn, "DOC-INV-002") == "needs_review"
    # The low_confidence exception stays open until the field is corrected.
    excs = [e for e in list_exceptions(conn)
            if e["kind"] == "low_confidence" and e["ref_public_id"] == "DOC-INV-002"]
    assert excs[0]["state"] == "open"
    # Correcting the rejected field completes the document.
    review_field(conn, "DOC-INV-002", "vendor", "correct",
                 actor="op-1", corrected_value="Brightfield Services", now=NOW)
    assert doc_state(conn, "DOC-INV-002") == "accepted"
    excs = [e for e in list_exceptions(conn)
            if e["kind"] == "low_confidence" and e["ref_public_id"] == "DOC-INV-002"]
    assert excs[0]["state"] == "resolved"


def test_review_accept_missing_field_rejected(conn):
    load_fixture(conn)
    with pytest.raises(ValueError, match="only a proposed"):
        review_field(conn, "DOC-INV-003", "due_date", "accept",
                     actor="op-1", now=NOW)


def test_review_unknown_action(conn):
    load_fixture(conn)
    with pytest.raises(ValueError, match="Unknown review action"):
        review_field(conn, "DOC-INV-002", "vendor", "shred",
                     actor="op-1", now=NOW)


def test_review_unknown_field(conn):
    load_fixture(conn)
    with pytest.raises(KeyError):
        review_field(conn, "DOC-INV-002", "no_such_field", "accept",
                     actor="op-1", now=NOW)


def test_reject_document_terminal(conn):
    load_fixture(conn)
    doc = reject_document(conn, "DOC-GARBAGE-001", actor="op-1",
                          detail="unreadable scan", now=NOW)
    assert doc["state"] == "rejected"
    hist = doc_history(conn, "DOC-GARBAGE-001")
    assert [(h["from_state"], h["to_state"]) for h in hist] == [
        ("ingested", "needs_review"), ("needs_review", "rejected")]
    with pytest.raises(InvalidTransition):
        reject_document(conn, "DOC-GARBAGE-001", actor="op-1", now=NOW)


def test_doc_history_single_accept_path(conn):
    load_fixture(conn)
    hist = doc_history(conn, "DOC-INV-001")
    assert [(h["from_state"], h["to_state"]) for h in hist] == [
        ("ingested", "accepted")]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def test_summary_matches_hand_computed_expectations(conn):
    load_fixture(conn)
    s = extraction_summary(conn)
    assert s["document_count"] == EXPECTED["document_count"]
    assert s["documents_by_state"] == {"accepted": 3, "needs_review": 4}
    assert s["documents_by_type"] == {"invoice": 4, "receipt": 2, "contract": 1}
    assert s["fields_total"] == EXPECTED["fields_total"]
    assert s["fields_by_status"] == {
        "accepted": 26, "proposed": 1, "missing": 6,
    }
    assert s["accepted_money_cents"] == EXPECTED["accepted_money_cents"]
    assert s["accepted_money"] == Decimal("52422.89")
    assert s["exceptions_by_state"] == {"open": 5}
    assert s["exceptions_by_kind"] == {
        "low_confidence": 1, "missing_field": 1, "validation_failed": 1,
        "duplicate_document": 1, "unparseable_document": 1,
    }


def test_run_log_records_ingest_and_extract(conn):
    ingest_json(conn, DOCS_JSON, actor="op-1", now=NOW)
    extract_all(conn, actor="op-1", now=NOW)
    rows = conn.execute(
        "SELECT kind, actor, stats_json FROM docintel_runs ORDER BY id"
    ).fetchall()
    kinds = [r["kind"] for r in rows]
    assert kinds == ["ingest_json", "extract"]
    assert all(r["actor"] == "op-1" for r in rows)
    stats = json.loads(rows[1]["stats_json"])
    assert stats["documents"] == 7
    assert stats["accepted"] == 3


def test_summary_field_identity(conn):
    load_fixture(conn)
    s = extraction_summary(conn)
    by_status = s["fields_by_status"]
    assert (by_status.get("accepted", 0) + by_status.get("proposed", 0)
            + by_status.get("rejected", 0) + by_status.get("missing", 0)) == s["fields_total"]
    # Independent raw-SQL recomputation (no service code).
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS acc, "
        "SUM(CASE WHEN status='proposed' THEN 1 ELSE 0 END) AS prop, "
        "SUM(CASE WHEN status='missing' THEN 1 ELSE 0 END) AS miss "
        "FROM docintel_fields"
    ).fetchone()
    assert row["total"] == s["fields_total"]
    assert row["acc"] == 26 and row["prop"] == 1 and row["miss"] == 6


def test_summary_money_excludes_proposed_values(conn):
    # A money field extracted below threshold is proposed — it must NOT
    # count in the accepted money total until a human accepts it.
    ingest_text(conn, "DOC-LOW-001", "invoice",
                "Vendor: Test Vendor LLC\n"
                "Invoice No: INV-2026-9001\n"
                "Invoice Date: 2026-09-01\n"
                "Due Date: 2026-10-01\n"
                "Please remit $250.00 at your earliest convenience.\n",
                actor="test", now=NOW)
    extract_all(conn, actor="test", now=NOW)
    s = extraction_summary(conn)
    assert s["accepted_money_cents"] == 0
    assert s["fields_by_status"]["proposed"] == 1
    review_field(conn, "DOC-LOW-001", "total_amount", "accept",
                 actor="op-1", now=NOW)
    s = extraction_summary(conn)
    assert s["accepted_money_cents"] == 25_000


def test_exception_aging_buckets(conn):
    load_fixture(conn)
    # Backdate one exception 83 days so it lands in the 31+ bucket.
    conn.execute(
        "UPDATE docintel_exceptions SET created_at = ? "
        "WHERE kind = 'duplicate_document'",
        ((NOW - timedelta(days=83)).isoformat(timespec="seconds"),),
    )
    conn.commit()
    aging = exception_aging(conn, now=NOW)
    assert aging["buckets"]["0-7 days"]["exception_count"] == 4
    assert aging["buckets"]["31+ days"]["exception_count"] == 1
    assert aging["buckets"]["31+ days"]["kinds"] == {"duplicate_document": 1}
    assert aging["buckets"]["8-30 days"]["exception_count"] == 0


def test_review_backlog_contents(conn):
    load_fixture(conn)
    backlog = review_backlog(conn)
    assert [b["doc_id"] for b in backlog] == [
        "DOC-INV-002", "DOC-INV-003", "DOC-RCP-002", "DOC-GARBAGE-001"]
    by_id = {b["doc_id"]: b for b in backlog}
    assert by_id["DOC-INV-002"]["unresolved_fields"] == ["vendor"]
    # The duplicate_document exception belongs to DOC-INV-001 (the
    # duplicated doc), which is accepted — so it is not in this backlog
    # entry. It stays visible in the exception queue itself.
    assert by_id["DOC-INV-002"]["open_exception_kinds"] == ["low_confidence"]
    assert by_id["DOC-GARBAGE-001"]["unresolved_fields"] == [
        "vendor", "invoice_number", "invoice_date", "due_date", "total_amount"]
    assert by_id["DOC-GARBAGE-001"]["open_exception_kinds"] == ["unparseable_document"]


# ---------------------------------------------------------------------------
# Decimal money math
# ---------------------------------------------------------------------------

def test_amounts_parse_via_decimal():
    # 0.29 via Decimal is 29 cents; float would give 28.9999... cents.
    value, cents = validate_corrected_value("invoice", "total_amount", "0.29")
    assert cents == 29
    assert value == "0.29"
    assert isinstance(value, str)


def test_summary_money_values_are_decimal(conn):
    load_fixture(conn)
    s = extraction_summary(conn)
    assert isinstance(s["accepted_money"], Decimal)


# ---------------------------------------------------------------------------
# Migration rollback
# ---------------------------------------------------------------------------

def test_migration_021_down_step_rolls_back_for_real(conn):
    assert "021_docintel.sql" in applied_migrations(conn)
    load_fixture(conn)
    assert rollback_migration(conn, "021_docintel.sql") is True
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'docintel_%'"
    ).fetchall()}
    assert tables == set()
    assert "021_docintel.sql" not in applied_migrations(conn)
    # P01/P02/Q05 tables untouched.
    assert conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"] >= 0
    assert conn.execute("SELECT COUNT(*) c FROM recon_invoices").fetchone()["c"] >= 0
    # Re-apply works cleanly.
    assert run_migrations(conn) == ["021_docintel.sql"]
    assert "021_docintel.sql" in applied_migrations(conn)
