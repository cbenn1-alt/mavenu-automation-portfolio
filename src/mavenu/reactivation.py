"""Project Q03 — Customer Reactivation Engine.

Pipeline: synthetic job history -> RFM features -> dormancy score ->
segment -> per-segment win-back sequence -> outbox queue -> (stub)
adapter -> send log -> attribution holdout report.

v1 sends NOTHING. A touch reaches a customer only through a
``MessageAdapter``; the bundled adapter (reused from Q02's ``cadence``
module) is a stub that writes a send-log row. The adapter protocol is the
seam where a real provider would plug in later — and where consent /
opt-out review (see SECURITY.md) would be required before any real
message goes out.

Suppression is absolute: a customer with do-not-contact set, a recent
complaint, or an active job is excluded from EVERY win-back step. The
flag is checked at queue-build time AND re-checked at flush time, so a
complaint recorded mid-sequence stops the remaining touches. Adversarial
tests assert zero touches to suppressed customers.

All timestamps are UTC ISO-8601; every mutating call accepts an
injectable ``now`` (frozen clock) so cadence math is testable and
deterministic.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from . import rfm as rfm_module
from .cadence import MessageAdapter, StubMessageAdapter
from .db import utcnow_iso
from .rfm import DeterministicDemoScorer, DormancyScorer, compute_rfm
from .validation import ValidationError

SERVICE_TYPES = ("hvac", "plumbing", "electrical", "roofing", "landscaping")
BOOKING_SOURCES = ("organic", "reactivation")

SEGMENTS = ("active", "cooling", "dormant", "churned")

# Segment boundaries on the dormancy score (higher = more dormant).
# A customer lands in the first segment whose upper bound exceeds the score.
SEGMENT_BOUNDS = (
    ("active", 0.25),
    ("cooling", 0.50),
    ("dormant", 0.75),
    ("churned", 1.01),  # catch-all for scores up to 1.0
)

# A complaint suppresses win-back touches for this many days afterwards.
COMPLAINT_LOOKBACK_DAYS = 180

# How often a customer may receive win-back touches, across all segments.
GLOBAL_TOUCH_CAP_PER_90_DAYS = 6

DEMO_FOOTER = "(demo touch; nothing was sent)"


def _now_or(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _now_iso(now: Optional[datetime]) -> str:
    return _now_or(now).isoformat()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Win-back sequence plans (per segment)
#
# Each step: rendered when due (``days_after_scored`` days after the
# customer's scoring timestamp), queued once, sent through the stub
# adapter. Copy is reminders-only — never pressure tactics (see
# SECURITY.md). {{variables}} fail closed on missing values.
# ---------------------------------------------------------------------------

SEQUENCE_PLANS: dict[str, list[dict]] = {
    "active": [],
    "cooling": [
        {
            "step_index": 1,
            "days_after_scored": 0,
            "channel": "email",
            "subject": "Checking in, {{customer_name}}",
            "body": (
                "Hi {{customer_name}},\n\nIt has been {{dormancy_months}} months "
                "since your last {{last_service}} visit. If anything needs "
                "attention before it becomes urgent, we are one call away.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
        {
            "step_index": 2,
            "days_after_scored": 10,
            "channel": "email",
            "subject": "Seasonal reminder for {{customer_name}}",
            "body": (
                "Hi {{customer_name}},\n\nA quick seasonal reminder: a short "
                "{{last_service}} check now is cheaper than an emergency call "
                "later. Reply if you would like us to stop these reminders.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
    ],
    "dormant": [
        {
            "step_index": 1,
            "days_after_scored": 0,
            "channel": "email",
            "subject": "We miss working with you, {{customer_name}}",
            "body": (
                "Hi {{customer_name}},\n\nIt has been a while since your last "
                "{{last_service}} job with us ({{dormancy_months}} months). "
                "If something has come up, we would be glad to help again — "
                "no pressure, just a reminder that we are here.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
        {
            "step_index": 2,
            "days_after_scored": 7,
            "channel": "email",
            "subject": "A reason to come back, {{customer_name}}",
            "body": (
                "Hi {{customer_name}},\n\nAs a thank-you for being a past "
                "customer, mention this note for priority scheduling on your "
                "next {{last_service}} visit. Reply STOP any time and we will "
                "not contact you again.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
        {
            "step_index": 3,
            "days_after_scored": 21,
            "channel": "email",
            "subject": "Last check-in, {{customer_name}}",
            "body": (
                "Hi {{customer_name}},\n\nThis is our last scheduled check-in. "
                "If the timing was never right, no worries — we will leave "
                "you in peace unless you reach out.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
    ],
    "churned": [
        {
            "step_index": 1,
            "days_after_scored": 0,
            "channel": "email",
            "subject": "Is everything alright, {{customer_name}}?",
            "body": (
                "Hi {{customer_name}},\n\nIt has been {{dormancy_months}} months "
                "since we last helped with {{last_service}}. If something "
                "about our service fell short, we would genuinely like to "
                "know — reply and a human will read it.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
        {
            "step_index": 2,
            "days_after_scored": 30,
            "channel": "email",
            "subject": "Closing the loop, {{customer_name}}",
            "body": (
                "Hi {{customer_name}},\n\nWe are closing out our win-back "
                "sequence. You will not hear from us again about this unless "
                "you ask. Thank you for having been a customer.\n\n"
                f"{DEMO_FOOTER}"
            ),
        },
    ],
}


class TouchRenderError(Exception):
    """Raised when a touch template cannot be rendered (fail closed)."""


_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def render_touch(template: str, context: Mapping[str, Any]) -> str:
    """Render a {{variable}} template. Missing variables are a hard failure."""
    missing: list[str] = []

    def _sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in context or context[name] is None:
            missing.append(name)
            return match.group(0)
        return str(context[name])

    rendered = _VAR_RE.sub(_sub, template)
    if missing:
        raise TouchRenderError(
            f"Missing template variables: {', '.join(sorted(set(missing)))}"
        )
    return rendered


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

def _record_event(
    conn: sqlite3.Connection,
    customer_id: Optional[int],
    event_type: str,
    actor: str,
    detail: Optional[dict[str, Any]] = None,
    created: Optional[str] = None,
) -> int:
    created = created or utcnow_iso()
    cur = conn.execute(
        """
        INSERT INTO reactivation_events
            (customer_id, event_type, actor, detail, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            customer_id,
            event_type,
            actor,
            json.dumps(detail, sort_keys=True) if detail is not None else None,
            created,
        ),
    )
    conn.commit()
    event_id = cur.lastrowid
    print(
        json.dumps(
            {
                "ts": created,
                "event": event_type,
                "event_id": event_id,
                "customer_id": customer_id,
                "actor": actor,
                "detail": detail or {},
            },
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
    return event_id


# ---------------------------------------------------------------------------
# Customers and synthetic job history
# ---------------------------------------------------------------------------

def _next_public_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT MAX(id) AS m FROM reactivation_customers").fetchone()
    nxt = (row["m"] or 0) + 1
    return f"CUS-{nxt:06d}"


def create_customer(
    conn: sqlite3.Connection,
    *,
    customer_name: str,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Create a synthetic customer record (no real PII — fixtures only)."""
    errors: dict[str, str] = {}
    name = (customer_name or "").strip()
    if not name:
        errors["customer_name"] = "A customer name is required."
    if len(name) > 200:
        errors["customer_name"] = "Customer name is too long (max 200 chars)."
    if errors:
        raise ValidationError(errors)
    now_iso = _now_iso(now)
    public_id = _next_public_id(conn)
    cur = conn.execute(
        """
        INSERT INTO reactivation_customers
            (public_id, customer_name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (public_id, name, now_iso, now_iso),
    )
    conn.commit()
    customer = get_customer(conn, cur.lastrowid)
    _record_event(
        conn, customer["id"], "customer.created", actor,
        {"public_id": public_id}, created=now_iso,
    )
    return customer


def get_customer(conn: sqlite3.Connection, customer_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM reactivation_customers WHERE id = ?", (customer_id,)
    ).fetchone()
    return dict(row) if row else None


def get_customer_by_public_id(conn: sqlite3.Connection, public_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM reactivation_customers WHERE public_id = ?", (public_id,)
    ).fetchone()
    return dict(row) if row else None


def list_customers(
    conn: sqlite3.Connection, *, segment: Optional[str] = None, limit: int = 500
) -> list[dict]:
    if segment:
        rows = conn.execute(
            "SELECT * FROM reactivation_customers WHERE segment = ? "
            "ORDER BY dormancy_score DESC NULLS LAST, id ASC LIMIT ?",
            (segment, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reactivation_customers ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_job(
    conn: sqlite3.Connection,
    customer_id: int,
    *,
    job_ref: str,
    service_type: str,
    job_date: str,
    amount_cents: int,
    booking_source: str = "organic",
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Record one synthetic completed job in the customer's history."""
    errors: dict[str, str] = {}
    if get_customer(conn, customer_id) is None:
        errors["customer_id"] = "Unknown customer."
    if service_type not in SERVICE_TYPES:
        errors["service_type"] = f"Must be one of: {', '.join(SERVICE_TYPES)}."
    try:
        amount = int(amount_cents)
        if amount <= 0:
            errors["amount_cents"] = "Must be a positive integer (cents)."
    except (TypeError, ValueError):
        errors["amount_cents"] = "Must be a positive integer (cents)."
        amount = 0
    if booking_source not in BOOKING_SOURCES:
        errors["booking_source"] = f"Must be one of: {', '.join(BOOKING_SOURCES)}."
    try:
        _parse_ts(job_date)
    except (ValueError, TypeError, AttributeError):
        errors["job_date"] = "Must be an ISO-8601 timestamp."
    if not (job_ref or "").strip():
        errors["job_ref"] = "A job reference is required."
    if errors:
        raise ValidationError(errors)
    now_iso = _now_iso(now)
    cur = conn.execute(
        """
        INSERT INTO reactivation_jobs
            (customer_id, job_ref, service_type, job_date, amount_cents,
             booking_source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (customer_id, job_ref.strip(), service_type, job_date, amount,
         booking_source, now_iso),
    )
    conn.commit()
    job = dict(
        conn.execute(
            "SELECT * FROM reactivation_jobs WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    )
    _record_event(
        conn, customer_id, "job.recorded", actor,
        {"job_ref": job["job_ref"], "booking_source": booking_source},
        created=now_iso,
    )
    return job


def customer_jobs(conn: sqlite3.Connection, customer_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM reactivation_jobs WHERE customer_id = ? ORDER BY job_date ASC",
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Suppression (absolute)
# ---------------------------------------------------------------------------

def suppression_reason(customer: Mapping[str, Any], now: datetime) -> Optional[str]:
    """Return the suppression reason, or None when the customer may be touched.

    Order is fixed so audits are stable: do_not_contact > recent_complaint
    > active_job. Any single reason suppresses absolutely.
    """
    if int(customer.get("do_not_contact") or 0) == 1:
        return "do_not_contact"
    complaint_at = customer.get("complaint_at")
    if complaint_at:
        try:
            age_days = (now - _parse_ts(str(complaint_at))).total_seconds() / 86400.0
        except (ValueError, TypeError):
            age_days = 0.0
        if 0 <= age_days <= COMPLAINT_LOOKBACK_DAYS:
            return "recent_complaint"
    if int(customer.get("active_job") or 0) == 1:
        return "active_job"
    return None


def is_suppressed(customer: Mapping[str, Any], now: datetime) -> bool:
    return suppression_reason(customer, now) is not None


def set_suppression(
    conn: sqlite3.Connection,
    customer_id: int,
    *,
    do_not_contact: Optional[bool] = None,
    active_job: Optional[bool] = None,
    active_job_ref: Optional[str] = None,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Set or clear suppression flags. Every change is audit-logged."""
    customer = get_customer(conn, customer_id)
    if customer is None:
        raise ValidationError({"customer_id": "Unknown customer."})
    now_dt = _now_or(now)
    now_iso = now_dt.isoformat()
    updates: list[str] = []
    params: list[Any] = []
    detail: dict[str, Any] = {}
    if do_not_contact is not None:
        updates.append("do_not_contact = ?")
        params.append(1 if do_not_contact else 0)
        detail["do_not_contact"] = bool(do_not_contact)
    if active_job is not None:
        updates.append("active_job = ?")
        params.append(1 if active_job else 0)
        detail["active_job"] = bool(active_job)
        if active_job_ref is not None:
            updates.append("active_job_ref = ?")
            params.append(active_job_ref)
            detail["active_job_ref"] = active_job_ref
    if not updates:
        raise ValidationError({"suppression": "Nothing to change."})
    updates.append("updated_at = ?")
    params.append(now_iso)
    params.append(customer_id)
    conn.execute(
        f"UPDATE reactivation_customers SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )
    conn.commit()
    _record_event(
        conn, customer_id, "customer.suppression_set", actor, detail, created=now_iso
    )
    return get_customer(conn, customer_id)


def record_complaint(
    conn: sqlite3.Connection,
    customer_id: int,
    *,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Record a customer complaint at ``now`` (suppresses win-back touches)."""
    customer = get_customer(conn, customer_id)
    if customer is None:
        raise ValidationError({"customer_id": "Unknown customer."})
    now_iso = _now_or(now).isoformat()
    conn.execute(
        """
        UPDATE reactivation_customers
        SET complaint_at = ?, updated_at = ? WHERE id = ?
        """,
        (now_iso, now_iso, customer_id),
    )
    conn.commit()
    _record_event(
        conn, customer_id, "customer.complaint_recorded", actor,
        {"complaint_at": now_iso,
         "lookback_days": COMPLAINT_LOOKBACK_DAYS},
        created=now_iso,
    )
    return get_customer(conn, customer_id)


# ---------------------------------------------------------------------------
# Scoring + segmentation
# ---------------------------------------------------------------------------

def segment_for_score(score: float) -> str:
    """Map a dormancy score to its segment (documented boundaries)."""
    for segment, bound in SEGMENT_BOUNDS:
        if score < bound:
            return segment
    return "churned"  # unreachable given the 1.01 catch-all, kept for safety


def score_customers(
    conn: sqlite3.Connection,
    *,
    scorer: Optional[DormancyScorer] = None,
    now: Optional[datetime] = None,
    actor: str = "system",
) -> list[dict]:
    """Compute RFM features, score dormancy, and persist segment per customer.

    Pure scoring: ``scorer.score(features)`` is a deterministic function of
    the features, so replays produce identical scores (tested). Persists
    ``segment``, ``dormancy_score`` and ``scored_at`` and writes one
    ``customer.scored`` audit event per customer.
    """
    scorer = scorer or DeterministicDemoScorer()
    now_dt = _now_or(now)
    now_iso = now_dt.isoformat()
    results: list[dict] = []
    for customer in list_customers(conn, limit=10_000):
        jobs = customer_jobs(conn, customer["id"])
        features = compute_rfm(
            [{"job_date": j["job_date"], "amount_cents": j["amount_cents"]}
             for j in jobs],
            now=now_dt,
        )
        scored = scorer.score(
            {
                "recency_days": features.recency_days,
                "frequency": features.frequency,
                "monetary_cents": features.monetary_cents,
            }
        )
        segment = segment_for_score(scored.score)
        conn.execute(
            """
            UPDATE reactivation_customers
            SET segment = ?, dormancy_score = ?, scored_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (segment, scored.score, now_iso, now_iso, customer["id"]),
        )
        conn.commit()
        _record_event(
            conn, customer["id"], "customer.scored", actor,
            {
                "scorer": scored.scorer,
                "score": scored.score,
                "segment": segment,
                "features": {
                    "recency_days": features.recency_days,
                    "frequency": features.frequency,
                    "monetary_cents": features.monetary_cents,
                },
                "reasons": list(scored.reasons),
            },
            created=now_iso,
        )
        results.append(
            {**get_customer(conn, customer["id"]),
             "score_reasons": list(scored.reasons),
             "score_flags": list(scored.flags)}
        )
    return results


# ---------------------------------------------------------------------------
# Win-back runs: queue due touches (suppression checked at build time)
# ---------------------------------------------------------------------------

def _outbox_key(customer_id: int, segment: str, step_index: int) -> str:
    return f"rx:{customer_id}:seg:{segment}:step:{step_index}"


def _touch_context(customer: Mapping[str, Any], now: datetime) -> dict:
    jobs = None  # resolved by caller when needed; kept simple here
    last_service = customer.get("last_service") or "home service"
    recency_days = customer.get("recency_days")
    dormancy_months = (
        f"{float(recency_days) / 30.0:.0f}" if recency_days is not None else "many"
    )
    return {
        "customer_name": customer["customer_name"],
        "last_service": last_service,
        "dormancy_months": dormancy_months,
        "segment": customer.get("segment") or "",
        "jobs": jobs,
    }


def _recent_touch_count(conn: sqlite3.Connection, customer_id: int, now: datetime) -> int:
    cutoff = (now.timestamp() - 90 * 86400)
    rows = conn.execute(
        """
        SELECT created_at FROM reactivation_outbox
        WHERE customer_id = ? AND status IN ('queued', 'sent')
        """,
        (customer_id,),
    ).fetchall()
    count = 0
    for r in rows:
        try:
            if _parse_ts(r["created_at"]).timestamp() >= cutoff:
                count += 1
        except (ValueError, TypeError):
            continue
    return count


def run_winback(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
    actor: str = "system",
    segments: Optional[Sequence[str]] = None,
) -> dict:
    """Queue due win-back touches for scored, non-suppressed customers.

    For every scored customer whose segment has a plan (and is in
    ``segments`` when given), each plan step whose
    ``scored_at + days_after_scored`` has elapsed gets exactly one queued
    outbox row — unless the customer is suppressed (checked here, at
    build time) or the step was already queued (idempotency key). A
    global frequency cap guards against over-contact. Scheduler replays
    are idempotent.

    Returns ``{"queued": [...], "skipped": [...]}``; skipped entries name
    the reason (suppressed / frequency_cap / render_error / no_plan).
    """
    now_dt = _now_or(now)
    now_iso = now_dt.isoformat()
    wanted = set(segments) if segments else set(SEQUENCE_PLANS)
    queued: list[dict] = []
    skipped: list[dict] = []

    for customer in list_customers(conn, limit=10_000):
        segment = customer.get("segment")
        public_id = customer["public_id"]
        if not segment or segment not in wanted:
            skipped.append({"public_id": public_id, "reason": "no_plan"})
            continue
        plan = SEQUENCE_PLANS.get(segment) or []
        if not plan:
            skipped.append({"public_id": public_id, "reason": "no_plan"})
            continue
        reason = suppression_reason(customer, now_dt)
        if reason is not None:
            skipped.append({"public_id": public_id, "reason": f"suppressed:{reason}"})
            _record_event(
                conn, customer["id"], "customer.suppressed", actor,
                {"reason": reason, "segment": segment}, created=now_iso,
            )
            continue
        if _recent_touch_count(conn, customer["id"], now_dt) >= GLOBAL_TOUCH_CAP_PER_90_DAYS:
            skipped.append({"public_id": public_id, "reason": "frequency_cap"})
            continue
        scored_at = _parse_ts(customer["scored_at"]) if customer.get("scored_at") else now_dt
        jobs = customer_jobs(conn, customer["id"])
        last_service = jobs[-1]["service_type"] if jobs else "home service"
        context = _touch_context(
            {**customer, "last_service": last_service,
             "recency_days": _recency_days(customer, jobs, now_dt)},
            now_dt,
        )
        for step in plan:
            due_at = scored_at.timestamp() + step["days_after_scored"] * 86400.0
            if now_dt.timestamp() < due_at:
                continue  # not due yet
            key = _outbox_key(customer["id"], segment, step["step_index"])
            exists = conn.execute(
                "SELECT 1 FROM reactivation_outbox WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if exists:
                continue  # replay-safe: already queued for this step
            try:
                subject = render_touch(step["subject"], context)
                body = render_touch(step["body"], context)
            except TouchRenderError as exc:
                skipped.append(
                    {"public_id": public_id,
                     "reason": f"render_error:{exc}"}
                )
                _record_event(
                    conn, customer["id"], "touch.skipped", actor,
                    {"step_index": step["step_index"], "reason": str(exc)},
                    created=now_iso,
                )
                continue
            cur = conn.execute(
                """
                INSERT INTO reactivation_outbox
                    (idempotency_key, customer_id, segment, step_index,
                     channel, scheduled_for, status, recipient_label,
                     subject, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    key, customer["id"], segment, step["step_index"],
                    step["channel"], now_iso,
                    f"synthetic-customer:{public_id}",
                    subject, body, now_iso,
                ),
            )
            if cur.rowcount == 0:
                continue  # lost a race; the guard is real even if unreachable here
            conn.commit()
            _record_event(
                conn, customer["id"], "touch.queued", actor,
                {"step_index": step["step_index"], "segment": segment,
                 "channel": step["channel"], "outbox_id": cur.lastrowid,
                 "idempotency_key": key},
                created=now_iso,
            )
            queued.append(
                {"public_id": public_id, "segment": segment,
                 "step_index": step["step_index"], "outbox_id": cur.lastrowid}
            )
    return {"queued": queued, "skipped": skipped}


def _recency_days(
    customer: Mapping[str, Any], jobs: Sequence[Mapping[str, Any]], now: datetime
) -> Optional[float]:
    if not jobs:
        return None
    last = max(jobs, key=lambda j: _parse_ts(str(j["job_date"])))
    return (now - _parse_ts(str(last["job_date"]))).total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# Outbox + flush through the message adapter (stub in v1)
# ---------------------------------------------------------------------------

def outbox(
    conn: sqlite3.Connection, *, status: Optional[str] = None, limit: int = 200
) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM reactivation_outbox WHERE status = ? ORDER BY id ASC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reactivation_outbox ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def send_log(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM reactivation_send_log ORDER BY id ASC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def flush_outbox(
    conn: sqlite3.Connection,
    adapter: Optional[MessageAdapter] = None,
    *,
    now: Optional[datetime] = None,
    actor: str = "system",
) -> list[dict]:
    """Hand every queued outbox row to the adapter and log the outcome.

    Suppression is RE-CHECKED here, at send time: a customer whose
    do-not-contact / complaint / active-job flag was set after the touch
    was queued has the row marked ``suppressed`` — the adapter is never
    called for it and no send-log row is written. This is the second half
    of the absolute-suppression guarantee (the first half is the check at
    queue-build time in ``run_winback``).

    With the stub adapter this is pure bookkeeping: it proves the
    outbox -> adapter -> send-log pipeline shape without sending.
    """
    adapter = adapter or StubMessageAdapter()
    now_dt = _now_or(now)
    now_iso = now_dt.isoformat()
    flushed: list[dict] = []
    for row in outbox(conn, status="queued"):
        customer = get_customer(conn, row["customer_id"])
        reason = suppression_reason(customer, now_dt) if customer else "unknown_customer"
        if reason is not None:
            conn.execute(
                "UPDATE reactivation_outbox SET status = 'suppressed' WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            _record_event(
                conn, row["customer_id"], "touch.suppressed_at_flush", actor,
                {"outbox_id": row["id"], "reason": reason,
                 "note": "suppression flag set after queueing; adapter not called"},
                created=now_iso,
            )
            flushed.append(
                {"outbox_id": row["id"], "adapter": adapter.name,
                 "status": "suppressed", "reason": reason}
            )
            continue
        result = adapter.send(row["recipient_label"], row["subject"], row["body"])
        status = str(result.get("status", "unknown"))
        conn.execute(
            "UPDATE reactivation_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
            (now_iso, row["id"]),
        )
        conn.execute(
            """
            INSERT INTO reactivation_send_log
                (outbox_id, adapter, status, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(outbox_id) DO NOTHING
            """,
            (row["id"], adapter.name, status,
             json.dumps(result, sort_keys=True, default=str), now_iso),
        )
        conn.commit()
        _record_event(
            conn, row["customer_id"], "touch.flushed", actor,
            {"outbox_id": row["id"], "adapter": adapter.name, "status": status},
            created=now_iso,
        )
        flushed.append(
            {"outbox_id": row["id"], "adapter": adapter.name, "status": status}
        )
    return flushed


# ---------------------------------------------------------------------------
# Reports: segments, suppression audit, touch history
# ---------------------------------------------------------------------------

def segment_report(conn: sqlite3.Connection) -> dict:
    """Per-segment customer counts, mean dormancy, and suppression tallies.

    Every total is a direct SQL aggregation over ``reactivation_customers``
    so the report reconciles to source rows by construction (tested with
    independent re-computation).
    """
    segments = []
    for segment in SEGMENTS:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n,
                   AVG(dormancy_score) AS avg_score,
                   SUM(CASE WHEN do_not_contact = 1 OR active_job = 1
                            OR complaint_at IS NOT NULL THEN 1 ELSE 0 END)
                       AS flagged
            FROM reactivation_customers WHERE segment = ?
            """,
            (segment,),
        ).fetchone()
        segments.append(
            {
                "segment": segment,
                "customers": row["n"],
                "avg_dormancy": round(row["avg_score"], 3) if row["avg_score"] is not None else None,
                "suppression_flags": row["flagged"] or 0,
                "plan_steps": len(SEQUENCE_PLANS.get(segment) or []),
            }
        )
    unscored = conn.execute(
        "SELECT COUNT(*) AS n FROM reactivation_customers WHERE segment IS NULL"
    ).fetchone()["n"]
    total = conn.execute("SELECT COUNT(*) AS n FROM reactivation_customers").fetchone()["n"]
    queued = conn.execute(
        "SELECT COUNT(*) AS n FROM reactivation_outbox WHERE status = 'queued'"
    ).fetchone()["n"]
    sent = conn.execute(
        "SELECT COUNT(*) AS n FROM reactivation_outbox WHERE status = 'sent'"
    ).fetchone()["n"]
    suppressed = conn.execute(
        "SELECT COUNT(*) AS n FROM reactivation_outbox WHERE status = 'suppressed'"
    ).fetchone()["n"]
    return {
        "segments": segments,
        "unscored_customers": unscored,
        "total_customers": total,
        "outbox": {"queued": queued, "sent": sent, "suppressed": suppressed},
    }


def suppression_audit(conn: sqlite3.Connection, *, now: Optional[datetime] = None,
                      limit: int = 500) -> dict:
    """Every currently-suppressed customer, its reason, and the audit trail.

    Used to prove the absolute-suppression guarantee: any customer with a
    flag is listed with the reason, and zero of them may hold queued or
    sent outbox rows (asserted in tests).
    """
    now_dt = _now_or(now)
    customers: list[dict] = []
    for customer in list_customers(conn, limit=10_000):
        reason = suppression_reason(customer, now_dt)
        if reason is None:
            continue
        touch_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n FROM reactivation_outbox
            WHERE customer_id = ? GROUP BY status
            """,
            (customer["id"],),
        ).fetchall()
        customers.append(
            {
                "public_id": customer["public_id"],
                "customer_name": customer["customer_name"],
                "reason": reason,
                "segment": customer.get("segment"),
                "outbox_by_status": {r["status"]: r["n"] for r in touch_rows},
            }
        )
    events = conn.execute(
        """
        SELECT * FROM reactivation_events
        WHERE event_type IN ('customer.suppression_set',
                             'customer.complaint_recorded',
                             'customer.suppressed',
                             'touch.suppressed_at_flush')
        ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {
        "suppressed_customers": customers,
        "suppressed_count": len(customers),
        "events": [dict(e) for e in events],
    }


def touch_history(conn: sqlite3.Connection, customer_id: int) -> list[dict]:
    """Queued/sent/suppressed touches for one customer, oldest first."""
    rows = conn.execute(
        "SELECT * FROM reactivation_outbox WHERE customer_id = ? ORDER BY id ASC",
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def customer_events(conn: sqlite3.Connection, customer_id: int,
                    limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM reactivation_events WHERE customer_id = ? "
        "ORDER BY id ASC LIMIT ?",
        (customer_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def rfm_module_info() -> dict:
    """Expose the documented scoring constants for UIs and docs."""
    return {
        "scorer": DeterministicDemoScorer.name,
        "weights": {
            "recency": rfm_module.RECENCY_WEIGHT,
            "frequency": rfm_module.FREQUENCY_WEIGHT,
            "monetary": rfm_module.MONETARY_WEIGHT,
        },
        "normalization": {
            "recency_window_days": rfm_module.RECENCY_WINDOW_DAYS,
            "frequency_cap": rfm_module.FREQUENCY_CAP,
            "monetary_cap_cents": rfm_module.MONETARY_CAP_CENTS,
        },
        "segments": [
            {"segment": seg, "score_below": bound}
            for seg, bound in SEGMENT_BOUNDS
        ],
    }
