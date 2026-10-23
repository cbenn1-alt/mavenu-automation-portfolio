"""Project Q05 — deterministic invoice/payment matching engine.

Two passes, fully explainable:

1. **Exact pass.** A payment with a non-empty ``invoice_ref`` whose
   normalized form equals a normalized invoice ``invoice_id`` matches that
   invoice with score 1.00. Exactness is structural: it can only match on
   ID equality, so exact-pass precision is 100% by construction (tested in
   tests/test_reconciliation.py against deceptive fixtures).

2. **Fuzzy pass.** Unmatched payments are scored against unmatched
   invoices with a documented component breakdown::

       amount  0.60 for an exact cent-for-cent amount match,
               0.40 when |difference| <= amount tolerance, else 0.00
       date    0.20 when |paid_date - due_date| <= window days, else 0.00
       id      0.20 when the payment note/refs normalize to the invoice id,
               0.10 when one normalized id contains the other, else 0.00

   The best candidate auto-matches only when score >= threshold (default
   0.75). A best candidate BELOW the threshold is NEVER silently
   auto-matched: it is routed to a ``review_candidate`` exception with the
   top candidates and their component breakdowns, for a human.

Every decision — exact, fuzzy, review-routed, or left unmatched — is
recorded with its reasons: match rows carry ``explanation_json``, review
exceptions carry candidate breakdowns in ``detail_json``, and the run
summary is appended to ``recon_runs``. Nothing in the matcher uses float
for money; scores are Decimal quantized to two decimals.

Idempotency: ``run_match`` clears auto-generated OPEN exceptions and
rebuilds them from current match state, so re-running a match changes
nothing when nothing changed (tested).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .reconcile import _log, _record_run, _upsert_open_exception, cents_to_decimal

MATCHER_VERSION = "q05-matcher/1"


@dataclass(frozen=True)
class MatchConfig:
    """Tunable matching policy. Thresholds are documented, not magic."""

    amount_tolerance_cents: int = 100  # $1.00 — "close enough" amount band
    date_window_days: int = 14         # |paid_date - due_date| for the date component
    fuzzy_threshold: Decimal = Decimal("0.75")  # >= this auto-matches; below -> review
    review_candidates: int = 3         # top-N candidates listed in review exceptions


def normalize_id(value: str | None) -> str:
    """Normalize an invoice/payment reference for comparison."""
    return re.sub(r"[^A-Za-z0-9]", "", (value or "").upper())


def score_candidate(
    *,
    payment_amount_cents: int,
    payment_date: date,
    payment_note: str,
    invoice_amount_cents: int,
    invoice_due_date: date,
    invoice_id: str,
    config: MatchConfig,
) -> dict[str, Any]:
    """Score one (payment, invoice) pair. Returns component breakdown + total.

    Total is a Decimal quantized to 2 decimals (never float).
    """
    diff = abs(payment_amount_cents - invoice_amount_cents)
    if diff == 0:
        amount_score = Decimal("0.60")
        amount_reason = f"amount matches exactly ({cents_to_decimal(payment_amount_cents)})"
    elif diff <= config.amount_tolerance_cents:
        amount_score = Decimal("0.40")
        amount_reason = (
            f"amount within tolerance: diff {cents_to_decimal(diff)} "
            f"<= {cents_to_decimal(config.amount_tolerance_cents)}"
        )
    else:
        amount_score = Decimal("0.00")
        amount_reason = f"amount differs by {cents_to_decimal(diff)} (outside tolerance)"

    day_gap = abs((payment_date - invoice_due_date).days)
    if day_gap <= config.date_window_days:
        date_score = Decimal("0.20")
        date_reason = (
            f"paid {payment_date.isoformat()} within {config.date_window_days} days "
            f"of due {invoice_due_date.isoformat()} (gap {day_gap}d)"
        )
    else:
        date_score = Decimal("0.00")
        date_reason = (
            f"paid {payment_date.isoformat()} is {day_gap} days from due "
            f"{invoice_due_date.isoformat()} (window {config.date_window_days}d)"
        )

    norm_note = normalize_id(payment_note)
    norm_inv = normalize_id(invoice_id)
    if norm_note and norm_note == norm_inv:
        id_score = Decimal("0.20")
        id_reason = f"payment reference normalizes to invoice id {norm_inv!r}"
    elif norm_note and norm_inv and (norm_note in norm_inv or norm_inv in norm_note):
        id_score = Decimal("0.10")
        id_reason = f"payment reference {norm_note!r} overlaps invoice id {norm_inv!r}"
    else:
        id_score = Decimal("0.00")
        id_reason = "no reference overlap with invoice id"

    total = (amount_score + date_score + id_score).quantize(Decimal("0.01"))
    return {
        "amount_score": str(amount_score),
        "date_score": str(date_score),
        "id_score": str(id_score),
        "total": str(total),
        "reasons": [amount_reason, date_reason, id_reason],
    }


def decide(total: Decimal, config: MatchConfig) -> str:
    """Route a fuzzy candidate total: 'auto' at/above threshold, 'review' below."""
    return "auto" if total >= config.fuzzy_threshold else "review"


# ---------------------------------------------------------------------------
# Match run
# ---------------------------------------------------------------------------

def _invoice_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM recon_invoices ORDER BY id").fetchall()


def _payment_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM recon_payments ORDER BY id").fetchall()


def _existing_payment_matches(conn: sqlite3.Connection) -> set[int]:
    return {
        r["payment_row_id"]
        for r in conn.execute("SELECT payment_row_id FROM recon_matches").fetchall()
    }


def _insert_match(
    conn: sqlite3.Connection,
    invoice_row_id: int,
    payment_row_id: int,
    match_kind: str,
    score: Decimal,
    explanation: list[dict[str, str]],
    matched_by: str,
    moment: datetime,
    actor: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO recon_matches
            (invoice_row_id, payment_row_id, match_kind, score,
             explanation_json, matched_by, matched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_row_id,
            payment_row_id,
            match_kind,
            str(score),
            json.dumps(explanation, sort_keys=True),
            matched_by,
            moment.isoformat(timespec="seconds"),
        ),
    )


def run_match(
    conn: sqlite3.Connection,
    *,
    config: Optional[MatchConfig] = None,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run the two-pass matcher, then rebuild the exception queue.

    Returns a decisions summary with counts and per-decision records.
    Idempotent: re-running with no new data produces zero new matches and
    an identical open-exception queue.
    """
    config = config or MatchConfig()
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    stats: dict[str, Any] = {
        "kind": "match",
        "matcher": MATCHER_VERSION,
        "exact_matches": 0,
        "fuzzy_matches": 0,
        "review_routed": 0,
        "decisions": [],
    }

    invoices = {r["id"]: r for r in _invoice_rows(conn)}
    payments = _payment_rows(conn)
    by_invoice_id = {normalize_id(r["invoice_id"]): r for r in invoices.values()}
    matched_payments = _existing_payment_matches(conn)

    # ---- Pass 1: exact -----------------------------------------------------
    for pay in payments:
        if pay["id"] in matched_payments:
            continue
        norm_ref = normalize_id(pay["invoice_ref"])
        if not norm_ref:
            continue
        inv = by_invoice_id.get(norm_ref)
        if inv is None:
            continue
        _insert_match(
            conn,
            inv["id"],
            pay["id"],
            "exact",
            Decimal("1.00"),
            [{"rule": "exact-invoice-id",
              "detail": f"payment invoice_ref {pay['invoice_ref']!r} "
                        f"normalizes to invoice {inv['invoice_id']!r}"}],
            "exact-pass",
            moment,
            actor,
        )
        stats["exact_matches"] += 1
        matched_payments.add(pay["id"])
        stats["decisions"].append({
            "payment_id": pay["payment_id"],
            "invoice_id": inv["invoice_id"],
            "decision": "matched-exact",
            "score": "1.00",
        })
    conn.commit()

    # ---- Pass 2: fuzzy -----------------------------------------------------
    matched_invoice_ids = {
        r["invoice_row_id"]
        for r in conn.execute("SELECT invoice_row_id FROM recon_matches").fetchall()
    }
    for pay in payments:
        if pay["id"] in matched_payments:
            continue
        paid_date = date.fromisoformat(pay["paid_date"])
        candidates: list[dict[str, Any]] = []
        for inv in invoices.values():
            if inv["id"] in matched_invoice_ids:
                continue
            scored = score_candidate(
                payment_amount_cents=pay["amount_cents"],
                payment_date=paid_date,
                payment_note=f"{pay['invoice_ref'] or ''} {pay['note'] or ''} {pay['customer'] or ''}",
                invoice_amount_cents=inv["amount_cents"],
                invoice_due_date=date.fromisoformat(inv["due_date"]),
                invoice_id=inv["invoice_id"],
                config=config,
            )
            candidates.append({
                "invoice_row_id": inv["id"],
                "invoice_id": inv["invoice_id"],
                "invoice_amount_cents": inv["amount_cents"],
                "score": Decimal(scored["total"]),
                "breakdown": scored,
            })
        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0] if candidates and candidates[0]["score"] > 0 else None
        if best is None:
            stats["decisions"].append({
                "payment_id": pay["payment_id"], "decision": "unmatched",
                "reason": "no candidate with a positive score",
            })
            continue
        if decide(best["score"], config) == "auto":
            _insert_match(
                conn,
                best["invoice_row_id"],
                pay["id"],
                "fuzzy",
                best["score"],
                [{"rule": name, "detail": detail}
                 for name, detail in zip(
                     ("amount", "date", "id"),
                     best["breakdown"]["reasons"],
                 )],
                "fuzzy-pass",
                moment,
                actor,
            )
            stats["fuzzy_matches"] += 1
            matched_payments.add(pay["id"])
            matched_invoice_ids.add(best["invoice_row_id"])
            stats["decisions"].append({
                "payment_id": pay["payment_id"],
                "invoice_id": best["invoice_id"],
                "decision": "matched-fuzzy",
                "score": str(best["score"]),
                "breakdown": best["breakdown"],
            })
        else:
            # Below threshold: NEVER auto-match. Route to human review.
            top = candidates[: config.review_candidates]
            exc_id = _upsert_open_exception(
                conn,
                kind="review_candidate",
                ref_type="payment",
                ref_id=pay["id"],
                ref_public_id=pay["payment_id"],
                detail={
                    "payment_id": pay["payment_id"],
                    "payment_amount_cents": pay["amount_cents"],
                    "paid_date": pay["paid_date"],
                    "best_score": str(best["score"]),
                    "threshold": str(config.fuzzy_threshold),
                    "candidates": [
                        {
                            "invoice_id": c["invoice_id"],
                            "invoice_amount_cents": c["invoice_amount_cents"],
                            "score": str(c["score"]),
                            "breakdown": c["breakdown"],
                        }
                        for c in top
                    ],
                },
                suggested_action=(
                    f"Review {pay['payment_id']} ({cents_to_decimal(pay['amount_cents'])} "
                    f"on {pay['paid_date']}). Best candidate {best['invoice_id']} "
                    f"scored {best['score']} < threshold {config.fuzzy_threshold} — "
                    "the matcher refused to auto-match. Confirm the right invoice "
                    "or mark the payment for refund/re-application."
                ),
                moment=moment,
                actor=actor,
            )
            stats["review_routed"] += 1
            matched_payments.add(pay["id"])  # reviewed, not silently unmatched
            stats["decisions"].append({
                "payment_id": pay["payment_id"],
                "decision": "review-routed",
                "exception_id": exc_id,
                "best_score": str(best["score"]),
                "threshold": str(config.fuzzy_threshold),
            })
    conn.commit()

    # ---- Rebuild the OPEN exception queue from current match state ---------
    rebuild_exceptions(conn, moment=moment, actor=actor)
    exceptions_open = conn.execute(
        "SELECT COUNT(*) AS c FROM recon_exceptions WHERE state = 'open'"
    ).fetchone()["c"]
    stats["exceptions_open"] = exceptions_open

    _record_run(conn, "match", stats, actor, moment)
    _log(actor, "reconciliation.match_run", {
        "exact": stats["exact_matches"], "fuzzy": stats["fuzzy_matches"],
        "review": stats["review_routed"], "exceptions_open": exceptions_open,
    })
    return stats


def rebuild_exceptions(
    conn: sqlite3.Connection,
    *,
    moment: Optional[datetime] = None,
    actor: str = "system",
) -> dict[str, int]:
    """Rebuild auto-generated OPEN exceptions from match state.

    Deletes the current OPEN exceptions and regenerates them from scratch.
    Rows a human has touched (investigating/resolved/written_off) are never
    deleted or duplicated. review_candidate exceptions (fuzzy-pass analysis)
    and duplicate_payment exceptions (ingest artifacts) are preserved —
    they are not pure derivations of match state.
    """
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    conn.execute(
        "DELETE FROM recon_exceptions "
        "WHERE state = 'open' AND kind NOT IN ('review_candidate', 'duplicate_payment')"
    )

    invoices = {r["id"]: r for r in _invoice_rows(conn)}
    payments = {r["id"]: r for r in _payment_rows(conn)}
    matched_payment_ids: set[int] = set()
    invoice_paid: dict[int, int] = {iid: 0 for iid in invoices}
    for r in conn.execute(
        """
        SELECT m.invoice_row_id AS iid, m.payment_row_id AS pid,
               p.amount_cents AS cents
        FROM recon_matches m
        JOIN recon_payments p ON p.id = m.payment_row_id
        """
    ).fetchall():
        matched_payment_ids.add(r["pid"])
        invoice_paid[r["iid"]] = invoice_paid.get(r["iid"], 0) + int(r["cents"])

    counts = {"unmatched_invoice": 0, "unmatched_payment": 0,
              "partial_payment": 0, "overpaid_invoice": 0}

    for iid, inv in invoices.items():
        paid = invoice_paid.get(iid, 0)
        diff = paid - inv["amount_cents"]
        if paid == 0:
            _upsert_open_exception(
                conn, kind="unmatched_invoice", ref_type="invoice", ref_id=iid,
                ref_public_id=inv["invoice_id"],
                detail={"invoice_id": inv["invoice_id"],
                        "customer": inv["customer"],
                        "amount_cents": inv["amount_cents"],
                        "due_date": inv["due_date"], "paid_cents": 0},
                suggested_action=(
                    f"Invoice {inv['invoice_id']} ({cents_to_decimal(inv['amount_cents'])}) "
                    f"from {inv['customer']} has no payment applied. Send a "
                    "statement/reminder or confirm the payment was recorded elsewhere."
                ),
                moment=moment, actor=actor,
            )
            counts["unmatched_invoice"] += 1
        elif diff < 0:
            balance = -diff
            _upsert_open_exception(
                conn, kind="partial_payment", ref_type="invoice", ref_id=iid,
                ref_public_id=inv["invoice_id"],
                detail={"invoice_id": inv["invoice_id"],
                        "customer": inv["customer"],
                        "amount_cents": inv["amount_cents"],
                        "paid_cents": paid, "balance_cents": balance,
                        "due_date": inv["due_date"]},
                suggested_action=(
                    f"Invoice {inv['invoice_id']} is short {cents_to_decimal(balance)} "
                    f"(paid {cents_to_decimal(paid)} of {cents_to_decimal(inv['amount_cents'])}). "
                    "Follow up with the customer for the balance; do not write off "
                    "without human authorization."
                ),
                moment=moment, actor=actor,
            )
            counts["partial_payment"] += 1
        elif diff > 0:
            _upsert_open_exception(
                conn, kind="overpaid_invoice", ref_type="invoice", ref_id=iid,
                ref_public_id=inv["invoice_id"],
                detail={"invoice_id": inv["invoice_id"],
                        "customer": inv["customer"],
                        "amount_cents": inv["amount_cents"],
                        "paid_cents": paid, "overpaid_cents": diff,
                        "due_date": inv["due_date"]},
                suggested_action=(
                    f"Invoice {inv['invoice_id']} is overpaid by {cents_to_decimal(diff)} "
                    f"(paid {cents_to_decimal(paid)} of {cents_to_decimal(inv['amount_cents'])}). "
                    "Verify the extra payment is not an accidental duplicate, then "
                    "refund it or apply it as a credit — a human decides."
                ),
                moment=moment, actor=actor,
            )
            counts["overpaid_invoice"] += 1

    # Payments with no match and no open review_candidate -> unmatched_payment.
    review_open = {
        r["ref_public_id"]
        for r in conn.execute(
            "SELECT ref_public_id FROM recon_exceptions "
            "WHERE state = 'open' AND kind = 'review_candidate'"
        ).fetchall()
    }
    for pid, pay in payments.items():
        if pid in matched_payment_ids or pay["payment_id"] in review_open:
            continue
        _upsert_open_exception(
            conn, kind="unmatched_payment", ref_type="payment", ref_id=pid,
            ref_public_id=pay["payment_id"],
            detail={"payment_id": pay["payment_id"],
                    "customer": pay["customer"],
                    "amount_cents": pay["amount_cents"],
                    "paid_date": pay["paid_date"],
                    "invoice_ref": pay["invoice_ref"], "note": pay["note"]},
            suggested_action=(
                f"Payment {pay['payment_id']} ({cents_to_decimal(pay['amount_cents'])} "
                f"on {pay['paid_date']}) matched nothing. Identify the intended "
                "invoice and apply it, or refund if unidentifiable."
            ),
            moment=moment, actor=actor,
        )
        counts["unmatched_payment"] += 1

    conn.commit()
    _log(actor, "reconciliation.exceptions_rebuilt", counts)
    return counts
