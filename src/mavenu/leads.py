"""Project 01 — AI Revenue Operations Engine: service layer.

Owns the lead lifecycle: intake, validation, duplicate protection,
rule-based qualification, classifier routing, booking, and manual
reviewer transitions. Every state change is recorded in the audit trail.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from .classifier import Classification, DeterministicDemoClassifier, LeadClassifier
from .db import utcnow_iso
from .events import record_event
from .validation import (
    ValidationError,
    in_service_area,
    validate_lead_payload,
)
from .workflow import LEAD_WORKFLOW


class BookingError(Exception):
    """Raised when the booking integration fails. The lead is never lost."""


class BookingAdapter(Protocol):
    name: str

    def create_booking(self, lead: dict[str, Any]) -> str:
        """Create an appointment for the lead. Returns a booking reference."""
        ...


class FakeBookingAdapter:
    """Deterministic in-process stand-in for an external scheduling system.

    ``fail=True`` simulates an integration outage so the failure path
    (lead preserved, routed to human review, incident recorded) can be
    demonstrated and tested without any real external service.
    """

    name = "fake-booking-v1"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def create_booking(self, lead: dict[str, Any]) -> str:
        if self.fail:
            raise BookingError("simulated booking integration failure")
        return f"BK-{lead['public_id']}-001"


DUPLICATE_WINDOW_HOURS = 24


def _find_possible_duplicate(conn: sqlite3.Connection, cleaned: dict) -> Optional[int]:
    """Find a recent lead with the same contact + service (informational only)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=DUPLICATE_WINDOW_HOURS)).isoformat()
    phone, email, service = cleaned["phone"], cleaned["email"], cleaned["service"]
    row = conn.execute(
        """
        SELECT id FROM leads
        WHERE service = ? AND created_at >= ?
          AND ((phone IS NOT NULL AND phone = ?) OR (email IS NOT NULL AND email = ?))
        ORDER BY id DESC LIMIT 1
        """,
        (service, since, phone, email),
    ).fetchone()
    return row["id"] if row else None


def _get_idempotency(conn: sqlite3.Connection, key: str, ttl_hours: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT lead_id, response_status, response_body, created_at FROM idempotency_keys WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    created = datetime.fromisoformat(row["created_at"])
    if datetime.now(timezone.utc) - created > timedelta(hours=ttl_hours):
        conn.execute("DELETE FROM idempotency_keys WHERE key = ?", (key,))
        conn.commit()
        return None
    return {
        "lead_id": row["lead_id"],
        "status": row["response_status"],
        "body": json.loads(row["response_body"]),
        "replayed": True,
    }


def _store_idempotency(
    conn: sqlite3.Connection, key: str, lead_id: int, status: int, body: dict
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO idempotency_keys (key, lead_id, response_status, response_body, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (key, lead_id, status, json.dumps(body, sort_keys=True), utcnow_iso()),
    )
    conn.commit()


def _insert_lead(conn: sqlite3.Connection, cleaned: dict, duplicate_of: Optional[int]) -> dict:
    now = utcnow_iso()
    cur = conn.execute(
        """
        INSERT INTO leads (public_id, name, phone, email, service, zip, notes, urgency,
                           state, possible_duplicate_of, created_at, updated_at)
        VALUES ('pending', ?, ?, ?, ?, ?, ?, ?, 'received', ?, ?, ?)
        """,
        (
            cleaned["name"], cleaned["phone"], cleaned["email"], cleaned["service"],
            cleaned["zip"], cleaned["notes"], cleaned["urgency"], duplicate_of, now, now,
        ),
    )
    lead_id = cur.lastrowid
    public_id = f"LD-{lead_id:06d}"
    conn.execute("UPDATE leads SET public_id = ? WHERE id = ?", (public_id, lead_id))
    conn.commit()
    return get_lead_by_id(conn, lead_id)


def _set_state(
    conn: sqlite3.Connection,
    lead: dict,
    to_state: str,
    actor: str,
    event_type: str,
    detail: Optional[dict] = None,
) -> dict:
    from_state = lead["state"]
    LEAD_WORKFLOW.check(from_state, to_state)
    now = utcnow_iso()
    conn.execute(
        "UPDATE leads SET state = ?, updated_at = ? WHERE id = ?", (to_state, now, lead["id"])
    )
    conn.commit()
    record_event(
        conn, lead["id"], event_type, actor,
        from_state=from_state, to_state=to_state, detail=detail,
    )
    return get_lead_by_id(conn, lead["id"])


def get_lead_by_id(conn: sqlite3.Connection, lead_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def get_lead(conn: sqlite3.Connection, public_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM leads WHERE public_id = ?", (public_id,)).fetchone()
    return dict(row) if row else None


def list_leads(conn: sqlite3.Connection, state: Optional[str] = None, limit: int = 50) -> list[dict]:
    if state:
        rows = conn.execute(
            "SELECT * FROM leads WHERE state = ? ORDER BY id DESC LIMIT ?", (state, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def lead_events(conn: sqlite3.Connection, lead_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM lead_events WHERE lead_id = ? ORDER BY id ASC", (lead_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection) -> dict:
    """Dashboard aggregates, computed directly from the database."""
    rows = conn.execute("SELECT state, COUNT(*) AS c FROM leads GROUP BY state").fetchall()
    by_state = {r["state"]: r["c"] for r in rows}
    total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
    return {"total": total, "by_state": by_state}


def submit_lead(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    idempotency_key: Optional[str] = None,
    classifier: Optional[LeadClassifier] = None,
    booking_adapter: Optional[BookingAdapter] = None,
    actor: str = "public-form",
    idempotency_ttl_hours: int = 72,
    review_threshold: float = 0.65,
) -> dict:
    """Run the full intake pipeline. Returns a result dict for the response.

    Raises ValidationError when the payload is invalid (no lead is created).
    A repeated idempotency key replays the original response without
    creating a duplicate business record.
    """
    classifier = classifier or DeterministicDemoClassifier(threshold=review_threshold)
    booking_adapter = booking_adapter or FakeBookingAdapter()

    if idempotency_key:
        hit = _get_idempotency(conn, idempotency_key, idempotency_ttl_hours)
        if hit is not None:
            return hit

    cleaned = validate_lead_payload(payload)  # raises ValidationError; nothing stored

    duplicate_of = _find_possible_duplicate(conn, cleaned)
    lead = _insert_lead(conn, cleaned, duplicate_of)
    record_event(conn, lead["id"], "lead.received", actor,
                 to_state="received",
                 detail={"duplicate_of": duplicate_of} if duplicate_of else {})

    features = {
        "service": cleaned["service"],
        "zip": cleaned["zip"],
        "in_service_area": in_service_area(cleaned["zip"]),
        "urgency": cleaned["urgency"],
        "has_phone": bool(cleaned["phone"]),
        "has_email": bool(cleaned["email"]),
        "notes_len": len(cleaned["notes"]),
    }
    classification: Classification = classifier.classify(features)
    conn.execute(
        """UPDATE leads SET classification_label = ?, classification_confidence = ?,
                          classification_model = ?, updated_at = ? WHERE id = ?""",
        (classification.label, classification.confidence, classification.model,
         utcnow_iso(), lead["id"]),
    )
    conn.commit()
    lead = get_lead_by_id(conn, lead["id"])

    result_detail = {
        "model": classification.model,
        "confidence": classification.confidence,
        "reason": classification.reason,
    }

    # Uncertain classifier output -> human review. Never auto-advance a guess.
    if classification.label != "qualified" or classification.confidence < review_threshold:
        lead = _set_state(conn, lead, "needs_review", "system", "lead.needs_review",
                          {**result_detail, "cause": "low_classifier_confidence"})
    elif not features["in_service_area"]:
        lead = _set_state(conn, lead, "needs_review", "system", "lead.needs_review",
                          {**result_detail, "cause": "out_of_service_area"})
    else:
        lead = _set_state(conn, lead, "qualified", "system", "lead.qualified", result_detail)
        lead = _set_state(conn, lead, "routed", "system", "lead.routed",
                          {"route": f"{cleaned['service']}/{cleaned['zip'][:3]}xx"})
        try:
            booking_ref = booking_adapter.create_booking(lead)
        except BookingError as exc:
            # Integration failure: the lead is preserved and queued for a human.
            # Nothing is silently lost; the incident is in the audit trail.
            lead = _set_state(conn, lead, "needs_review", "system", "lead.booking_failed",
                              {"error": str(exc), "adapter": booking_adapter.name})
        else:
            conn.execute("UPDATE leads SET booking_ref = ? WHERE id = ?",
                         (booking_ref, lead["id"]))
            conn.commit()
            lead = _set_state(conn, lead, "booked", "system", "lead.booked",
                              {"booking_ref": booking_ref, "adapter": booking_adapter.name})

    body = {
        "public_id": lead["public_id"],
        "state": lead["state"],
        "booking_ref": lead["booking_ref"],
    }
    if idempotency_key:
        _store_idempotency(conn, idempotency_key, lead["id"], 201, body)
    return {"lead_id": lead["id"], "status": 201, "body": body, "replayed": False}


def transition_lead(
    conn: sqlite3.Connection, public_id: str, to_state: str, actor: str
) -> dict:
    """Reviewer-driven state change. Enforces the workflow; records the audit event."""
    lead = get_lead(conn, public_id)
    if lead is None:
        raise KeyError(f"No lead {public_id!r}.")
    return _set_state(conn, lead, to_state, actor, "lead.state_changed")
