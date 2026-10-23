"""Project Q01 — Missed-Call Recovery Engine: service layer.

Owns the missed-call lifecycle: ingest (CSV + JSON webhook shape),
deterministic urgency scoring, caller-ID masking/hashing, repeat-caller
anomaly flags, claim/assign, outcome tracking, SLA escalation stubs,
ingestion-lag alerting, and DB-computed dashboard statistics.

Every state change goes through CALL_WORKFLOW and writes a row to
``call_events`` (queryable audit trail) plus a JSON log line on stdout.

Privacy: raw caller IDs are NEVER stored. Only the masked display form
(last 4 digits visible) and a SHA-256 hash (for dedup and repeat-caller
detection) reach the database. All fixture data is synthetic.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .urgency import DeterministicDemoScorer, UrgencyScorer
from .validation import ValidationError
from .workflow import CALL_WORKFLOW, InvalidTransition

TRANSCRIPT_MAX_CHARS = 2000
REPEAT_WINDOW_HOURS = 24
REPEAT_ANOMALY_THRESHOLD = 3  # 3rd missed call from one ID in the window -> flag
RING_COUNT_MAX = 60
DURATION_MAX_SECONDS = 7200

_AGE_DECAY_HALF_LIFE_HOURS = 24.0  # priority halves every 24h of age


# ---------------------------------------------------------------------------
# Caller-ID privacy helpers
# ---------------------------------------------------------------------------

def digits_only(caller_id: str) -> str:
    return re.sub(r"\D", "", caller_id or "")


def mask_caller_id(caller_id: str) -> str:
    """Mask all but the last 4 digits. Never returns the full number."""
    digits = digits_only(caller_id)
    if len(digits) <= 4:
        return "\u2022" * len(digits)
    return "\u2022" * (len(digits) - 4) + digits[-4:]


def hash_caller_id(caller_id: str) -> str:
    """SHA-256 of the normalized digits. Used for dedup + repeat detection."""
    return hashlib.sha256(digits_only(caller_id).encode("utf-8")).hexdigest()


def dedup_key_for(caller_hash: str, missed_at: str) -> str:
    return f"{caller_hash}:{missed_at}"


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


# ---------------------------------------------------------------------------
# Validation / normalization
# ---------------------------------------------------------------------------

def normalize_event(raw: Mapping[str, Any]) -> dict:
    """Validate and normalize one missed-call event. Raises ValidationError.

    Required: ``timestamp`` (ISO-8601), ``caller_id`` (>= 7 digits after
    normalization). Optional: ``ring_count`` (0..60), ``duration_seconds``
    (0..7200), ``transcript`` (string, capped at 2000 chars).
    """
    errors: dict[str, str] = {}
    if not isinstance(raw, Mapping):
        raise ValidationError({"event": "Event must be an object."})

    ts_raw = raw.get("timestamp")
    try:
        missed_dt = _parse_ts(ts_raw)
    except (ValueError, AttributeError):
        errors["timestamp"] = "Must be an ISO-8601 timestamp."
        missed_dt = None

    digits = digits_only(str(raw.get("caller_id") or ""))
    if len(digits) < 7:
        errors["caller_id"] = "Must contain at least 7 digits."

    ring_count = raw.get("ring_count")
    rings: Optional[int] = None
    if ring_count is not None and ring_count != "":
        try:
            rings = int(ring_count)
        except (TypeError, ValueError):
            errors["ring_count"] = "Must be an integer."
        else:
            if not 0 <= rings <= RING_COUNT_MAX:
                errors["ring_count"] = f"Must be 0..{RING_COUNT_MAX}."

    duration = raw.get("duration_seconds", 0)
    duration_seconds = 0
    if duration is not None and duration != "":
        try:
            duration_seconds = int(duration)
        except (TypeError, ValueError):
            errors["duration_seconds"] = "Must be an integer."
        else:
            if not 0 <= duration_seconds <= DURATION_MAX_SECONDS:
                errors["duration_seconds"] = (
                    f"Must be 0..{DURATION_MAX_SECONDS}."
                )

    transcript = raw.get("transcript")
    if transcript is None:
        transcript = ""
    elif not isinstance(transcript, str):
        errors["transcript"] = "Must be a string when provided."
    elif len(transcript) > TRANSCRIPT_MAX_CHARS:
        transcript = transcript[:TRANSCRIPT_MAX_CHARS]

    if errors:
        raise ValidationError(errors)

    return {
        "missed_at": missed_dt.isoformat(),  # type: ignore[union-attr]
        "caller_digits": digits,
        "caller_masked": mask_caller_id(digits),
        "caller_hash": hash_caller_id(digits),
        "ring_count": rings,
        "duration_seconds": duration_seconds,
        "transcript": transcript,
    }


# ---------------------------------------------------------------------------
# Audit events (call-specific; events.py is lead/request-specific)
# ---------------------------------------------------------------------------

def _record_call_event(
    conn: sqlite3.Connection,
    call_id: int,
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
        INSERT INTO call_events
            (call_id, event_type, actor, from_state, to_state, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (call_id, event_type, actor, from_state, to_state, detail_json, created),
    )
    event_id = cur.lastrowid
    conn.commit()
    print(
        json.dumps(
            {
                "ts": created,
                "event": event_type,
                "event_id": event_id,
                "call_id": call_id,
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
# Ingestion
# ---------------------------------------------------------------------------

def _repeat_count(conn: sqlite3.Connection, caller_hash: str, missed_at: str) -> int:
    """Prior missed calls from this caller within the repeat window."""
    since = (
        _parse_ts(missed_at) - timedelta(hours=REPEAT_WINDOW_HOURS)
    ).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM missed_calls
        WHERE caller_id_hash = ? AND missed_at >= ? AND missed_at < ?
        """,
        (caller_hash, since, missed_at),
    ).fetchone()
    return row["c"]


def ingest_event(
    conn: sqlite3.Connection,
    raw: Mapping[str, Any],
    *,
    source: str = "webhook",
    actor: str = "system",
    scorer: Optional[UrgencyScorer] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Ingest one missed-call event (the JSON webhook shape).

    Validates, scores, masks/hashes the caller ID, and stores the call.
    An event with the same caller + timestamp as an existing row is a
    duplicate: no new row is created and the original is reported.
    """
    scorer = scorer or DeterministicDemoScorer()
    cleaned = normalize_event(raw)  # raises ValidationError; nothing stored
    now_iso = _now_or(now).isoformat()
    dedup_key = dedup_key_for(cleaned["caller_hash"], cleaned["missed_at"])

    existing = conn.execute(
        "SELECT id, public_id FROM missed_calls WHERE dedup_key = ?",
        (dedup_key,),
    ).fetchone()
    if existing:
        _record_call_event(
            conn, existing["id"], existing["public_id"],
            "call.duplicate_received", actor,
            detail={"dedup_key": dedup_key, "source": source},
        )
        return {
            "call_id": existing["id"],
            "public_id": existing["public_id"],
            "state": "pending",
            "duplicate": True,
        }

    repeat = _repeat_count(conn, cleaned["caller_hash"], cleaned["missed_at"])
    urgency = scorer.score({
        "repeat_count": repeat,
        "missed_at": cleaned["missed_at"],
        "transcript": cleaned["transcript"],
        "ring_count": cleaned["ring_count"],
    })

    flags = list(urgency.flags)
    if repeat + 1 >= REPEAT_ANOMALY_THRESHOLD:
        # Never auto-trust: a burst of missed calls from one ID is flagged
        # for human review rather than boosted or dropped.
        flags.append("repeat-id-anomaly")

    cur = conn.execute(
        """
        INSERT INTO missed_calls
            (public_id, missed_at, caller_id_masked, caller_id_hash,
             ring_count, duration_seconds, transcript,
             urgency_score, urgency_reasons, urgency_scorer, flags,
             state, source, dedup_key, created_at, updated_at)
        VALUES ('pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            cleaned["missed_at"], cleaned["caller_masked"], cleaned["caller_hash"],
            cleaned["ring_count"], cleaned["duration_seconds"], cleaned["transcript"],
            urgency.score, json.dumps(list(urgency.reasons), sort_keys=True),
            urgency.scorer, json.dumps(flags, sort_keys=True),
            source, dedup_key, now_iso, now_iso,
        ),
    )
    call_id = cur.lastrowid
    public_id = f"MC-{call_id:06d}"
    conn.execute("UPDATE missed_calls SET public_id = ? WHERE id = ?", (public_id, call_id))
    conn.commit()

    _record_call_event(
        conn, call_id, public_id, "call.received", actor, to_state="pending",
        detail={"source": source, "repeat_count": repeat, "dedup_key": dedup_key},
    )
    _record_call_event(
        conn, call_id, public_id, "call.scored", "system", to_state="pending",
        detail={"score": urgency.score, "scorer": urgency.scorer,
                "reasons": list(urgency.reasons), "flags": flags},
    )
    return {
        "call_id": call_id,
        "public_id": public_id,
        "state": "pending",
        "urgency_score": urgency.score,
        "flags": flags,
        "duplicate": False,
    }


def ingest_csv(
    conn: sqlite3.Connection,
    text: str,
    *,
    source: str = "csv",
    actor: str = "system",
    scorer: Optional[UrgencyScorer] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Ingest CSV text with a header row.

    Expected columns: ``timestamp, caller_id`` (required),
    ``ring_count, duration_seconds, transcript`` (optional).
    Row-level failures never abort the batch: accepted rows are stored,
    failures are returned with their row number and field errors.
    """
    scorer = scorer or DeterministicDemoScorer()
    reader = csv.DictReader(io.StringIO(text or ""))
    accepted, duplicates = 0, 0
    errors: list[dict] = []
    first_row_public_id: Optional[str] = None
    for lineno, row in enumerate(reader, start=2):
        try:
            result = ingest_event(
                conn, row, source=source, actor=actor, scorer=scorer, now=now
            )
        except ValidationError as exc:
            errors.append({"row": lineno, "fields": exc.field_errors})
            continue
        if result["duplicate"]:
            duplicates += 1
        else:
            accepted += 1
            if first_row_public_id is None:
                first_row_public_id = result["public_id"]
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": len(errors),
        "errors": errors,
        "first_public_id": first_row_public_id,
    }


def _get_idempotency(conn: sqlite3.Connection, key: str, ttl_hours: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT response_status, response_body, created_at FROM call_idempotency_keys WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    created = datetime.fromisoformat(row["created_at"])
    if datetime.now(timezone.utc) - created > timedelta(hours=ttl_hours):
        conn.execute("DELETE FROM call_idempotency_keys WHERE key = ?", (key,))
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
        INSERT OR REPLACE INTO call_idempotency_keys
            (key, response_status, response_body, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (key, status, json.dumps(body, sort_keys=True), utcnow_iso()),
    )
    conn.commit()


def ingest_with_idempotency(
    conn: sqlite3.Connection,
    raw_or_csv: Any,
    *,
    idempotency_key: Optional[str] = None,
    is_csv: bool = False,
    ttl_hours: int = 72,
    **kwargs: Any,
) -> dict:
    """Idempotent ingestion wrapper: a repeated key replays the original
    response without creating duplicate business records."""
    if idempotency_key:
        hit = _get_idempotency(conn, idempotency_key, ttl_hours)
        if hit is not None:
            return hit
    if is_csv:
        body = ingest_csv(conn, raw_or_csv, **kwargs)
        status = 201
    else:
        body = ingest_event(conn, raw_or_csv, **kwargs)
        status = 201
    if idempotency_key:
        _store_idempotency(conn, idempotency_key, status, body)
    return {"status": status, "body": body, "replayed": False}


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def get_call_by_id(conn: sqlite3.Connection, call_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM missed_calls WHERE id = ?", (call_id,)).fetchone()
    return dict(row) if row else None


def get_call(conn: sqlite3.Connection, public_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM missed_calls WHERE public_id = ?", (public_id,)
    ).fetchone()
    return dict(row) if row else None


def call_events(conn: sqlite3.Connection, call_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM call_events WHERE call_id = ? ORDER BY id ASC", (call_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Queue, claim/assign, outcomes
# ---------------------------------------------------------------------------

def _age_hours(missed_at: str, now: datetime) -> float:
    return max(0.0, (now - _parse_ts(missed_at)).total_seconds() / 3600.0)


def priority_of(urgency_score: float, age_hours: float) -> float:
    """priority = score x age decay. Older calls decay: halves every 24h."""
    return round(
        urgency_score / (1.0 + age_hours / _AGE_DECAY_HALF_LIFE_HOURS), 4
    )


def priority_queue(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None, limit: int = 50
) -> list[dict]:
    """Pending calls ordered by priority (urgency score x age decay)."""
    now = _now_or(now)
    rows = conn.execute(
        "SELECT * FROM missed_calls WHERE state = 'pending' ORDER BY urgency_score DESC, missed_at ASC"
    ).fetchall()
    queue = []
    for r in rows:
        call = dict(r)
        age = _age_hours(call["missed_at"], now)
        call["age_hours"] = round(age, 2)
        call["priority"] = priority_of(call["urgency_score"], age)
        queue.append(call)
    queue.sort(key=lambda c: (-c["priority"], c["missed_at"]))
    return queue[:limit]


def claim_call(
    conn: sqlite3.Connection, public_id: str, assignee: str, actor: str
) -> dict:
    """Claim/assign a pending call to a person. State is unchanged."""
    call = get_call(conn, public_id)
    if call is None:
        raise KeyError(f"No missed call {public_id!r}.")
    if call["state"] != "pending":
        raise InvalidTransition(
            f"Only pending calls can be claimed; {public_id} is {call['state']!r}."
        )
    if not assignee or not assignee.strip():
        raise ValidationError({"assignee": "An assignee name is required."})
    now = utcnow_iso()
    conn.execute(
        "UPDATE missed_calls SET assigned_to = ?, updated_at = ? WHERE id = ?",
        (assignee.strip(), now, call["id"]),
    )
    conn.commit()
    _record_call_event(
        conn, call["id"], public_id, "call.claimed", actor,
        detail={"assigned_to": assignee.strip()},
    )
    return get_call(conn, public_id)


def log_outcome(
    conn: sqlite3.Connection,
    public_id: str,
    to_state: str,
    actor: str,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Record a callback outcome. Enforces the call workflow:

    pending -> attempted -> connected -> booked | lost
    attempted -> lost, connected -> lost, pending -> lost (admin close)
    booked / lost are terminal.
    """
    call = get_call(conn, public_id)
    if call is None:
        raise KeyError(f"No missed call {public_id!r}.")
    CALL_WORKFLOW.check(call["state"], to_state)
    now_iso = _now_or(now).isoformat()
    stamp_updates: dict[str, Any] = {"state": to_state, "updated_at": now_iso}
    if to_state == "attempted" and call["attempted_at"] is None:
        stamp_updates["attempted_at"] = now_iso
    if to_state in ("booked", "lost"):
        stamp_updates["outcome_at"] = now_iso
    sets = ", ".join(f"{k} = ?" for k in stamp_updates)
    conn.execute(
        f"UPDATE missed_calls SET {sets} WHERE id = ?",
        (*stamp_updates.values(), call["id"]),
    )
    conn.commit()
    _record_call_event(
        conn, call["id"], public_id, f"call.{to_state}", actor,
        from_state=call["state"], to_state=to_state, created=now_iso,
    )
    return get_call(conn, public_id)


# ---------------------------------------------------------------------------
# Failure analysis: SLA escalation, ingestion lag
# ---------------------------------------------------------------------------

def sweep_sla(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
    sla_hours: float = 2.0,
    urgency_threshold: float = 0.7,
) -> list[dict]:
    """Escalate high-urgency pending calls older than the SLA.

    Escalated calls are flagged (``escalated = 1``) and a row is written to
    ``owner_notifications`` — a STUB: no real notification is sent anywhere.
    The stub exists so the escalation path is exercised and tested.
    The sweep is idempotent: already-escalated calls are never re-notified.
    """
    now = _now_or(now)
    escalated = []
    pending = conn.execute(
        "SELECT * FROM missed_calls WHERE state = 'pending' AND escalated = 0"
    ).fetchall()
    for r in pending:
        call = dict(r)
        if call["urgency_score"] < urgency_threshold:
            continue
        if _age_hours(call["missed_at"], now) < sla_hours:
            continue
        now_iso = now.isoformat()
        conn.execute(
            "UPDATE missed_calls SET escalated = 1, updated_at = ? WHERE id = ?",
            (now_iso, call["id"]),
        )
        conn.execute(
            """
            INSERT INTO owner_notifications (call_id, message, status, created_at)
            VALUES (?, ?, 'queued-stub', ?)
            """,
            (
                call["id"],
                f"STUB — owner notification for {call['public_id']}: "
                f"high-urgency missed call ({call['urgency_score']}) from "
                f"{call['caller_id_masked']} waiting > {sla_hours}h. "
                f"No real message was sent.",
                now_iso,
            ),
        )
        conn.commit()
        _record_call_event(
            conn, call["id"], call["public_id"], "call.escalated", "system",
            to_state="pending",
            detail={"reason": "sla_breach", "sla_hours": sla_hours,
                    "urgency_score": call["urgency_score"]},
        )
        escalated.append(get_call(conn, call["public_id"]))
    return escalated


def ingestion_lag_report(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None,
    max_gap_hours: float = 6.0,
) -> dict:
    """Ingestion-lag alert stub.

    v1 has no live telephony feed, so "ingestion lag" means: the newest
    stored event is older than ``max_gap_hours`` relative to now. A real
    deployment would compare against the feed's heartbeat instead.
    """
    now = _now_or(now)
    row = conn.execute(
        "SELECT MAX(missed_at) AS newest FROM missed_calls"
    ).fetchone()
    newest = row["newest"]
    if newest is None:
        return {"alert": False, "gap_hours": None, "newest_missed_at": None,
                "message": "No calls ingested yet."}
    gap = _age_hours(newest, now)
    alert = gap > max_gap_hours
    return {
        "alert": alert,
        "gap_hours": round(gap, 2),
        "newest_missed_at": newest,
        "message": (
            f"Ingestion feed may be stale: newest event is "
            f"{round(gap, 1)}h old (threshold {max_gap_hours}h)."
            if alert else "Ingestion feed is current."
        ),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def dashboard_stats(conn: sqlite3.Connection, *, now: Optional[datetime] = None) -> dict:
    """Dashboard aggregates, computed directly from the database.

    - recovery_rate: booked / total missed calls
    - contact_rate: (connected + booked) / total missed calls
    - median_time_to_callback_minutes: median(missed_at -> first attempted)
      over calls that have been attempted
    Every total must reconcile with the source rows (asserted by tests).
    """
    now = _now_or(now)
    by_state = {
        r["state"]: r["c"]
        for r in conn.execute(
            "SELECT state, COUNT(*) AS c FROM missed_calls GROUP BY state"
        ).fetchall()
    }
    total = conn.execute("SELECT COUNT(*) AS c FROM missed_calls").fetchone()["c"]
    booked = by_state.get("booked", 0)
    connected = by_state.get("connected", 0)
    escalated = conn.execute(
        "SELECT COUNT(*) AS c FROM missed_calls WHERE escalated = 1"
    ).fetchone()["c"]

    first_attempts = conn.execute(
        """
        SELECT m.public_id, m.missed_at, MIN(e.created_at) AS first_attempt
        FROM missed_calls m
        JOIN call_events e ON e.call_id = m.id AND e.event_type = 'call.attempted'
        GROUP BY m.id
        """
    ).fetchall()
    ttcb = [
        (_parse_ts(r["first_attempt"]) - _parse_ts(r["missed_at"])).total_seconds() / 60.0
        for r in first_attempts
    ]

    high_urgency_pending = conn.execute(
        "SELECT COUNT(*) AS c FROM missed_calls WHERE state = 'pending' AND urgency_score >= 0.7"
    ).fetchone()["c"]

    return {
        "total": total,
        "by_state": by_state,
        "booked": booked,
        "escalated": escalated,
        "high_urgency_pending": high_urgency_pending,
        "recovery_rate": round(booked / total, 4) if total else 0.0,
        "contact_rate": round((connected + booked) / total, 4) if total else 0.0,
        "median_time_to_callback_minutes": (
            round(_median(ttcb), 2) if ttcb else None
        ),
        "attempted_calls": len(ttcb),
    }
