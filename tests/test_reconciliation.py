"""Project Q05 — Invoice Reconciliation & Exception Reporter: service tests.

All data is synthetic. Amounts are invented; names are fictional stand-ins.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.matching import (
    MatchConfig,
    decide,
    normalize_id,
    run_match,
    score_candidate,
)
from mavenu.reconcile import (
    aging_report,
    cents_to_decimal,
    exception_aging,
    exception_history,
    ingest_invoices,
    ingest_payments,
    list_exceptions,
    parse_amount_cents,
    parse_iso_date,
    reconciliation_summary,
    sanitize_cell,
    transition_exception,
)
from mavenu.workflow import EXCEPTION_WORKFLOW, InvalidTransition

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Hand-built fixture — every expectation below is hand-computed.
# ---------------------------------------------------------------------------

INVOICES_CSV = """invoice_id,customer,amount,issued_date,due_date
INV-0001,Acme Test Co,1200.00,2026-09-01,2026-10-01
INV-0002,Brightfield Services,850.00,2026-09-10,2026-10-10
INV-0003,Cedar Works LLC,2500.00,2026-09-15,2026-10-15
INV-0004,Dovetail Partners,400.00,2026-09-20,2026-10-20
INV-0005,Elm Street Co-op,975.50,2026-09-25,2026-10-25
INV-0006,Foxglove Inc,1100.00,2026-08-01,2026-09-01
INV-0007,Granite Supply,600.00,2026-10-01,2026-11-01
INV-0008,Harborlight LLC,300.00,2026-06-01,2026-07-01
"""

PAYMENTS_CSV = """payment_id,invoice_ref,customer,amount,paid_date,note
PAY-0001,INV-0001,Acme Test Co,1200.00,2026-09-28,Check 4410
PAY-0002,INV-0002,Brightfield Services,850.00,2026-10-05,Online transfer
PAY-0003,INV-0003,Cedar Works LLC,1000.00,2026-10-01,First installment
PAY-0004,,Elm Street Co-op,975.50,2026-10-20,Elm Street Co-op INV 0005
PAY-0005,INV-0004,Dovetail Partners,400.00,2026-10-18,Paid in full
PAY-0006,,Unknown Payer,300.00,2026-10-10,random memo
PAY-0007,,Misc Customer,612.34,2026-10-12,Consulting fee
PAY-0008,INV-0001,Acme Test Co,1200.00,2026-10-02,Second check
PAY-0009,INV-9999,Mystery Co,250.00,2026-10-15,No such invoice
PAY-0010,INV-0006,Foxglove Inc,500.00,2026-08-20,Partial wire
PAY-0010,INV-0006,Foxglove Inc,500.00,2026-08-20,Partial wire again
"""

# Hand-computed expectations (see EVIDENCE_MATRIX.md for the arithmetic).
EXPECTED = {
    "invoice_count": 8,
    "payment_count": 10,          # PAY-0010 duplicate row is skipped, not inserted
    "total_invoiced_cents": 792_550,
    "total_paid_cents": 728_784,  # excludes the skipped duplicate row
    "exact_matches": 6,           # PAY-0001,02,03,05,08,10
    "fuzzy_matches": 1,           # PAY-0004 -> INV-0005 (score 0.90)
    "review_routed": 1,           # PAY-0006 (best 0.60 < 0.75)
    "matched_payments_cents": 612_550,
    "unmatched_payments_cents": 116_234,   # PAY-0006 + PAY-0007 + PAY-0009
    "matched_invoices": 6,
    "outstanding_cents": 300_000,  # 1500.00 + 600.00 + 600.00 + 300.00
    "overpaid_cents": 120_000,     # INV-0001 overpaid by 1200.00
    "open_exceptions": 9,          # 2 partial + 1 overpaid + 2 unmatched inv
                                   # + 2 unmatched pay + 1 review + 1 duplicate
}


def load_fixture(conn):
    inv = ingest_invoices(conn, INVOICES_CSV, actor="test", now=NOW)
    pay = ingest_payments(conn, PAYMENTS_CSV, actor="test", now=NOW)
    return inv, pay


# ---------------------------------------------------------------------------
# Ingest: schema validation + row-level errors
# ---------------------------------------------------------------------------

def test_ingest_invoices_happy_path(conn):
    result = ingest_invoices(conn, INVOICES_CSV, actor="test", now=NOW)
    assert result["inserted"] == 8
    assert result["skipped_idempotent"] == 0
    assert result["errors"] == []
    row = conn.execute(
        "SELECT amount_cents FROM recon_invoices WHERE invoice_id = 'INV-0005'"
    ).fetchone()
    assert row["amount_cents"] == 97_550  # Decimal 975.50, never float


def test_ingest_invoices_row_level_errors_do_not_abort_batch(conn):
    csv_text = """invoice_id,customer,amount,issued_date,due_date
INV-0100,Ok Co,100.00,2026-09-01,2026-10-01
INV-0101,Bad Amount Co,not-a-number,2026-09-01,2026-10-01
INV-0102,Bad Date Co,50.00,2026-13-01,2026-10-01
INV-0103,,75.00,2026-09-01,2026-10-01
INV-0104,Time Travel Co,25.00,2026-10-01,2026-09-01
INV-0105,Fine Co,200.00,2026-09-01,2026-10-01
"""
    result = ingest_invoices(conn, csv_text, actor="test", now=NOW)
    assert result["inserted"] == 2  # INV-0100 and INV-0105
    assert len(result["errors"]) == 4
    rows = [e["row"] for e in result["errors"]]
    assert rows == [2, 3, 4, 5]
    fields = [sorted(e.keys() - {"row"}) for e in result["errors"]]
    assert fields[0] == ["amount"]
    assert fields[1] == ["issued_date"]
    assert fields[2] == ["customer"]
    assert fields[3] == ["due_date"]


def test_ingest_missing_columns_is_fatal(conn):
    result = ingest_invoices(conn, "a,b,c\n1,2,3\n", actor="test", now=NOW)
    assert result["inserted"] == 0
    assert len(result["errors"]) == 1
    assert "fatal" in result["errors"][0]
    assert "Missing required columns" in result["errors"][0]["fatal"]


def test_ingest_reingest_is_idempotent(conn):
    first = ingest_invoices(conn, INVOICES_CSV, actor="test", now=NOW)
    second = ingest_invoices(conn, INVOICES_CSV, actor="test", now=NOW)
    assert first["inserted"] == 8
    assert second["inserted"] == 0
    assert second["skipped_idempotent"] == 8
    count = conn.execute("SELECT COUNT(*) AS c FROM recon_invoices").fetchone()["c"]
    assert count == 8


def test_ingest_payments_happy_path(conn):
    result = ingest_payments(conn, PAYMENTS_CSV, actor="test", now=NOW)
    assert result["inserted"] == 10  # duplicate PAY-0010 row skipped, not inserted
    dup = conn.execute(
        "SELECT * FROM recon_exceptions WHERE kind = 'duplicate_payment' "
        "AND state = 'open'"
    ).fetchone()
    assert dup is not None
    assert dup["ref_public_id"] == "PAY-0010"
    detail = __import__("json").loads(dup["detail_json"])
    assert detail["reason"] == "payment_id appeared twice in one ingest batch"


def test_within_batch_duplicate_not_double_counted(conn):
    ingest_invoices(conn, INVOICES_CSV, actor="test", now=NOW)
    ingest_payments(conn, PAYMENTS_CSV, actor="test", now=NOW)
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM recon_payments WHERE payment_id = 'PAY-0010'"
    ).fetchone()["c"]
    assert count == 1
    run_match(conn, actor="test", now=NOW)
    coverage = conn.execute(
        "SELECT COALESCE(SUM(p.amount_cents), 0) AS t "
        "FROM recon_matches m JOIN recon_payments p ON p.id = m.payment_row_id "
        "WHERE m.invoice_row_id = (SELECT id FROM recon_invoices WHERE invoice_id='INV-0006')"
    ).fetchone()["t"]
    assert coverage == 50_000  # single 500.00 payment, not 1000.00


def test_payments_reingest_idempotent(conn):
    first = ingest_payments(conn, PAYMENTS_CSV, actor="test", now=NOW)
    second = ingest_payments(conn, PAYMENTS_CSV, actor="test", now=NOW)
    assert second["inserted"] == 0
    assert second["skipped_idempotent"] == 10  # all seen in an earlier batch
    dups = conn.execute(
        "SELECT COUNT(*) AS c FROM recon_exceptions "
        "WHERE kind = 'duplicate_payment' AND state = 'open'"
    ).fetchone()["c"]
    assert dups == 1  # not one per re-ingest


# ---------------------------------------------------------------------------
# CSV injection sanitization
# ---------------------------------------------------------------------------

def test_sanitize_cell_prefixes_formula_cells():
    for evil in ("=1+1", "=cmd|'/C calc'!A0", "+SUM(A1:A2)", "-2+3", "@malicious"):
        cleaned, was = sanitize_cell(evil)
        assert was is True
        assert cleaned == "'" + evil
        assert cleaned[1] == evil[0]
    ok, was = sanitize_cell("Elm Street Co-op")
    assert was is False and ok == "Elm Street Co-op"
    ok, was = sanitize_cell("  padded  ")
    assert was is False and ok == "padded"


def test_formula_cells_neutralized_in_db(conn):
    csv_text = (
        "invoice_id,customer,amount,issued_date,due_date\n"
        "INV-0900,=cmd|'/C calc'!A0,10.00,2026-09-01,2026-10-01\n"
        "INV-0901,+SUM(B2),20.00,2026-09-01,2026-10-01\n"
        "INV-0902,@evil,30.00,2026-09-01,2026-10-01\n"
    )
    result = ingest_invoices(conn, csv_text, actor="test", now=NOW)
    assert result["inserted"] == 3
    assert result["sanitized"] == 3
    names = [r["customer"] for r in conn.execute("SELECT customer FROM recon_invoices")]
    assert names == ["'=cmd|'/C calc'!A0", "'+SUM(B2)", "'@evil"]
    # No customer cell starts with a formula trigger character.
    assert all(n[0] == "'" for n in names)


def test_formula_amount_rejected_as_row_error(conn):
    csv_text = (
        "invoice_id,customer,amount,issued_date,due_date\n"
        "INV-0903,Sneaky Co,=1+1,2026-09-01,2026-10-01\n"
    )
    result = ingest_invoices(conn, csv_text, actor="test", now=NOW)
    assert result["inserted"] == 0
    assert len(result["errors"]) == 1
    assert "amount" in result["errors"][0]


def test_payment_note_formula_sanitized(conn):
    csv_text = (
        "payment_id,invoice_ref,customer,amount,paid_date,note\n"
        "PAY-0900,,Note Co,5.00,2026-10-01,=HYPERLINK(\"http://evil\")\n"
    )
    ingest_payments(conn, csv_text, actor="test", now=NOW)
    note = conn.execute("SELECT note FROM recon_payments").fetchone()["note"]
    assert note == "'=HYPERLINK(\"http://evil\")"


# ---------------------------------------------------------------------------
# Amount math: Decimal only
# ---------------------------------------------------------------------------

def test_amounts_parse_via_decimal(conn):
    assert parse_amount_cents("0.29") == 29      # float("0.29")*100 = 28.99...
    assert parse_amount_cents("975.50") == 97_550
    assert parse_amount_cents("1200") == 120_000
    assert parse_amount_cents("1,200.50") == 120_050
    assert parse_amount_cents("$1,200.50") == 120_050
    for bad in ("=1+1", "abc", "12.345", "-5.00", "", None):
        with pytest.raises(ValueError):
            parse_amount_cents(bad)


def test_cents_to_decimal_never_float():
    d = cents_to_decimal(97_550)
    assert isinstance(d, Decimal)
    assert d == Decimal("975.50")
    assert not isinstance(d, float)


def test_parse_iso_date():
    d = parse_iso_date("2026-10-23")
    assert d.year == 2026 and d.month == 10 and d.day == 23
    for bad in ("10/23/2026", "2026-13-01", "", None):
        with pytest.raises(ValueError):
            parse_iso_date(bad)


def test_summary_money_values_are_decimal(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    summary = reconciliation_summary(conn)
    for key in ("total_invoiced", "total_paid", "matched_payments",
                "unmatched_payments", "outstanding", "overpaid"):
        assert isinstance(summary[key], Decimal), key
        assert not isinstance(summary[key], float), key


# ---------------------------------------------------------------------------
# Matching: exact pass precision
# ---------------------------------------------------------------------------

def test_normalize_id():
    assert normalize_id("INV-0001") == "INV0001"
    assert normalize_id("inv 0001") == "INV0001"
    assert normalize_id(" inv_0001!") == "INV0001"
    assert normalize_id("") == ""
    assert normalize_id(None) == ""


def test_exact_pass_precision_against_deceptive_fixture(conn):
    invoices = """invoice_id,customer,amount,issued_date,due_date
INV-01,Similar Co,100.00,2026-09-01,2026-10-01
INV-1,Other Co,100.00,2026-09-01,2026-10-01
INV-02,Exact Co,200.00,2026-09-01,2026-10-01
"""
    payments = """payment_id,invoice_ref,customer,amount,paid_date,note
PAY-A,INV-01,Similar Co,100.00,2026-09-15,ref INV-01
PAY-B,INV-9999,Ghost Co,100.00,2026-09-15,nonexistent
PAY-C,  inv-02 ,Exact Co,200.00,2026-09-15,case and spaces
PAY-D,,Other Co,100.00,2026-09-15,no ref at all
"""
    ingest_invoices(conn, invoices, actor="test", now=NOW)
    ingest_payments(conn, payments, actor="test", now=NOW)
    stats = run_match(conn, actor="test", now=NOW)
    assert stats["exact_matches"] == 2  # PAY-A -> INV-01, PAY-C -> INV-02 only
    pairs = {
        (m["invoice_row_id"], m["payment_row_id"]) for m in
        conn.execute("SELECT invoice_row_id, payment_row_id FROM recon_matches").fetchall()
    }
    inv = {r["invoice_id"]: r["id"] for r in conn.execute("SELECT id, invoice_id FROM recon_invoices")}
    pay = {r["payment_id"]: r["id"] for r in conn.execute("SELECT id, payment_id FROM recon_payments")}
    assert (inv["INV-01"], pay["PAY-A"]) in pairs
    assert (inv["INV-02"], pay["PAY-C"]) in pairs
    # INV-1 must NOT have matched PAY-A (its own PAY-D has no ref -> not exact).
    assert (inv["INV-1"], pay["PAY-A"]) not in pairs
    # Every exact match row carries score 1.00 and an explanation.
    for row in conn.execute("SELECT * FROM recon_matches"):
        assert row["match_kind"] == "exact"
        assert Decimal(row["score"]) == Decimal("1.00")
        assert "exact-invoice-id" in row["explanation_json"]


# ---------------------------------------------------------------------------
# Matching: fuzzy scoring + threshold boundary
# ---------------------------------------------------------------------------

def test_score_candidate_components():
    config = MatchConfig()
    from datetime import date
    scored = score_candidate(
        payment_amount_cents=97_550, payment_date=date(2026, 10, 20),
        payment_note="Elm Street Co-op INV 0005",
        invoice_amount_cents=97_550, invoice_due_date=date(2026, 10, 25),
        invoice_id="INV-0005", config=config,
    )
    assert Decimal(scored["total"]) == Decimal("0.90")
    assert scored["amount_score"] == "0.60"
    assert scored["date_score"] == "0.20"
    assert scored["id_score"] == "0.10"  # "INV 0005" contained in the note

    # Amount within tolerance, date outside window, no id overlap -> 0.40.
    scored2 = score_candidate(
        payment_amount_cents=30_050, payment_date=date(2026, 10, 10),
        payment_note="random memo",
        invoice_amount_cents=30_000, invoice_due_date=date(2026, 7, 1),
        invoice_id="INV-0008", config=config,
    )
    assert Decimal(scored2["total"]) == Decimal("0.40")
    # Scores are Decimal-quantized strings, never floats.
    assert isinstance(scored2["total"], str)


def test_decide_boundary():
    config = MatchConfig(fuzzy_threshold=Decimal("0.75"))
    assert decide(Decimal("0.75"), config) == "auto"
    assert decide(Decimal("0.76"), config) == "auto"
    assert decide(Decimal("0.74"), config) == "review"
    assert decide(Decimal("0.00"), config) == "review"


def test_below_threshold_never_silently_automatched(conn):
    # One invoice, one payment whose best score (0.60) is below threshold.
    invoices = """invoice_id,customer,amount,issued_date,due_date
INV-0700,Boundary Co,300.00,2026-06-01,2026-07-01
"""
    payments = """payment_id,invoice_ref,customer,amount,paid_date,note
PAY-0700,,Boundary Payer,300.00,2026-10-10,unrelated memo
"""
    ingest_invoices(conn, invoices, actor="test", now=NOW)
    ingest_payments(conn, payments, actor="test", now=NOW)
    stats = run_match(conn, actor="test", now=NOW)
    assert stats["fuzzy_matches"] == 0
    assert stats["review_routed"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM recon_matches").fetchone()["c"] == 0
    exc = conn.execute(
        "SELECT * FROM recon_exceptions WHERE kind = 'review_candidate' AND state='open'"
    ).fetchone()
    assert exc is not None and exc["ref_public_id"] == "PAY-0700"
    detail = __import__("json").loads(exc["detail_json"])
    assert detail["best_score"] == "0.60"
    assert detail["threshold"] == "0.75"
    assert len(detail["candidates"]) >= 1
    assert "review" in exc["suggested_action"].lower() or "Review" in exc["suggested_action"]


def test_all_below_threshold_candidates_routed_to_review(conn):
    # Five payments, each with a sub-threshold best candidate.
    invoices = """invoice_id,customer,amount,issued_date,due_date
INV-0800,A Co,1000.00,2026-06-01,2026-07-01
INV-0801,B Co,2000.00,2026-06-01,2026-07-01
INV-0802,C Co,3000.00,2026-06-01,2026-07-01
"""
    rows = ["payment_id,invoice_ref,customer,amount,paid_date,note"]
    for i, amt in enumerate(("1000.00", "1000.50", "1000.75", "999.75", "999.25")):
        rows.append(f"PAY-08{i:02d},,Payer{i},{amt},2026-10-10,memo")
    ingest_invoices(conn, invoices, actor="test", now=NOW)
    ingest_payments(conn, "\n".join(rows), actor="test", now=NOW)
    stats = run_match(conn, actor="test", now=NOW)
    # Every payment scores 0.40-0.60 (amount within tolerance; date/id give 0)
    # -> all below the 0.75 threshold -> all routed to review, none auto-matched.
    assert stats["fuzzy_matches"] == 0
    assert stats["review_routed"] == 5
    assert conn.execute("SELECT COUNT(*) AS c FROM recon_matches").fetchone()["c"] == 0
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM recon_exceptions "
        "WHERE kind='review_candidate' AND state='open'"
    ).fetchone()["c"]
    assert n == 5


# ---------------------------------------------------------------------------
# End-to-end fixture: hand-computed expectations
# ---------------------------------------------------------------------------

def test_fixture_match_counts(conn):
    load_fixture(conn)
    stats = run_match(conn, actor="test", now=NOW)
    assert stats["exact_matches"] == EXPECTED["exact_matches"]
    assert stats["fuzzy_matches"] == EXPECTED["fuzzy_matches"]
    assert stats["review_routed"] == EXPECTED["review_routed"]
    assert stats["exceptions_open"] == EXPECTED["open_exceptions"]
    n_matches = conn.execute("SELECT COUNT(*) AS c FROM recon_matches").fetchone()["c"]
    assert n_matches == EXPECTED["exact_matches"] + EXPECTED["fuzzy_matches"]


def test_fixture_known_pairs(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    inv = {r["invoice_id"]: r["id"] for r in conn.execute("SELECT id, invoice_id FROM recon_invoices")}
    pay = {r["payment_id"]: (r["id"],) for r in conn.execute("SELECT id, payment_id FROM recon_payments")}
    pairs = {
        (m["invoice_row_id"], m["payment_row_id"], m["match_kind"])
        for m in conn.execute("SELECT invoice_row_id, payment_row_id, match_kind FROM recon_matches")
    }
    expected_exact = [
        ("PAY-0001", "INV-0001"), ("PAY-0002", "INV-0002"), ("PAY-0003", "INV-0003"),
        ("PAY-0005", "INV-0004"), ("PAY-0008", "INV-0001"), ("PAY-0010", "INV-0006"),
    ]
    for p, i in expected_exact:
        assert (inv[i], pay[p][0], "exact") in pairs, (p, i)
    assert (inv["INV-0005"], pay["PAY-0004"][0], "fuzzy") in pairs
    # Fuzzy row carries a component explanation.
    fuzzy = conn.execute(
        "SELECT * FROM recon_matches WHERE match_kind='fuzzy'"
    ).fetchone()
    assert Decimal(fuzzy["score"]) >= Decimal("0.75")
    assert "amount" in fuzzy["explanation_json"]


def test_fixture_exception_queue_contents(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    excs = {(e["kind"], e["ref_public_id"], e["state"]): e
            for e in list_exceptions(conn)}
    assert len(excs) == EXPECTED["open_exceptions"]
    assert ("partial_payment", "INV-0003", "open") in excs
    assert ("partial_payment", "INV-0006", "open") in excs
    assert ("overpaid_invoice", "INV-0001", "open") in excs
    assert ("unmatched_invoice", "INV-0007", "open") in excs
    assert ("unmatched_invoice", "INV-0008", "open") in excs
    assert ("unmatched_payment", "PAY-0007", "open") in excs
    assert ("unmatched_payment", "PAY-0009", "open") in excs  # $50 > $1 tolerance
    assert ("review_candidate", "PAY-0006", "open") in excs
    assert ("duplicate_payment", "PAY-0010", "open") in excs
    for e in excs.values():
        assert e["suggested_action"], "every exception must propose a next action"


def test_partial_payment_balance_and_action(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    exc = conn.execute(
        "SELECT * FROM recon_exceptions WHERE kind='partial_payment' "
        "AND ref_public_id='INV-0003' AND state='open'"
    ).fetchone()
    detail = __import__("json").loads(exc["detail_json"])
    assert detail["balance_cents"] == 150_000
    assert detail["paid_cents"] == 100_000
    assert "1500.00" in exc["suggested_action"]


def test_overpaid_invoice_exception(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    exc = conn.execute(
        "SELECT * FROM recon_exceptions WHERE kind='overpaid_invoice' AND state='open'"
    ).fetchone()
    detail = __import__("json").loads(exc["detail_json"])
    assert exc["ref_public_id"] == "INV-0001"
    assert detail["overpaid_cents"] == 120_000


# ---------------------------------------------------------------------------
# Reconciliation summary: hand-computed + independent SQL recomputation
# ---------------------------------------------------------------------------

def test_summary_matches_hand_computed_expectations(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    s = reconciliation_summary(conn)
    assert s["invoice_count"] == EXPECTED["invoice_count"]
    assert s["payment_count"] == EXPECTED["payment_count"]
    assert s["total_invoiced_cents"] == EXPECTED["total_invoiced_cents"]
    assert s["total_paid_cents"] == EXPECTED["total_paid_cents"]
    assert s["matched_payments_cents"] == EXPECTED["matched_payments_cents"]
    assert s["unmatched_payments_cents"] == EXPECTED["unmatched_payments_cents"]
    assert s["matched_invoices"] == EXPECTED["matched_invoices"]
    assert s["outstanding_cents"] == EXPECTED["outstanding_cents"]
    assert s["overpaid_cents"] == EXPECTED["overpaid_cents"]
    # Reconciliation identity: outstanding - overpaid == invoiced - matched-paid.
    assert (s["outstanding_cents"] - s["overpaid_cents"]
            == s["total_invoiced_cents"] - s["matched_payments_cents"])


def test_summary_reconciles_to_independent_raw_sql(conn):
    """Independent recomputation straight from source rows, no service code."""
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    s = reconciliation_summary(conn)

    inv_total = conn.execute("SELECT SUM(amount_cents) t FROM recon_invoices").fetchone()["t"]
    pay_total = conn.execute("SELECT SUM(amount_cents) t FROM recon_payments").fetchone()["t"]
    assert s["total_invoiced_cents"] == inv_total
    assert s["total_paid_cents"] == pay_total

    matched_pay = conn.execute(
        "SELECT SUM(amount_cents) t FROM recon_payments WHERE id IN "
        "(SELECT payment_row_id FROM recon_matches)"
    ).fetchone()["t"]
    assert s["matched_payments_cents"] == matched_pay
    assert s["unmatched_payments_cents"] == pay_total - matched_pay

    # Per-invoice outstanding from a raw join (no _invoice_coverage()).
    rows = conn.execute(
        """
        SELECT i.id, i.amount_cents,
               COALESCE((SELECT SUM(p.amount_cents) FROM recon_matches m
                         JOIN recon_payments p ON p.id = m.payment_row_id
                         WHERE m.invoice_row_id = i.id), 0) AS paid
        FROM recon_invoices i
        """
    ).fetchall()
    outstanding = sum(max(0, r["amount_cents"] - r["paid"]) for r in rows)
    overpaid = sum(max(0, r["paid"] - r["amount_cents"]) for r in rows)
    assert s["outstanding_cents"] == outstanding
    assert s["overpaid_cents"] == overpaid


# ---------------------------------------------------------------------------
# Re-ingest produces zero duplicate matches
# ---------------------------------------------------------------------------

def test_reingest_and_rematch_produces_zero_new_matches(conn):
    load_fixture(conn)
    first = run_match(conn, actor="test", now=NOW)
    n_matches = conn.execute("SELECT COUNT(*) c FROM recon_matches").fetchone()["c"]
    n_open = conn.execute(
        "SELECT COUNT(*) c FROM recon_exceptions WHERE state='open'").fetchone()["c"]

    # Re-ingest the exact same CSVs (all idempotent skips).
    inv2 = ingest_invoices(conn, INVOICES_CSV, actor="test", now=NOW)
    pay2 = ingest_payments(conn, PAYMENTS_CSV, actor="test", now=NOW)
    assert inv2["inserted"] == 0 and pay2["inserted"] == 0

    second = run_match(conn, actor="test", now=NOW)
    assert second["exact_matches"] == 0
    assert second["fuzzy_matches"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM recon_matches").fetchone()["c"] == n_matches
    assert conn.execute(
        "SELECT COUNT(*) c FROM recon_exceptions WHERE state='open'").fetchone()["c"] == n_open
    assert first["exceptions_open"] == second["exceptions_open"]


# ---------------------------------------------------------------------------
# Exception state machine
# ---------------------------------------------------------------------------

def _any_open_exception(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    return list_exceptions(conn, state="open")[0]


def test_exception_legal_transitions(conn):
    exc = _any_open_exception(conn)
    moved = transition_exception(conn, exc["id"], "investigating",
                                 actor="ada", detail="looking into it", now=NOW)
    assert moved["state"] == "investigating"
    assert moved["actor"] == "ada"
    moved = transition_exception(conn, exc["id"], "resolved",
                                 actor="ada", detail="fixed", now=NOW)
    assert moved["state"] == "resolved"
    hist = exception_history(conn, exc["id"])
    assert [(h["from_state"], h["to_state"], h["actor"]) for h in hist] == [
        (None, "open", "test"),  # raised by the fixture ingest with actor="test"
        ("open", "investigating", "ada"),
        ("investigating", "resolved", "ada"),
    ]


def test_exception_written_off_path(conn):
    exc = _any_open_exception(conn)
    transition_exception(conn, exc["id"], "investigating", actor="bea", now=NOW)
    moved = transition_exception(conn, exc["id"], "written_off",
                                 actor="bea", detail="authorized write-off", now=NOW)
    assert moved["state"] == "written_off"
    assert moved["actor"] == "bea"


@pytest.mark.parametrize("from_state,to_state", [
    ("open", "resolved"), ("open", "written_off"), ("open", "open"),
    ("investigating", "open"), ("resolved", "investigating"),
    ("resolved", "written_off"), ("written_off", "resolved"),
    ("open", "bogus"),
])
def test_exception_illegal_transitions_rejected(conn, from_state, to_state):
    exc = _any_open_exception(conn)
    if from_state != "open":
        transition_exception(conn, exc["id"], "investigating", actor="x", now=NOW)
        if from_state in ("resolved", "written_off"):
            transition_exception(conn, exc["id"], from_state, actor="x", now=NOW)
    with pytest.raises(InvalidTransition):
        transition_exception(conn, exc["id"], to_state, actor="x", now=NOW)
    # State unchanged after the failed move.
    row = conn.execute(
        "SELECT state FROM recon_exceptions WHERE id = ?", (exc["id"],)
    ).fetchone()
    assert row["state"] == from_state


def test_transition_unknown_exception_raises(conn):
    with pytest.raises(KeyError):
        transition_exception(conn, 999_999, "investigating", actor="x", now=NOW)


def test_workflow_states_documented():
    assert EXCEPTION_WORKFLOW.can("open", "investigating")
    assert EXCEPTION_WORKFLOW.can("investigating", "resolved")
    assert EXCEPTION_WORKFLOW.can("investigating", "written_off")
    assert not EXCEPTION_WORKFLOW.can("open", "resolved")


# ---------------------------------------------------------------------------
# Aging reports
# ---------------------------------------------------------------------------

def test_aging_buckets_match_hand_computed(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    report = aging_report(conn, now=NOW)
    buckets = report["buckets"]
    assert report["as_of"] == "2026-10-23"
    # Hand-computed: outstanding INV-0003 1500 (1-30), INV-0006 600 (31-60),
    # INV-0007 600 (current), INV-0008 300 (90+).
    assert buckets["current"] == {"invoice_count": 1, "outstanding_cents": 60_000,
                                  "outstanding": Decimal("600.00")}
    assert buckets["1-30"]["outstanding_cents"] == 150_000
    assert buckets["1-30"]["invoice_count"] == 1
    assert buckets["31-60"]["outstanding_cents"] == 60_000
    assert buckets["31-60"]["invoice_count"] == 1
    assert buckets["61-90"]["outstanding_cents"] == 0
    assert buckets["90+"]["outstanding_cents"] == 30_000
    assert buckets["90+"]["invoice_count"] == 1
    # Bucket totals sum to the summary outstanding.
    total = sum(b["outstanding_cents"] for b in buckets.values())
    assert total == reconciliation_summary(conn)["outstanding_cents"]


def test_exception_aging_buckets(conn):
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    report = exception_aging(conn, now=NOW)
    assert report["buckets"]["0-7 days"]["exception_count"] == EXPECTED["open_exceptions"]
    assert report["buckets"]["8-30 days"]["exception_count"] == 0
    assert report["buckets"]["31+ days"]["exception_count"] == 0


def test_exception_aging_with_old_exceptions(conn):
    old = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    ingest_invoices(conn, INVOICES_CSV, actor="test", now=old)
    ingest_payments(conn, PAYMENTS_CSV, actor="test", now=old)
    run_match(conn, actor="test", now=old)
    report = exception_aging(conn, now=NOW)  # 83 days later
    assert report["buckets"]["31+ days"]["exception_count"] == EXPECTED["open_exceptions"]


# ---------------------------------------------------------------------------
# Migration rollback — tested for real
# ---------------------------------------------------------------------------

def test_migration_008_down_step_rolls_back_for_real(conn):
    assert "008_reconciliation.sql" in applied_migrations(conn)
    load_fixture(conn)
    run_match(conn, actor="test", now=NOW)
    assert rollback_migration(conn, "008_reconciliation.sql") is True
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'recon_%'"
    ).fetchall()}
    assert tables == set()
    assert "008_reconciliation.sql" not in applied_migrations(conn)
    # P01/P02/Q01 tables untouched.
    assert conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"] >= 0
    # Re-apply works cleanly.
    assert run_migrations(conn) == ["008_reconciliation.sql"]
    assert "008_reconciliation.sql" in applied_migrations(conn)
