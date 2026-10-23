"""Q10 — Webhook Integration Hub: delivery queue, retries, circuit breaker.

* Retry with exponential backoff: ``next_attempt_at = now + min(cap, base*2**(n-1))``.
  The clock is injectable (``now=``) so the schedule is tested deterministically.
* Dead-letter after ``max_attempts`` (default 5) exhausted retries.
* Per-endpoint circuit breaker: ``closed → open → half_open → closed``.
  ``CIRCUIT_FAILURE_THRESHOLD`` consecutive failures open the circuit for
  ``CIRCUIT_COOLDOWN_SECONDS``; then one half-open probe is allowed.
* Every delivery attempt is logged (append-only ``webhook_attempts``) —
  success or failure, never silently swallowed.
* Stub endpoints are in-process callables, NEVER real HTTP. A callable
  receives ``(delivery_dict, envelope_dict)`` and raises on failure.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Optional

from .db import utcnow_iso
from .webhooks import event_status, get_event, record_lineage, redacted_summary, utcnow

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_CAP_SECONDS = 3600.0
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 60.0
LOOP_BATCH_LIMIT = 500


def backoff_delay_seconds(attempts_completed: int) -> float:
    """Exponential backoff after the Nth completed attempt: base * 2**(N-1), capped."""
    return min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts_completed - 1)))


def enqueue_delivery(
    conn: sqlite3.Connection,
    event_id: str,
    endpoint: str,
    *,
    rule_id: Optional[int] = None,
    rule_version: Optional[int] = None,
    max_attempts: int = MAX_ATTEMPTS,
    now: Optional[datetime] = None,
    actor: str = "router",
) -> Optional[dict[str, Any]]:
    """Enqueue one forward delivery. Idempotent on (event_id, endpoint).

    Returns the delivery row, or the existing row when this event was
    already queued for the endpoint (duplicate deliveries are impossible
    by construction — the UNIQUE constraint + INSERT OR IGNORE).
    """
    created = (now or utcnow()).isoformat()
    conn.execute(
        """
        INSERT OR IGNORE INTO webhook_deliveries
            (event_id, endpoint, rule_id, rule_version, state,
             attempts, max_attempts, next_attempt_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)
        """,
        (event_id, endpoint, rule_id, rule_version, max_attempts,
         created, created, created),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM webhook_deliveries WHERE event_id = ? AND endpoint = ?",
        (event_id, endpoint),
    ).fetchone()
    return dict(row)


def event_current_state(conn: sqlite3.Connection, event_id: str) -> Optional[str]:
    return event_status(conn, event_id)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
def get_circuit(conn: sqlite3.Connection, endpoint: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM webhook_endpoint_state WHERE endpoint = ?", (endpoint,)
    ).fetchone()
    if row is None:
        return {"endpoint": endpoint, "state": "closed", "consecutive_failures": 0,
                "opened_at": None, "half_open_after": None, "last_failure_at": None}
    return dict(row)


def _circuit_allows(
    conn: sqlite3.Connection, endpoint: str, now: datetime, probes: set[str]
) -> bool:
    """True if the endpoint may be attempted now. Advances open→half_open.

    ``probes`` tracks endpoints already probed in this loop run: a
    half-open circuit admits exactly ONE probe per run, so a retry storm
    cannot slip through the half-open window.
    """
    circuit = get_circuit(conn, endpoint)
    state = circuit["state"]
    if state == "closed":
        return True
    if state == "open":
        half_open_after = circuit["half_open_after"]
        if half_open_after and now.isoformat() >= half_open_after:
            conn.execute(
                """
                UPDATE webhook_endpoint_state
                SET state = 'half_open', updated_at = ? WHERE endpoint = ?
                """,
                (now.isoformat(), endpoint),
            )
            conn.commit()
            state = "half_open"
        else:
            return False
    # half_open: exactly one probe per loop run.
    if endpoint in probes:
        return False
    probes.add(endpoint)
    return True


def _circuit_on_success(conn: sqlite3.Connection, endpoint: str, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO webhook_endpoint_state
            (endpoint, state, consecutive_failures, opened_at, half_open_after,
             last_failure_at, updated_at)
        VALUES (?, 'closed', 0, NULL, NULL, NULL, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            state = 'closed', consecutive_failures = 0,
            opened_at = NULL, half_open_after = NULL, updated_at = excluded.updated_at
        """,
        (endpoint, now.isoformat()),
    )
    conn.commit()


def _circuit_on_failure(conn: sqlite3.Connection, endpoint: str, now: datetime) -> None:
    circuit = get_circuit(conn, endpoint)
    failures = circuit["consecutive_failures"] + 1
    if circuit["state"] == "closed" and failures >= CIRCUIT_FAILURE_THRESHOLD:
        half_open_after = (now + timedelta(seconds=CIRCUIT_COOLDOWN_SECONDS)).isoformat()
        conn.execute(
            """
            INSERT INTO webhook_endpoint_state
                (endpoint, state, consecutive_failures, opened_at, half_open_after,
                 last_failure_at, updated_at)
            VALUES (?, 'open', ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                state = 'open', consecutive_failures = excluded.consecutive_failures,
                opened_at = excluded.opened_at,
                half_open_after = excluded.half_open_after,
                last_failure_at = excluded.last_failure_at,
                updated_at = excluded.updated_at
            """,
            (endpoint, failures, now.isoformat(), half_open_after,
             now.isoformat(), now.isoformat()),
        )
    elif circuit["state"] == "half_open":
        # Probe failed: back to open with a fresh cooldown.
        half_open_after = (now + timedelta(seconds=CIRCUIT_COOLDOWN_SECONDS)).isoformat()
        conn.execute(
            """
            UPDATE webhook_endpoint_state
            SET state = 'open', consecutive_failures = ?,
                opened_at = ?, half_open_after = ?, last_failure_at = ?,
                updated_at = ?
            WHERE endpoint = ?
            """,
            (failures, now.isoformat(), half_open_after, now.isoformat(),
             now.isoformat(), endpoint),
        )
    else:
        conn.execute(
            """
            INSERT INTO webhook_endpoint_state
                (endpoint, state, consecutive_failures, opened_at, half_open_after,
                 last_failure_at, updated_at)
            VALUES (?, 'closed', ?, NULL, NULL, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                consecutive_failures = excluded.consecutive_failures,
                last_failure_at = excluded.last_failure_at,
                updated_at = excluded.updated_at
            """,
            (endpoint, failures, now.isoformat(), now.isoformat()),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Dead-letter store
# ---------------------------------------------------------------------------
def dead_letter(
    conn: sqlite3.Connection,
    event_id: str,
    reason: str,
    *,
    delivery_id: Optional[int] = None,
    actor: str = "hub",
    created: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> int:
    """Dead-letter an event (and optionally one of its deliveries).

    Records the dead-letter row AND the terminal ``dead_lettered`` lineage
    transition. The detail is redacted — never the full payload.
    """
    created = created or utcnow_iso()
    try:
        event = get_event(conn, event_id)
        source, event_type = event["source"], event["event_type"]
    except KeyError:
        source, event_type = "", ""
    from_state = event_status(conn, event_id)
    cur = conn.execute(
        """
        INSERT INTO webhook_dead_letters
            (event_id, delivery_id, source, event_type, reason, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, delivery_id, source, event_type, reason,
         json.dumps(detail or {}, sort_keys=True), created),
    )
    conn.commit()
    if from_state not in ("dead_lettered",):
        record_lineage(
            conn, event_id, "dead_lettered", from_state=from_state,
            actor=actor, created=created,
            detail={"reason": reason, "delivery_id": delivery_id,
                    **(detail or {})},
        )
    return cur.lastrowid


def list_dead_letters(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM webhook_dead_letters ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def replay_dead_letter(
    conn: sqlite3.Connection,
    dead_letter_id: int,
    endpoints: Mapping[str, Callable[..., Any]],
    *,
    actor: str = "hub",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Re-queue a dead letter for another attempt.

    * Delivery-level dead letters (max_attempts_exceeded / unknown_endpoint):
      reset that delivery to queued with attempts=0 and re-run the loop once.
    * Routing-level dead letters (routing_error): re-run routing on the
      stored envelope (rules may have been fixed since).
    * Malformed-envelope dead letters: NOT replayable (no valid envelope
      exists) — raises ValueError.
    """
    row = conn.execute(
        "SELECT * FROM webhook_dead_letters WHERE id = ?", (dead_letter_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown dead letter {dead_letter_id!r}")
    dl = dict(row)
    if dl["reason"] == "malformed_envelope":
        raise ValueError("malformed-envelope dead letters cannot be replayed")
    created = (now or utcnow()).isoformat()
    event_id = dl["event_id"]
    record_lineage(conn, event_id, "replayed",
                   from_state=event_status(conn, event_id),
                   actor=actor, created=created,
                   detail={"dead_letter_id": dead_letter_id, "reason": dl["reason"]})
    if dl["delivery_id"] is not None:
        conn.execute(
            """
            UPDATE webhook_deliveries
            SET state = 'queued', attempts = 0, last_error = NULL,
                next_attempt_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (created, created, dl["delivery_id"]),
        )
        conn.execute(
            "UPDATE webhook_dead_letters SET replayed = 1 WHERE id = ?",
            (dead_letter_id,),
        )
        conn.commit()
        record_lineage(conn, event_id, "queued", from_state="replayed",
                       actor=actor, created=created,
                       detail={"replay_of": dead_letter_id})
        stats = run_delivery_loop(conn, endpoints, now=now, actor=actor)
        return {"replayed": True, "delivery_id": dl["delivery_id"], "loop": stats}
    # Routing-level: re-run routing on the stored envelope.
    from . import router as _router
    event = get_event(conn, event_id)
    envelope = json.loads(event["envelope_json"])
    conn.execute(
        "UPDATE webhook_dead_letters SET replayed = 1 WHERE id = ?", (dead_letter_id,)
    )
    conn.commit()
    plan = _router.apply_routes(conn, envelope, endpoints, actor=actor, now=now)
    return {"replayed": True, "plan": plan}


# ---------------------------------------------------------------------------
# Delivery loop
# ---------------------------------------------------------------------------
def list_deliveries(
    conn: sqlite3.Connection, *, state: Optional[str] = None, limit: int = 200
) -> list[dict[str, Any]]:
    if state:
        rows = conn.execute(
            "SELECT * FROM webhook_deliveries WHERE state = ? ORDER BY next_attempt_at LIMIT ?",
            (state, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM webhook_deliveries ORDER BY next_attempt_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def settle_event(
    conn: sqlite3.Connection, event_id: str, *,
    actor: str = "deliver", now: Optional[datetime] = None,
) -> Optional[str]:
    """Move an event to a terminal lineage state when nothing is pending.

    * any dead-letter rows → ``dead_lettered``
    * all deliveries ``delivered`` (or none exist) → ``delivered``
    * otherwise → nothing pending yet; leave as-is.
    Returns the terminal state recorded, or None when not terminal yet.
    """
    current = event_status(conn, event_id)
    if current in ("delivered", "dead_lettered", "rejected"):
        return current
    created = (now or utcnow()).isoformat()
    # Only non-replayed dead letters block the delivered terminal state:
    # a replayed dead letter means the event got a second chance.
    dl_count = conn.execute(
        "SELECT COUNT(*) AS c FROM webhook_dead_letters"
        " WHERE event_id = ? AND replayed = 0",
        (event_id,),
    ).fetchone()["c"]
    if dl_count:
        record_lineage(conn, event_id, "dead_lettered", from_state=current,
                       actor=actor, created=created,
                       detail={"dead_letters": dl_count})
        return "dead_lettered"
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM webhook_deliveries"
        " WHERE event_id = ? AND state = 'queued'",
        (event_id,),
    ).fetchone()["c"]
    if pending == 0:
        record_lineage(conn, event_id, "delivered", from_state=current,
                       actor=actor, created=created, detail={})
        return "delivered"
    return None


def run_delivery_loop(
    conn: sqlite3.Connection,
    endpoints: Mapping[str, Callable[..., Any]],
    *,
    now: Optional[datetime] = None,
    actor: str = "deliver",
) -> dict[str, int]:
    """Attempt every due delivery once. Never raises for endpoint failures.

    Per-delivery isolation: an exception from one endpoint's callable is
    recorded as a failed attempt; the loop continues with the next
    delivery. Retry storms are bounded by exponential backoff + the
    circuit breaker (open circuits are skipped, counted, and left alone).
    """
    moment = now or utcnow()
    now_iso = moment.isoformat()
    due = conn.execute(
        """
        SELECT * FROM webhook_deliveries
        WHERE state = 'queued' AND next_attempt_at <= ?
        ORDER BY next_attempt_at LIMIT ?
        """,
        (now_iso, LOOP_BATCH_LIMIT),
    ).fetchall()
    stats = {"attempted": 0, "delivered": 0, "failed": 0,
             "dead_lettered": 0, "skipped_circuit_open": 0}
    touched_events: set[str] = set()
    probes: set[str] = set()  # half-open probes already used this run
    for row in due:
        delivery = dict(row)
        endpoint = delivery["endpoint"]
        event_id = delivery["event_id"]
        if not _circuit_allows(conn, endpoint, moment, probes):
            stats["skipped_circuit_open"] += 1
            continue
        stats["attempted"] += 1
        attempt_no = delivery["attempts"] + 1
        try:
            envelope = json.loads(get_event(conn, event_id)["envelope_json"])
        except KeyError:
            # Corrupt queue state (delivery without an event row): record the
            # failure and keep going — the loop must never halt.
            ok, detail = False, f"event_missing: no event row for {event_id!r}"
        else:
            ok, detail = _attempt_once(delivery, envelope, endpoints)
        conn.execute(
            """
            INSERT INTO webhook_attempts
                (delivery_id, attempt_no, endpoint, ok, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (delivery["id"], attempt_no, endpoint, 1 if ok else 0,
             detail[:300], now_iso),
        )
        if ok:
            conn.execute(
                """
                UPDATE webhook_deliveries
                SET state = 'delivered', attempts = ?, last_error = NULL,
                    updated_at = ? WHERE id = ?
                """,
                (attempt_no, now_iso, delivery["id"]),
            )
            _circuit_on_success(conn, endpoint, moment)
            stats["delivered"] += 1
        else:
            permanent = detail.startswith("unknown_endpoint")
            if not permanent:
                # Unknown endpoints are permanent config errors: they neither
                # retry nor count against the circuit breaker.
                _circuit_on_failure(conn, endpoint, moment)
            if permanent or attempt_no >= delivery["max_attempts"]:
                conn.execute(
                    """
                    UPDATE webhook_deliveries
                    SET state = 'dead_lettered', attempts = ?, last_error = ?,
                        updated_at = ? WHERE id = ?
                    """,
                    (attempt_no, detail[:300], now_iso, delivery["id"]),
                )
                dead_letter(
                    conn, event_id,
                    "unknown_endpoint" if permanent else "max_attempts_exceeded",
                    delivery_id=delivery["id"], actor=actor, created=now_iso,
                    detail={"endpoint": endpoint, "attempts": attempt_no,
                            "last_error": detail[:200]},
                )
                stats["dead_lettered"] += 1
            else:
                next_at = (moment + timedelta(
                    seconds=backoff_delay_seconds(attempt_no))).isoformat()
                conn.execute(
                    """
                    UPDATE webhook_deliveries
                    SET attempts = ?, last_error = ?, next_attempt_at = ?,
                        updated_at = ? WHERE id = ?
                    """,
                    (attempt_no, detail[:300], next_at, now_iso, delivery["id"]),
                )
                stats["failed"] += 1
        conn.commit()
        touched_events.add(event_id)
    for event_id in touched_events:
        settle_event(conn, event_id, actor=actor, now=moment)
    return stats


def _attempt_once(
    delivery: dict[str, Any],
    envelope: dict[str, Any],
    endpoints: Mapping[str, Callable[..., Any]],
) -> tuple[bool, str]:
    """Call one stub endpoint. Returns (ok, detail). Never raises."""
    endpoint = delivery["endpoint"]
    fn = endpoints.get(endpoint)
    if fn is None:
        return False, f"unknown_endpoint: no stub registered for {endpoint!r}"
    try:
        result = fn(delivery, envelope)
    except Exception as exc:  # endpoint failures are data, not crashes
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"
    return True, f"ok: {str(result)[:120]}"


def endpoint_states(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM webhook_endpoint_state ORDER BY endpoint"
    ).fetchall()
    return [dict(r) for r in rows]
