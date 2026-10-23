"""Project Q05 — Invoice Reconciliation & Exception Reporter: service layer.

Owns: CSV ingest (invoices + payments) with schema validation, row-level
error reporting, and CSV-formula sanitization; idempotent inserts on the
natural keys (invoice_id / payment_id); the exception queue
(open -> investigating -> resolved | written_off, enforced by
EXCEPTION_WORKFLOW) with actor-stamped transition history; and the
reconciliation reports (summary, aging buckets, exception aging).

The matching engine itself lives in ``matching.py``; this module owns the
data the matcher reads and the exceptions the matcher raises.

Money: amounts arrive as Decimal, are stored as integer cents, and are
rendered back as Decimal. float is NEVER used for amounts anywhere in
this module.

ALL DATA IS SYNTHETIC DEMONSTRATION DATA. See the module README in
projects/project_q05/ for the honest-status banner.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .workflow import EXCEPTION_WORKFLOW, InvalidTransition

# ---------------------------------------------------------------------------
# CSV-injection sanitization
# ---------------------------------------------------------------------------

# Cells starting with these characters are interpreted as formulas by
# spreadsheet apps (CSV injection / "formula injection"). Neutralize them on
# ingest by prefixing a single quote, which renders the cell as literal text.
_FORMULA_LEADS = ("=", "+", "-", "@")


def sanitize_cell(value: Any) -> tuple[str, bool]:
    """Return (sanitized_value, was_sanitized).

    Strips surrounding whitespace; a cell whose first non-space character
    is a formula trigger (= + - @) is prefixed with a single quote so
    spreadsheet apps treat it as literal text. All other values pass
    through unchanged.
    """
    text = "" if value is None else str(value).strip()
    if text and text[0] in _FORMULA_LEADS:
        return "'" + text, True
    return text, False


# ---------------------------------------------------------------------------
# Amount / date parsing (Decimal, never float)
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(r"^-?\d{1,15}(\.\d{1,2})?$")


def parse_amount_cents(raw: Any) -> int:
    """Parse a money amount to integer cents using Decimal. Raises ValueError.

    Accepts forms like "1200", "1,200.50", "$1,200.50", "975.5". Anything
    that is not a plain decimal number (including formula cells such as
    "=1+1") raises ValueError — formulas never reach the ledger.
    """
    if raw is None:
        raise ValueError("amount is required")
    text = str(raw).strip().replace("$", "").replace(",", "")
    if not _AMOUNT_RE.fullmatch(text):
        raise ValueError(f"amount must be a plain decimal number, got {str(raw)!r}")
    amount = Decimal(text)
    if amount < 0:
        raise ValueError("amount must not be negative")
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents


def cents_to_decimal(cents: int) -> Decimal:
    """Integer cents back to Decimal dollars. Never returns a float."""
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(raw: Any) -> date:
    """Parse a YYYY-MM-DD date. Naive = calendar date as given. Raises ValueError."""
    if raw is None or not str(raw).strip():
        raise ValueError("date is required")
    text = str(raw).strip()
    if not _DATE_RE.fullmatch(text):
        raise ValueError(f"date must be YYYY-MM-DD, got {str(raw)!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid date {str(raw)!r}") from exc


# ---------------------------------------------------------------------------
# CSV ingest
# ---------------------------------------------------------------------------

INVOICE_COLUMNS = ("invoice_id", "customer", "amount", "issued_date", "due_date")
PAYMENT_COLUMNS = ("payment_id", "invoice_ref", "customer", "amount", "paid_date", "note")

_ROW_REQUIRED = {
    "invoice_id": "invoice_id",
    "customer": "customer",
    "payment_id": "payment_id",
}


def _now_or(now: Optional[datetime]) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now


def _batch_label(now: datetime) -> str:
    return f"csv:{now.isoformat(timespec='seconds')}"


def _validate_header(fieldnames: list[str] | None, expected: tuple[str, ...]) -> dict | None:
    """Return a fatal error dict when the header is missing/empty, else None."""
    if not fieldnames:
        return {"fatal": "CSV must have a header row."}
    missing = [c for c in expected if c not in fieldnames]
    if missing:
        return {"fatal": f"Missing required columns: {', '.join(missing)}."}
    return None


def ingest_invoices(
    conn: sqlite3.Connection,
    csv_text: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Ingest an invoice CSV. Returns {inserted, skipped_idempotent, sanitized, errors, batch}.

    Row-level validation: a bad row is recorded in ``errors`` (with its
    1-based data-row number) and never aborts the batch. Re-ingesting an
    invoice_id already present is an idempotent skip. Inserted rows are
    recorded in recon_runs.
    """
    moment = _now_or(now)
    batch = _batch_label(moment)
    result: dict[str, Any] = {
        "kind": "ingest_invoices",
        "inserted": 0,
        "skipped_idempotent": 0,
        "sanitized": 0,
        "errors": [],
        "batch": batch,
    }
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    fatal = _validate_header(reader.fieldnames, INVOICE_COLUMNS)
    if fatal:
        result["errors"].append({"row": 0, **fatal})
        _record_run(conn, "ingest_invoices", result, actor, moment)
        return result

    for lineno, raw in enumerate(reader, start=1):
        errors: dict[str, str] = {}
        invoice_id, s1 = sanitize_cell(raw.get("invoice_id"))
        customer, s2 = sanitize_cell(raw.get("customer"))
        amount_raw = (raw.get("amount") or "").strip()
        issued_raw = (raw.get("issued_date") or "").strip()
        due_raw = (raw.get("due_date") or "").strip()
        result["sanitized"] += sum(1 for s in (s1, s2) if s)
        if not invoice_id:
            errors["invoice_id"] = "invoice_id is required."
        if not customer:
            errors["customer"] = "customer is required."
        try:
            amount_cents = parse_amount_cents(amount_raw)
        except ValueError as exc:
            errors["amount"] = str(exc)
            amount_cents = 0
        try:
            issued = parse_iso_date(issued_raw)
        except ValueError as exc:
            errors["issued_date"] = str(exc)
            issued = None
        try:
            due = parse_iso_date(due_raw)
        except ValueError as exc:
            errors["due_date"] = str(exc)
            due = None
        if issued and due and due < issued:
            errors["due_date"] = "due_date must not be before issued_date."
        if errors:
            result["errors"].append({"row": lineno, **errors})
            continue
        existing = conn.execute(
            "SELECT id FROM recon_invoices WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()
        if existing:
            result["skipped_idempotent"] += 1
            continue
        conn.execute(
            """
            INSERT INTO recon_invoices
                (invoice_id, customer, amount_cents, issued_date, due_date,
                 source_row, ingest_batch, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                customer,
                amount_cents,
                issued.isoformat(),
                due.isoformat(),
                lineno,
                batch,
                moment.isoformat(timespec="seconds"),
            ),
        )
        result["inserted"] += 1
    conn.commit()
    _record_run(conn, "ingest_invoices", result, actor, moment)
    _log(actor, "reconciliation.ingest_invoices", {
        "batch": batch, "inserted": result["inserted"],
        "skipped": result["skipped_idempotent"],
        "sanitized": result["sanitized"], "errors": len(result["errors"]),
    })
    return result


def ingest_payments(
    conn: sqlite3.Connection,
    csv_text: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Ingest a payment CSV. Same contract as ingest_invoices.

    Within-batch repeats of a payment_id do NOT insert a second row: the
    repeat is skipped and an open ``duplicate_payment`` exception is raised
    with a suggested next action. A payment_id already present from an
    earlier batch is an idempotent skip (re-ingest produces zero duplicate
    matches).
    """
    moment = _now_or(now)
    batch = _batch_label(moment)
    result: dict[str, Any] = {
        "kind": "ingest_payments",
        "inserted": 0,
        "skipped_idempotent": 0,
        "sanitized": 0,
        "errors": [],
        "batch": batch,
    }
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    fatal = _validate_header(reader.fieldnames, PAYMENT_COLUMNS)
    if fatal:
        result["errors"].append({"row": 0, **fatal})
        _record_run(conn, "ingest_payments", result, actor, moment)
        return result

    seen_in_batch: set[str] = set()
    for lineno, raw in enumerate(reader, start=1):
        errors: dict[str, str] = {}
        payment_id, s1 = sanitize_cell(raw.get("payment_id"))
        invoice_ref, s2 = sanitize_cell(raw.get("invoice_ref"))
        customer, s3 = sanitize_cell(raw.get("customer"))
        note, s4 = sanitize_cell(raw.get("note"))
        amount_raw = (raw.get("amount") or "").strip()
        paid_raw = (raw.get("paid_date") or "").strip()
        result["sanitized"] += sum(1 for s in (s1, s2, s3, s4) if s)
        if not payment_id:
            errors["payment_id"] = "payment_id is required."
        if not customer:
            errors["customer"] = "customer is required."
        try:
            amount_cents = parse_amount_cents(amount_raw)
        except ValueError as exc:
            errors["amount"] = str(exc)
            amount_cents = 0
        try:
            paid = parse_iso_date(paid_raw)
        except ValueError as exc:
            errors["paid_date"] = str(exc)
            paid = None
        if errors:
            result["errors"].append({"row": lineno, **errors})
            continue
        if payment_id in seen_in_batch:
            # Same payment_id twice in one batch: probable double-payment /
            # double-entry. Skip the row, raise a visible exception.
            _raise_duplicate_exception(
                conn, payment_id, lineno, batch, moment, actor=actor
            )
            continue
        seen_in_batch.add(payment_id)
        existing = conn.execute(
            "SELECT id FROM recon_payments WHERE payment_id = ?", (payment_id,)
        ).fetchone()
        if existing:
            result["skipped_idempotent"] += 1
            continue
        conn.execute(
            """
            INSERT INTO recon_payments
                (payment_id, invoice_ref, customer, amount_cents, paid_date,
                 note, source_row, ingest_batch, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payment_id,
                invoice_ref,
                customer,
                amount_cents,
                paid.isoformat(),
                note,
                lineno,
                batch,
                moment.isoformat(timespec="seconds"),
            ),
        )
        result["inserted"] += 1
    conn.commit()
    _record_run(conn, "ingest_payments", result, actor, moment)
    _log(actor, "reconciliation.ingest_payments", {
        "batch": batch, "inserted": result["inserted"],
        "skipped": result["skipped_idempotent"],
        "sanitized": result["sanitized"], "errors": len(result["errors"]),
    })
    return result


def _raise_duplicate_exception(
    conn: sqlite3.Connection,
    payment_id: str,
    lineno: int,
    batch: str,
    moment: datetime,
    *,
    actor: str,
) -> int:
    row = conn.execute(
        "SELECT id, amount_cents FROM recon_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    detail = {
        "payment_id": payment_id,
        "repeat_row": lineno,
        "batch": batch,
        "first_amount_cents": row["amount_cents"] if row else None,
        "reason": "payment_id appeared twice in one ingest batch",
    }
    exc_id = _upsert_open_exception(
        conn,
        kind="duplicate_payment",
        ref_type="payment",
        ref_id=row["id"] if row else 0,
        ref_public_id=payment_id,
        detail=detail,
        suggested_action=(
            f"Verify {payment_id} was not charged twice. The repeat row was "
            "NOT ingested (no double-counting). Confirm with the payer, then "
            "mark investigating and resolve or refund."
        ),
        moment=moment,
        actor=actor,
    )
    conn.commit()
    return exc_id


# ---------------------------------------------------------------------------
# Exception queue
# ---------------------------------------------------------------------------

def _upsert_open_exception(
    conn: sqlite3.Connection,
    *,
    kind: str,
    ref_type: str,
    ref_id: int,
    ref_public_id: str,
    detail: Mapping[str, Any],
    suggested_action: str,
    moment: datetime,
    actor: str = "system",
) -> int:
    """Create an open exception, or return the existing open one (idempotent)."""
    existing = conn.execute(
        """
        SELECT id FROM recon_exceptions
        WHERE kind = ? AND ref_type = ? AND ref_public_id = ? AND state = 'open'
        """,
        (kind, ref_type, ref_public_id),
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO recon_exceptions
            (kind, ref_type, ref_id, ref_public_id, detail_json,
             suggested_action, state, actor, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            kind,
            ref_type,
            ref_id,
            ref_public_id,
            json.dumps(dict(detail), sort_keys=True),
            suggested_action,
            actor,
            moment.isoformat(timespec="seconds"),
            moment.isoformat(timespec="seconds"),
        ),
    )
    exc_id = cur.lastrowid
    _log_exception_event(conn, exc_id, None, "open", actor, "exception raised", moment)
    return exc_id


def _log_exception_event(
    conn: sqlite3.Connection,
    exception_id: int,
    from_state: Optional[str],
    to_state: str,
    actor: str,
    detail: str,
    moment: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO recon_exception_events
            (exception_id, from_state, to_state, actor, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            exception_id,
            from_state,
            to_state,
            actor,
            detail,
            moment.isoformat(timespec="seconds"),
        ),
    )
    _log(actor, "reconciliation.exception_transition", {
        "exception_id": exception_id, "from_state": from_state,
        "to_state": to_state,
    })


def transition_exception(
    conn: sqlite3.Connection,
    exception_id: int,
    to_state: str,
    *,
    actor: str,
    detail: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Move an exception through the state machine. Illegal moves raise
    InvalidTransition. The transition is actor-stamped in the audit trail."""
    moment = _now_or(now)
    row = conn.execute(
        "SELECT * FROM recon_exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No exception with id {exception_id}.")
    EXCEPTION_WORKFLOW.check(row["state"], to_state)
    conn.execute(
        "UPDATE recon_exceptions SET state = ?, actor = ?, updated_at = ? WHERE id = ?",
        (to_state, actor, moment.isoformat(timespec="seconds"), exception_id),
    )
    _log_exception_event(conn, exception_id, row["state"], to_state, actor, detail, moment)
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM recon_exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    return _exception_dict(updated)


def _exception_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "ref_type": row["ref_type"],
        "ref_id": row["ref_id"],
        "ref_public_id": row["ref_public_id"],
        "detail": json.loads(row["detail_json"]),
        "suggested_action": row["suggested_action"],
        "state": row["state"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_exceptions(
    conn: sqlite3.Connection,
    *,
    state: Optional[str] = None,
    kind: Optional[str] = None,
) -> list[dict]:
    sql = "SELECT * FROM recon_exceptions"
    clauses, params = [], []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at, id"
    return [_exception_dict(r) for r in conn.execute(sql, params).fetchall()]


def exception_history(conn: sqlite3.Connection, exception_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM recon_exception_events
        WHERE exception_id = ? ORDER BY id
        """,
        (exception_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "from_state": r["from_state"],
            "to_state": r["to_state"],
            "actor": r["actor"],
            "detail": r["detail"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Reports: reconciliation summary, aging buckets, exception aging
# ---------------------------------------------------------------------------

def _invoice_coverage(conn: sqlite3.Connection) -> dict[int, dict]:
    """Per-invoice {amount_cents, paid_cents, invoice_id, due_date}."""
    coverage: dict[int, dict] = {}
    for r in conn.execute("SELECT * FROM recon_invoices").fetchall():
        coverage[r["id"]] = {
            "invoice_id": r["invoice_id"],
            "amount_cents": r["amount_cents"],
            "due_date": r["due_date"],
            "paid_cents": 0,
        }
    for r in conn.execute(
        """
        SELECT m.invoice_row_id AS iid, SUM(p.amount_cents) AS paid
        FROM recon_matches m
        JOIN recon_payments p ON p.id = m.payment_row_id
        GROUP BY m.invoice_row_id
        """
    ).fetchall():
        if r["iid"] in coverage:
            coverage[r["iid"]]["paid_cents"] = int(r["paid"])
    return coverage


def reconciliation_summary(conn: sqlite3.Connection) -> dict:
    """Every total is computed from source rows (invoices/payments/matches).

    Money values are Decimal; counts are ints. The caller can verify the
    reconciliation identity against independent SQL (see TEST_PLAN.md):
        outstanding_cents - overpaid_cents
            == total_invoiced_cents - matched_payments_cents
    """
    total_invoiced = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM recon_invoices"
    ).fetchone()["t"]
    total_paid = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM recon_payments"
    ).fetchone()["t"]
    invoice_count = conn.execute("SELECT COUNT(*) AS c FROM recon_invoices").fetchone()["c"]
    payment_count = conn.execute("SELECT COUNT(*) AS c FROM recon_payments").fetchone()["c"]
    matched_payments = conn.execute(
        "SELECT COALESCE(SUM(p.amount_cents), 0) AS t "
        "FROM recon_payments p WHERE EXISTS "
        "(SELECT 1 FROM recon_matches m WHERE m.payment_row_id = p.id)"
    ).fetchone()["t"]
    unmatched_payments = int(total_paid) - int(matched_payments)
    matched_invoices = conn.execute(
        "SELECT COUNT(DISTINCT invoice_row_id) AS c FROM recon_matches"
    ).fetchone()["c"]

    outstanding = 0
    overpaid = 0
    for cov in _invoice_coverage(conn).values():
        diff = cov["paid_cents"] - cov["amount_cents"]
        if diff < 0:
            outstanding += -diff
        elif diff > 0:
            overpaid += diff

    exception_counts: dict[str, int] = {}
    for r in conn.execute(
        "SELECT state, COUNT(*) AS c FROM recon_exceptions GROUP BY state"
    ).fetchall():
        exception_counts[r["state"]] = r["c"]

    return {
        "total_invoiced_cents": int(total_invoiced),
        "total_invoiced": cents_to_decimal(int(total_invoiced)),
        "total_paid_cents": int(total_paid),
        "total_paid": cents_to_decimal(int(total_paid)),
        "invoice_count": invoice_count,
        "payment_count": payment_count,
        "matched_invoices": matched_invoices,
        "matched_payments_cents": int(matched_payments),
        "matched_payments": cents_to_decimal(int(matched_payments)),
        "unmatched_payments_cents": unmatched_payments,
        "unmatched_payments": cents_to_decimal(unmatched_payments),
        "outstanding_cents": outstanding,
        "outstanding": cents_to_decimal(outstanding),
        "overpaid_cents": overpaid,
        "overpaid": cents_to_decimal(overpaid),
        "exceptions_by_state": exception_counts,
    }


# Aging buckets, by days overdue vs. the injectable clock.
AGING_BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def _aging_bucket(due: date, today: date) -> str:
    overdue = (today - due).days
    if overdue <= 0:
        return "current"
    if overdue <= 30:
        return "1-30"
    if overdue <= 60:
        return "31-60"
    if overdue <= 90:
        return "61-90"
    return "90+"


def aging_report(conn: sqlite3.Connection, *, now: Optional[datetime] = None) -> dict:
    """Outstanding balance per aging bucket. Every bucket total is a sum
    over source invoice rows; the bucket totals sum to summary.outstanding."""
    today = _now_or(now).date()
    buckets: dict[str, dict] = {
        b: {"invoice_count": 0, "outstanding_cents": 0} for b in AGING_BUCKETS
    }
    for cov in _invoice_coverage(conn).values():
        outstanding = cov["amount_cents"] - cov["paid_cents"]
        if outstanding <= 0:
            continue
        bucket = _aging_bucket(date.fromisoformat(cov["due_date"]), today)
        buckets[bucket]["invoice_count"] += 1
        buckets[bucket]["outstanding_cents"] += outstanding
    for b in buckets:
        buckets[b]["outstanding"] = cents_to_decimal(buckets[b]["outstanding_cents"])
    return {"as_of": today.isoformat(), "buckets": buckets}


EXCEPTION_AGING_BUCKETS = ("0-7 days", "8-30 days", "31+ days")


def exception_aging(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None
) -> dict:
    """Open (and investigating) exceptions by age since creation."""
    today = _now_or(now).date()
    buckets: dict[str, dict] = {
        b: {"exception_count": 0, "kinds": {}} for b in EXCEPTION_AGING_BUCKETS
    }
    for r in conn.execute(
        "SELECT kind, created_at FROM recon_exceptions "
        "WHERE state IN ('open', 'investigating')"
    ).fetchall():
        created = datetime.fromisoformat(r["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (today - created.date()).days
        bucket = (
            "0-7 days" if age_days <= 7 else ("8-30 days" if age_days <= 30 else "31+ days")
        )
        buckets[bucket]["exception_count"] += 1
        kinds = buckets[bucket]["kinds"]
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"as_of": today.isoformat(), "buckets": buckets}


# ---------------------------------------------------------------------------
# Run log + structured stdout logging
# ---------------------------------------------------------------------------

def _record_run(
    conn: sqlite3.Connection,
    kind: str,
    stats: Mapping[str, Any],
    actor: str,
    moment: datetime,
) -> None:
    serializable = {
        k: (str(v) if isinstance(v, Decimal) else v) for k, v in stats.items()
    }
    conn.execute(
        "INSERT INTO recon_runs (kind, stats_json, actor, created_at) "
        "VALUES (?, ?, ?, ?)",
        (kind, json.dumps(serializable, sort_keys=True), actor,
         moment.isoformat(timespec="seconds")),
    )
    conn.commit()


def _log(actor: str, event: str, detail: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            {"ts": utcnow_iso(), "event": event, "actor": actor, "detail": dict(detail)},
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
