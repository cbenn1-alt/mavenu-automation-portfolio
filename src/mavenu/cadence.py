"""Project Q02 — follow-up cadence scheduler.

This is the honest core of the "automation": given the current time (an
injectable clock) and a set of configurable cadence rules (step N is due
``days_after_sent`` days after the estimate went out), the scheduler
computes which follow-ups are due, renders each one through the versioned
template engine, and writes exactly one row per (estimate, step) into the
outbox queue.

v1 sends NOTHING. A follow-up reaches the customer only through a
``MessageAdapter``; the bundled adapter is a stub that writes a send-log
row. The adapter protocol is the seam where a real provider (SMTP,
Twilio, etc.) would plug in later — and where CAN-SPAM/TCPA review would
be required before any real message goes out (see SECURITY.md).

Failure analysis implemented here:
- Double-sending: outbox rows carry an idempotency key
  ``est:<estimate_id>:step:<step_index>`` with a UNIQUE constraint, so a
  scheduler replay can never queue the same step twice. The transition of
  the estimate to ``followed_up`` only happens for steps that were
  actually queued.
- Clock changes: all timestamps are stored and compared in UTC; local-time
  rendering is a presentation concern only. Computation never depends on
  the server's local timezone.
- Template with wrong variables: render-time validation raises
  TemplateRenderError; the scheduler records a ``followup.skipped`` event
  and moves on (fail closed) instead of queueing a broken message.
- Stop rules: accepted / declined / expired / unsubscribed estimates are
  never queued, whatever the rules say.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Protocol

from . import templates as template_service
from .estimates import _age_days, _parse_ts, _record_estimate_event, get_estimate_by_id, template_context
from .validation import ValidationError
from .workflow import ESTIMATE_WORKFLOW, InvalidTransition, OPEN_ESTIMATE_STATES

EXPIRY_DAYS_DEFAULT = 30


def _now_or(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Cadence rules (configurable schedule)
# ---------------------------------------------------------------------------

def list_rules(conn: sqlite3.Connection, *, active_only: bool = True) -> list[dict]:
    where = "WHERE is_active = 1" if active_only else ""
    rows = conn.execute(
        f"SELECT * FROM cadence_rules {where} ORDER BY step_index ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def replace_rules(
    conn: sqlite3.Connection,
    rules: list[Mapping[str, Any]],
    *,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> list[dict]:
    """Replace the whole active rule set with ``rules``.

    Each rule: ``{"step_index": int >= 1, "days_after_sent": float >= 0,
    "template_name": str}``. Step indexes must be unique and start at 1
    with no gaps. Old rules are deactivated (history preserved), and the
    new set becomes active atomically.
    """
    if not isinstance(rules, list) or not rules:
        raise ValidationError({"rules": "Provide a non-empty list of rules."})
    errors: dict[str, str] = {}
    seen: set[int] = set()
    cleaned: list[dict] = []
    for i, raw in enumerate(rules):
        if not isinstance(raw, Mapping):
            errors[f"rules[{i}]"] = "Each rule must be an object."
            continue
        try:
            step_index = int(raw.get("step_index"))
        except (TypeError, ValueError):
            errors[f"rules[{i}].step_index"] = "Must be an integer >= 1."
            step_index = None
        else:
            if step_index < 1:
                errors[f"rules[{i}].step_index"] = "Must be an integer >= 1."
        try:
            days = float(raw.get("days_after_sent"))
        except (TypeError, ValueError):
            errors[f"rules[{i}].days_after_sent"] = "Must be a number >= 0."
            days = None
        else:
            if days < 0:
                errors[f"rules[{i}].days_after_sent"] = "Must be a number >= 0."
        template_name = str(raw.get("template_name") or "").strip()
        if not template_name:
            errors[f"rules[{i}].template_name"] = "A template name is required."
        elif template_service.get_template(conn, template_name) is None:
            errors[f"rules[{i}].template_name"] = (
                f"No active template named {template_name!r}."
            )
        if step_index is not None:
            if step_index in seen:
                errors[f"rules[{i}].step_index"] = "Step indexes must be unique."
            seen.add(step_index)
        if step_index is not None and days is not None and template_name and not errors:
            cleaned.append(
                {"step_index": step_index, "days_after_sent": days,
                 "template_name": template_name}
            )
    if sorted(seen) != list(range(1, len(seen) + 1)):
        errors["rules"] = "Step indexes must start at 1 with no gaps."
    if errors:
        raise ValidationError(errors)

    now_iso = _now_or(now).isoformat()
    conn.execute("UPDATE cadence_rules SET is_active = 0 WHERE is_active = 1")
    for rule in cleaned:
        conn.execute(
            """
            INSERT INTO cadence_rules
                (step_index, days_after_sent, template_name, is_active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (rule["step_index"], rule["days_after_sent"], rule["template_name"], now_iso),
        )
    conn.commit()
    print(
        json.dumps(
            {
                "ts": now_iso,
                "event": "cadence.rules_replaced",
                "actor": actor,
                "rules": cleaned,
            },
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
    return list_rules(conn)


# ---------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------

def _outbox_key(estimate_id: int, step_index: int) -> str:
    return f"est:{estimate_id}:step:{step_index}"


def _step_already_queued(conn: sqlite3.Connection, estimate_id: int, step_index: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM estimate_outbox WHERE idempotency_key = ?",
        (_outbox_key(estimate_id, step_index),),
    ).fetchone()
    return row is not None


def _open_estimates(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ",".join("?" for _ in OPEN_ESTIMATE_STATES)
    rows = conn.execute(
        f"""
        SELECT * FROM estimates
        WHERE state IN ({placeholders})
          AND unsubscribed = 0
          AND sent_at IS NOT NULL
        ORDER BY id ASC
        """,
        tuple(sorted(OPEN_ESTIMATE_STATES)),
    ).fetchall()
    return [dict(r) for r in rows]


def run_cadence(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None, actor: str = "system"
) -> dict:
    """Compute due follow-ups and queue them in the outbox.

    For every open (sent/viewed/followed_up), non-unsubscribed estimate,
    every active rule step whose ``days_after_sent`` has elapsed and that
    has not been queued before gets one rendered outbox row. The estimate
    moves to ``followed_up`` on the first queued step. Scheduler replays
    are idempotent: the UNIQUE idempotency key means a second run queues
    nothing new.

    Returns ``{"queued": [...], "skipped": [...]}`` where each entry names
    the estimate, step, and (for skips) the reason.
    """
    now = _now_or(now)
    now_iso = now.isoformat()
    rules = list_rules(conn)
    queued: list[dict] = []
    skipped: list[dict] = []

    for estimate in _open_estimates(conn):
        age_days = _age_days(estimate["sent_at"], now)
        for rule in rules:
            if age_days < rule["days_after_sent"]:
                continue  # not due yet
            if _step_already_queued(conn, estimate["id"], rule["step_index"]):
                continue  # replay-safe: already queued for this step
            try:
                rendered = template_service.render_template(
                    conn, rule["template_name"], template_context(estimate)
                )
            except template_service.TemplateRenderError as exc:
                # Fail closed: record the skip, never queue a broken message.
                skipped.append(
                    {"public_id": estimate["public_id"],
                     "step_index": rule["step_index"],
                     "reason": str(exc)}
                )
                _record_estimate_event(
                    conn, estimate["id"], estimate["public_id"],
                    "estimate.followup_skipped", actor,
                    detail={"step_index": rule["step_index"],
                            "template_name": rule["template_name"],
                            "reason": str(exc)},
                    created=now_iso,
                )
                continue
            key = _outbox_key(estimate["id"], rule["step_index"])
            cur = conn.execute(
                """
                INSERT INTO estimate_outbox
                    (idempotency_key, estimate_id, template_name, template_version,
                     step_index, scheduled_for, status, recipient_label,
                     subject, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    key, estimate["id"], rendered["name"], rendered["version"],
                    rule["step_index"], now_iso,
                    f"synthetic-customer:{estimate['public_id']}",
                    rendered["subject"], rendered["body"], now_iso,
                ),
            )
            if cur.rowcount == 0:
                # Lost a race with a concurrent scheduler (single-process
                # demo: effectively unreachable, but the guard is real).
                continue
            if estimate["state"] != "followed_up":
                conn.execute(
                    """
                    UPDATE estimates
                    SET state = 'followed_up', followup_count = followup_count + 1,
                        last_followup_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, estimate["id"]),
                )
                _record_estimate_event(
                    conn, estimate["id"], estimate["public_id"],
                    "estimate.followup_queued", actor,
                    from_state=estimate["state"], to_state="followed_up",
                    detail={"step_index": rule["step_index"],
                            "template_name": rule["template_name"],
                            "template_version": rendered["version"],
                            "outbox_id": cur.lastrowid,
                            "idempotency_key": key},
                    created=now_iso,
                )
            else:
                conn.execute(
                    """
                    UPDATE estimates
                    SET followup_count = followup_count + 1,
                        last_followup_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, estimate["id"]),
                )
                _record_estimate_event(
                    conn, estimate["id"], estimate["public_id"],
                    "estimate.followup_queued", actor,
                    from_state="followed_up", to_state="followed_up",
                    detail={"step_index": rule["step_index"],
                            "template_name": rule["template_name"],
                            "template_version": rendered["version"],
                            "outbox_id": cur.lastrowid,
                            "idempotency_key": key},
                    created=now_iso,
                )
            conn.commit()
            estimate = get_estimate_by_id(conn, estimate["id"])
            queued.append(
                {"public_id": estimate["public_id"],
                 "step_index": rule["step_index"],
                 "outbox_id": cur.lastrowid}
            )
    return {"queued": queued, "skipped": skipped}


# ---------------------------------------------------------------------------
# Expiry sweep: estimates that aged out without a decision
# ---------------------------------------------------------------------------

def sweep_expired(
    conn: sqlite3.Connection, *,
    now: Optional[datetime] = None,
    expiry_days: float = EXPIRY_DAYS_DEFAULT,
    actor: str = "system",
) -> list[dict]:
    """Move open estimates older than ``expiry_days`` (since sent) to expired.

    Idempotent: already-expired estimates are untouched, and every move is
    an actor-stamped audit event.
    """
    now = _now_or(now)
    now_iso = now.isoformat()
    expired = []
    for estimate in _open_estimates(conn):
        if _age_days(estimate["sent_at"], now) < expiry_days:
            continue
        try:
            ESTIMATE_WORKFLOW.check(estimate["state"], "expired")
        except InvalidTransition:
            continue
        conn.execute(
            "UPDATE estimates SET state = 'expired', expired_at = ?, updated_at = ? WHERE id = ?",
            (now_iso, now_iso, estimate["id"]),
        )
        conn.commit()
        _record_estimate_event(
            conn, estimate["id"], estimate["public_id"], "estimate.expired", actor,
            from_state=estimate["state"], to_state="expired",
            detail={"reason": "expiry_sweep", "expiry_days": expiry_days},
            created=now_iso,
        )
        expired.append(get_estimate_by_id(conn, estimate["id"]))
    return expired


# ---------------------------------------------------------------------------
# Outbox flushing through the message adapter (stub in v1)
# ---------------------------------------------------------------------------

class MessageAdapter(Protocol):
    """Seam for a real send provider. v1 ships only the stub."""

    name: str

    def send(self, recipient_label: str, subject: str, body: str) -> dict:
        """Attempt delivery. Returns a dict with at least a 'status' key."""
        ...


class StubMessageAdapter:
    """v1 adapter: records a send-log row, delivers nothing anywhere.

    There is deliberately no code path here that touches a network: the
    stub's entire job is to prove the outbox -> adapter -> send-log path
    is exercised while sending nothing.
    """

    name = "stub"

    def send(self, recipient_label: str, subject: str, body: str) -> dict:
        return {
            "status": "stub-logged",
            "recipient_label": recipient_label,
            "note": "STUB — no message was sent anywhere.",
        }


def outbox(conn: sqlite3.Connection, *, status: Optional[str] = None,
           limit: int = 100) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM estimate_outbox WHERE status = ? ORDER BY id ASC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM estimate_outbox ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def send_log(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM send_log ORDER BY id ASC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def flush_outbox(
    conn: sqlite3.Connection,
    adapter: Optional[MessageAdapter] = None,
    *,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Hand every queued outbox row to the adapter and log the outcome.

    One send-log row per outbox row (UNIQUE on outbox_id), so a flushed row
    is never flushed twice. With the stub adapter this is a pure
    bookkeeping pass: it proves the pipeline shape without sending.
    """
    adapter = adapter or StubMessageAdapter()
    now_iso = _now_or(now).isoformat()
    flushed = []
    for row in outbox(conn, status="queued"):
        result = adapter.send(row["recipient_label"], row["subject"], row["body"])
        status = str(result.get("status", "unknown"))
        conn.execute(
            "UPDATE estimate_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
            (now_iso, row["id"]),
        )
        conn.execute(
            """
            INSERT INTO send_log (outbox_id, adapter, status, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(outbox_id) DO NOTHING
            """,
            (row["id"], adapter.name, status,
             json.dumps(result, sort_keys=True, default=str), now_iso),
        )
        conn.commit()
        flushed.append({"outbox_id": row["id"], "adapter": adapter.name,
                        "status": status})
    return flushed
