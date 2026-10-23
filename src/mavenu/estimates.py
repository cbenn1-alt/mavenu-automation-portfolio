"""Project Q02 — Estimate Follow-Up Automation: estimate CRUD + lifecycle.

Owns the estimate lifecycle ``draft -> sent -> viewed -> followed_up ->
accepted | declined | expired``: transitions are enforced by ESTIMATE_WORKFLOW
in code, every change writes an ``estimate_events`` audit row (actor, from/to,
timestamps) plus a JSON log line on stdout.

The clock is injectable: every function that touches time accepts an optional
``now``; production callers leave it None (real wall clock), tests pass a
frozen datetime for deterministic cadence/report behavior.

All data is synthetic. Customer names are invented fixtures; the outbox is
not a mail server (see cadence.py).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .validation import SERVICES, ValidationError
from .workflow import ESTIMATE_WORKFLOW, InvalidTransition, OPEN_ESTIMATE_STATES

MAX_NAME_LEN = 120
MAX_NOTES_LEN = 2000
MAX_ESTIMATOR_LEN = 80

# Decline reasons are a closed set so win/loss reporting can group them.
DECLINE_REASONS = (
    "price",
    "timing",
    "chose_competitor",
    "scope",
    "no_response",
    "other",
)

# Timestamp stamped when an estimate first enters each state.
_STATE_STAMPS = {
    "sent": "sent_at",
    "viewed": "viewed_at",
    "accepted": "accepted_at",
    "declined": "declined_at",
    "expired": "expired_at",
}


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp. Naive values are treated as UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now_or(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _age_days(since_iso: str, now: datetime) -> float:
    return max(0.0, (now - _parse_ts(since_iso)).total_seconds() / 86400.0)


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

def _record_estimate_event(
    conn: sqlite3.Connection,
    estimate_id: int,
    public_id: str,
    event_type: str,
    actor: str,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    created: Optional[str] = None,
) -> int:
    # ``created`` is injectable so frozen-clock tests get exact timestamps;
    # production callers leave it None (real wall clock).
    created = created or utcnow_iso()
    detail_json = json.dumps(detail, sort_keys=True) if detail is not None else None
    cur = conn.execute(
        """
        INSERT INTO estimate_events
            (estimate_id, event_type, actor, from_state, to_state, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (estimate_id, event_type, actor, from_state, to_state, detail_json, created),
    )
    event_id = cur.lastrowid
    conn.commit()
    print(
        json.dumps(
            {
                "ts": created,
                "event": event_type,
                "event_id": event_id,
                "estimate_id": estimate_id,
                "public_id": public_id,
                "actor": actor,
                "from_state": from_state,
                "to_state": to_state,
                "detail": detail or {},
            },
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
    return event_id


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def normalize_estimate(raw: Mapping[str, Any]) -> dict:
    """Validate and normalize an estimate payload. Raises ValidationError."""
    errors: dict[str, str] = {}
    if not isinstance(raw, Mapping):
        raise ValidationError({"estimate": "Estimate must be an object."})

    customer_name = str(raw.get("customer_name") or "").strip()
    if not customer_name:
        errors["customer_name"] = "A (synthetic) customer name is required."
    elif len(customer_name) > MAX_NAME_LEN:
        errors["customer_name"] = f"Must be at most {MAX_NAME_LEN} characters."

    service_type = str(raw.get("service_type") or "").strip().lower()
    if service_type not in SERVICES:
        errors["service_type"] = f"Must be one of: {', '.join(SERVICES)}."

    estimator = str(raw.get("estimator") or "").strip()
    if not estimator:
        errors["estimator"] = "An estimator label is required."
    elif len(estimator) > MAX_ESTIMATOR_LEN:
        errors["estimator"] = f"Must be at most {MAX_ESTIMATOR_LEN} characters."

    amount_cents = raw.get("amount_cents")
    try:
        amount_cents = int(amount_cents)
    except (TypeError, ValueError):
        errors["amount_cents"] = "Must be a positive integer number of cents."
        amount_cents = None
    else:
        if amount_cents <= 0:
            errors["amount_cents"] = "Must be greater than zero."

    notes = raw.get("notes", "")
    if notes is None:
        notes = ""
    elif not isinstance(notes, str):
        errors["notes"] = "Must be a string when provided."
    elif len(notes) > MAX_NOTES_LEN:
        errors["notes"] = f"Must be at most {MAX_NOTES_LEN} characters."

    if errors:
        raise ValidationError(errors)

    return {
        "customer_name": customer_name,
        "service_type": service_type,
        "estimator": estimator,
        "amount_cents": amount_cents,
        "notes": notes,
    }


def validate_decline(reason: Any, note: Any) -> dict:
    errors: dict[str, str] = {}
    reason = str(reason or "").strip().lower()
    if reason not in DECLINE_REASONS:
        errors["decline_reason"] = f"Must be one of: {', '.join(DECLINE_REASONS)}."
    note = (note or "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        errors["decline_note"] = "Must be a string when provided."
    elif len(note) > MAX_NOTES_LEN:
        errors["decline_note"] = f"Must be at most {MAX_NOTES_LEN} characters."
    if errors:
        raise ValidationError(errors)
    return {"decline_reason": reason, "decline_note": note}


# ---------------------------------------------------------------------------
# CRUD + lifecycle
# ---------------------------------------------------------------------------

def create_estimate(
    conn: sqlite3.Connection,
    raw: Mapping[str, Any],
    *,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Create an estimate in ``draft``. Raises ValidationError on bad input."""
    cleaned = normalize_estimate(raw)  # raises; nothing stored
    now_iso = _now_or(now).isoformat()
    cur = conn.execute(
        """
        INSERT INTO estimates
            (public_id, customer_name, service_type, estimator, amount_cents,
             state, notes, created_at, updated_at)
        VALUES ('pending', ?, ?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            cleaned["customer_name"], cleaned["service_type"], cleaned["estimator"],
            cleaned["amount_cents"], cleaned["notes"], now_iso, now_iso,
        ),
    )
    estimate_id = cur.lastrowid
    public_id = f"EST-{estimate_id:06d}"
    conn.execute("UPDATE estimates SET public_id = ? WHERE id = ?", (public_id, estimate_id))
    conn.commit()
    _record_estimate_event(
        conn, estimate_id, public_id, "estimate.created", actor,
        to_state="draft",
        detail={"customer_name": cleaned["customer_name"],
                "service_type": cleaned["service_type"],
                "amount_cents": cleaned["amount_cents"]},
        created=now_iso,
    )
    return get_estimate(conn, public_id)


def get_estimate_by_id(conn: sqlite3.Connection, estimate_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM estimates WHERE id = ?", (estimate_id,)).fetchone()
    return dict(row) if row else None


def get_estimate(conn: sqlite3.Connection, public_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM estimates WHERE public_id = ?", (public_id,)
    ).fetchone()
    return dict(row) if row else None


def list_estimates(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM estimates ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def estimate_events(conn: sqlite3.Connection, estimate_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM estimate_events WHERE estimate_id = ? ORDER BY id ASC",
        (estimate_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def transition_estimate(
    conn: sqlite3.Connection,
    public_id: str,
    to_state: str,
    actor: str,
    *,
    decline_reason: Any = None,
    decline_note: Any = None,
    now: Optional[datetime] = None,
) -> dict:
    """Move an estimate through the lifecycle.

    Enforces ESTIMATE_WORKFLOW in code; illegal moves raise InvalidTransition
    and change nothing. Moving to ``declined`` requires a valid
    ``decline_reason``. Each transition stamps the relevant *_at column and
    writes an actor-stamped audit event.
    """
    estimate = get_estimate(conn, public_id)
    if estimate is None:
        raise KeyError(f"No estimate {public_id!r}.")
    ESTIMATE_WORKFLOW.check(estimate["state"], to_state)

    decline: dict[str, str] = {}
    if to_state == "declined":
        decline = validate_decline(decline_reason, decline_note)

    now_iso = _now_or(now).isoformat()
    updates: dict[str, Any] = {"state": to_state, "updated_at": now_iso}
    stamp = _STATE_STAMPS.get(to_state)
    if stamp:
        updates[stamp] = now_iso
    updates.update(decline)
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE estimates SET {sets} WHERE id = ?",
        (*updates.values(), estimate["id"]),
    )
    conn.commit()
    _record_estimate_event(
        conn, estimate["id"], public_id, f"estimate.{to_state}", actor,
        from_state=estimate["state"], to_state=to_state,
        detail={"decline_reason": decline.get("decline_reason")} if decline else None,
        created=now_iso,
    )
    return get_estimate(conn, public_id)


def set_unsubscribed(
    conn: sqlite3.Connection, public_id: str, actor: str,
    *, now: Optional[datetime] = None,
) -> dict:
    """Opt a customer out of follow-ups. A stop rule: unsubscribed estimates
    are excluded from every cadence run, in any state."""
    estimate = get_estimate(conn, public_id)
    if estimate is None:
        raise KeyError(f"No estimate {public_id!r}.")
    now_iso = _now_or(now).isoformat()
    conn.execute(
        "UPDATE estimates SET unsubscribed = 1, updated_at = ? WHERE id = ?",
        (now_iso, estimate["id"]),
    )
    conn.commit()
    _record_estimate_event(
        conn, estimate["id"], public_id, "estimate.unsubscribed", actor,
        detail={"stops_cadence": True}, created=now_iso,
    )
    return get_estimate(conn, public_id)


# ---------------------------------------------------------------------------
# Idempotency wrapper for the create API
# ---------------------------------------------------------------------------

def _get_idempotency(conn: sqlite3.Connection, key: str, ttl_hours: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT response_status, response_body, created_at FROM estimate_idempotency_keys WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    created = _parse_ts(row["created_at"])
    if _now_or(None) - created > timedelta(hours=ttl_hours):
        conn.execute("DELETE FROM estimate_idempotency_keys WHERE key = ?", (key,))
        conn.commit()
        return None
    return {
        "status": row["response_status"],
        "body": json.loads(row["response_body"]),
        "replayed": True,
    }


def _store_idempotency(conn: sqlite3.Connection, key: str, status: int, body: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO estimate_idempotency_keys
            (key, response_status, response_body, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (key, status, json.dumps(body, sort_keys=True), utcnow_iso()),
    )
    conn.commit()


def create_with_idempotency(
    conn: sqlite3.Connection,
    raw: Mapping[str, Any],
    *,
    idempotency_key: Optional[str] = None,
    ttl_hours: int = 72,
    **kwargs: Any,
) -> dict:
    """Idempotent estimate creation: a repeated key replays the original
    response without creating a duplicate estimate."""
    if idempotency_key:
        hit = _get_idempotency(conn, idempotency_key, ttl_hours)
        if hit is not None:
            return hit
    estimate = create_estimate(conn, raw, **kwargs)
    body = {"public_id": estimate["public_id"], "state": estimate["state"]}
    if idempotency_key:
        _store_idempotency(conn, idempotency_key, 201, body)
    return {"status": 201, "body": body, "replayed": False}


# ---------------------------------------------------------------------------
# Render context (shared by the cadence scheduler)
# ---------------------------------------------------------------------------

def format_amount(amount_cents: int) -> str:
    return f"${amount_cents / 100:,.2f}"


def template_context(estimate: Mapping[str, Any]) -> dict:
    """Variable context a rendered follow-up gets for one estimate."""
    return {
        "estimate_id": estimate["public_id"],
        "customer_name": estimate["customer_name"],
        "service_type": estimate["service_type"],
        "amount": format_amount(estimate["amount_cents"]),
        "estimator": estimate["estimator"],
    }
