"""Project 02 — Enterprise Request & Approval Automation: service layer.

A portfolio SIMULATION of the intake → approval → document-store → SQL
reporting chain (the real-world analogue of Power Apps → Power Automate →
SharePoint → SQL). It is built on a custom Python stack and is NOT a Power
Platform, SharePoint, or UiPath implementation — no such access exists.

Owns the request lifecycle: intake, server-side validation, duplicate
protection (idempotency keys), role-based multi-step approval routing,
deterministic SLA-breach escalation, and an actor-stamped audit trail.
Every state change is recorded as a ``request_events`` row plus a
structured JSON log line.

The clock is injectable: every function that touches time accepts an
optional ``now`` (an aware ``datetime``). When omitted, real UTC time is
used; tests pass a fake clock to make SLA behavior deterministic.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db import utcnow_iso
from .validation import ValidationError, normalize_email
from .workflow import REQUEST_WORKFLOW

# -- domain constants --------------------------------------------------------

REQUEST_TYPES = (
    "purchase",
    "travel",
    "access",
    "hr_change",
    "vendor_onboarding",
    "budget_transfer",
)

# Request types that carry money and therefore require amount > 0.
MONETARY_TYPES = frozenset({"purchase", "travel", "vendor_onboarding", "budget_transfer"})

# Approver roles. The chain is built in code from the request's amount:
# every request needs its manager; requests over the finance threshold
# additionally need finance. An SLA breach escalates to director.
ROLE_MANAGER = "manager"
ROLE_FINANCE = "finance"
ROLE_DIRECTOR = "director"

# Sanity cap: $10,000,000. Catches fat-fingered amounts and abuse.
MAX_AMOUNT_CENTS = 1_000_000_000

MAX_TITLE_LEN = 120
MAX_NAME_LEN = 120
MIN_JUSTIFICATION_LEN = 20
MAX_JUSTIFICATION_LEN = 2000

_COST_CENTER_RE = re.compile(r"^[A-Z0-9]{3,8}$")

DECISIONS = ("approve", "reject", "request_changes")


class ApprovalRoleError(Exception):
    """Raised when a decision comes from a role that does not own the step."""


class InvalidDecision(Exception):
    """Raised when a decision is not allowed in the request's current state."""


# -- time handling ------------------------------------------------------------

def _now(dt: Optional[datetime] = None) -> datetime:
    """Return the effective clock time as an aware UTC datetime."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return _now(dt).isoformat(timespec="seconds")


# -- validation ---------------------------------------------------------------

def _parse_amount_cents(raw: Any, request_type: str, errors: dict) -> int:
    """Parse the amount (dollars) into integer cents; records field errors."""
    if raw in (None, ""):
        if request_type in MONETARY_TYPES:
            errors["amount"] = (
                f"Amount is required for {request_type} requests."
            )
            return 0
        return 0
    try:
        dollars = float(raw)
    except (TypeError, ValueError):
        errors["amount"] = "Amount must be a number of dollars."
        return 0
    if dollars != dollars or dollars in (float("inf"), float("-inf")):
        errors["amount"] = "Amount must be a finite number."
        return 0
    cents = int(round(dollars * 100))
    if request_type in MONETARY_TYPES and cents <= 0:
        errors["amount"] = "Amount must be greater than zero."
    elif cents < 0:
        errors["amount"] = "Amount cannot be negative."
    elif cents > MAX_AMOUNT_CENTS:
        errors["amount"] = (
            f"Amount exceeds the {MAX_AMOUNT_CENTS // 100:,} dollar limit."
        )
    return cents


def validate_request_payload(data: dict) -> dict:
    """Validate raw intake data. Returns cleaned values or raises ValidationError."""
    errors: dict[str, str] = {}
    cleaned: dict = {}

    request_type = str(data.get("request_type", "")).strip().lower()
    if request_type not in REQUEST_TYPES:
        errors["request_type"] = (
            f"Request type must be one of: {', '.join(REQUEST_TYPES)}."
        )
    else:
        cleaned["request_type"] = request_type
    request_type = cleaned.get("request_type", "")

    title = str(data.get("title", "")).strip()
    if not title:
        errors["title"] = "Title is required."
    elif len(title) > MAX_TITLE_LEN:
        errors["title"] = f"Title must be {MAX_TITLE_LEN} characters or fewer."
    else:
        cleaned["title"] = title

    cleaned["amount_cents"] = _parse_amount_cents(data.get("amount"), request_type, errors)

    cost_center = str(data.get("cost_center", "")).strip().upper()
    if not _COST_CENTER_RE.match(cost_center):
        errors["cost_center"] = (
            "Cost center must be 3-8 uppercase letters/digits (e.g. OPS410)."
        )
    else:
        cleaned["cost_center"] = cost_center

    justification = str(data.get("justification", "")).strip()
    if len(justification) < MIN_JUSTIFICATION_LEN:
        errors["justification"] = (
            f"Justification must be at least {MIN_JUSTIFICATION_LEN} characters."
        )
    elif len(justification) > MAX_JUSTIFICATION_LEN:
        errors["justification"] = (
            f"Justification must be {MAX_JUSTIFICATION_LEN} characters or fewer."
        )
    else:
        cleaned["justification"] = justification

    name = str(data.get("requester_name", "")).strip()
    if not name:
        errors["requester_name"] = "Requester name is required."
    elif len(name) > MAX_NAME_LEN:
        errors["requester_name"] = (
            f"Requester name must be {MAX_NAME_LEN} characters or fewer."
        )
    else:
        cleaned["requester_name"] = name

    email = normalize_email(data.get("requester_email"))
    if email is None:
        errors["requester_email"] = "A valid requester email is required."
    else:
        cleaned["requester_email"] = email

    if errors:
        raise ValidationError(errors)
    return cleaned


# -- audit trail --------------------------------------------------------------

def record_request_event(
    conn: sqlite3.Connection,
    request_id: int,
    event_type: str,
    actor: str,
    role: Optional[str] = None,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> int:
    """Insert an audit event and emit the structured log line. Returns event id."""
    created = _iso(now)
    detail_json = json.dumps(detail, sort_keys=True) if detail is not None else None
    cur = conn.execute(
        """
        INSERT INTO request_events
            (request_id, event_type, actor, role, from_state, to_state, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (request_id, event_type, actor, role, from_state, to_state, detail_json, created),
    )
    event_id = cur.lastrowid
    conn.commit()  # the audit trail is durable the moment it is recorded
    print(
        json.dumps(
            {
                "ts": created,
                "event": event_type,
                "event_id": event_id,
                "request_id": request_id,
                "actor": actor,
                "role": role,
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


# -- reads --------------------------------------------------------------------

def get_request_by_id(conn: sqlite3.Connection, request_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def get_request(conn: sqlite3.Connection, public_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM requests WHERE public_id = ?", (public_id,)
    ).fetchone()
    return dict(row) if row else None


def list_requests(
    conn: sqlite3.Connection, state: Optional[str] = None, limit: int = 50
) -> list[dict]:
    if state:
        rows = conn.execute(
            "SELECT * FROM requests WHERE state = ? ORDER BY id DESC LIMIT ?",
            (state, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def request_events(conn: sqlite3.Connection, request_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM request_events WHERE request_id = ? ORDER BY id ASC",
        (request_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def approval_chain_for(amount_cents: int, finance_threshold_cents: int) -> list[str]:
    """Build the approval chain for a request amount.

    Every request needs its manager. Requests over the finance threshold
    additionally need finance. Deterministic and pure — trivially testable.
    """
    chain = [ROLE_MANAGER]
    if amount_cents > finance_threshold_cents:
        chain.append(ROLE_FINANCE)
    return chain


# -- writes -------------------------------------------------------------------

def _set_state(
    conn: sqlite3.Connection,
    request: dict,
    to_state: str,
    actor: str,
    event_type: str,
    role: Optional[str] = None,
    detail: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> dict:
    from_state = request["state"]
    REQUEST_WORKFLOW.check(from_state, to_state)  # raises InvalidTransition
    timestamp = _iso(now)
    conn.execute(
        "UPDATE requests SET state = ?, updated_at = ? WHERE id = ?",
        (to_state, timestamp, request["id"]),
    )
    conn.commit()
    record_request_event(
        conn, request["id"], event_type, actor, role=role,
        from_state=from_state, to_state=to_state, detail=detail, now=now,
    )
    return get_request_by_id(conn, request["id"])


def _get_idempotency(
    conn: sqlite3.Connection, key: str, ttl_hours: int, now: datetime
) -> Optional[dict]:
    row = conn.execute(
        """SELECT request_id, response_status, response_body, created_at
           FROM request_idempotency_keys WHERE key = ?""",
        (key,),
    ).fetchone()
    if row is None:
        return None
    created = datetime.fromisoformat(row["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if now - created > timedelta(hours=ttl_hours):
        conn.execute("DELETE FROM request_idempotency_keys WHERE key = ?", (key,))
        conn.commit()
        return None
    return {
        "request_id": row["request_id"],
        "status": row["response_status"],
        "body": json.loads(row["response_body"]),
        "replayed": True,
    }


def _store_idempotency(
    conn: sqlite3.Connection, key: str, request_id: int, status: int,
    body: dict, now: datetime,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO request_idempotency_keys
            (key, request_id, response_status, response_body, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (key, request_id, status, json.dumps(body, sort_keys=True), _iso(now)),
    )
    conn.commit()


def submit_request(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    idempotency_key: Optional[str] = None,
    actor: str = "public-form",
    now: Optional[datetime] = None,
    finance_threshold_cents: int = 100_000,
    idempotency_ttl_hours: int = 72,
) -> dict:
    """Create a request in ``draft`` state.

    Raises ValidationError when the payload is invalid (nothing is stored).
    A repeated idempotency key replays the original response without
    creating a duplicate business record.
    """
    now = _now(now)
    if idempotency_key:
        hit = _get_idempotency(conn, idempotency_key, idempotency_ttl_hours, now)
        if hit is not None:
            return hit

    cleaned = validate_request_payload(payload)  # raises; nothing stored
    timestamp = _iso(now)
    cur = conn.execute(
        """
        INSERT INTO requests
            (public_id, request_type, title, amount_cents, cost_center,
             justification, requester_name, requester_email,
             state, approval_chain, current_step, created_at, updated_at)
        VALUES ('pending', ?, ?, ?, ?, ?, ?, ?, 'draft', '[]', 0, ?, ?)
        """,
        (
            cleaned["request_type"], cleaned["title"], cleaned["amount_cents"],
            cleaned["cost_center"], cleaned["justification"],
            cleaned["requester_name"], cleaned["requester_email"],
            timestamp, timestamp,
        ),
    )
    request_id = cur.lastrowid
    public_id = f"RQ-{request_id:06d}"
    conn.execute("UPDATE requests SET public_id = ? WHERE id = ?", (public_id, request_id))
    conn.commit()
    request = get_request_by_id(conn, request_id)
    record_request_event(
        conn, request_id, "request.created", actor, to_state="draft",
        detail={"request_type": cleaned["request_type"]}, now=now,
    )
    body = {"public_id": public_id, "state": "draft"}
    if idempotency_key:
        _store_idempotency(conn, idempotency_key, request_id, 201, body, now)
    return {"request_id": request_id, "status": 201, "body": body, "replayed": False}


def _route_to_review(
    conn: sqlite3.Connection, request: dict, actor: str, now: datetime,
    finance_threshold_cents: int, sla_hours: int,
) -> dict:
    """submitted -> in_review: build the chain, arm the first step's SLA."""
    chain = approval_chain_for(request["amount_cents"], finance_threshold_cents)
    sla_due = _iso(now + timedelta(hours=sla_hours))
    conn.execute(
        """UPDATE requests
           SET approval_chain = ?, current_step = 0, sla_due_at = ?, updated_at = ?
           WHERE id = ?""",
        (json.dumps(chain), sla_due, _iso(now), request["id"]),
    )
    conn.commit()
    request = _set_state(
        conn, request, "in_review", actor, "request.routed",
        detail={"chain": chain, "sla_due_at": sla_due}, now=now,
    )
    return request


def submit_for_review(
    conn: sqlite3.Connection,
    public_id: str,
    actor: str,
    *,
    now: Optional[datetime] = None,
    finance_threshold_cents: int = 100_000,
    sla_hours: int = 48,
) -> dict:
    """Requester submits a draft: draft -> submitted -> in_review."""
    now = _now(now)
    request = get_request(conn, public_id)
    if request is None:
        raise KeyError(f"No request {public_id!r}.")
    request = _set_state(
        conn, request, "submitted", actor, "request.submitted",
        detail={"actor": actor}, now=now,
    )
    return _route_to_review(conn, request, actor, now, finance_threshold_cents, sla_hours)


def resubmit(
    conn: sqlite3.Connection,
    public_id: str,
    actor: str,
    *,
    now: Optional[datetime] = None,
    finance_threshold_cents: int = 100_000,
    sla_hours: int = 48,
) -> dict:
    """Requester resubmits after changes were requested: changes_requested -> submitted -> in_review."""
    now = _now(now)
    request = get_request(conn, public_id)
    if request is None:
        raise KeyError(f"No request {public_id!r}.")
    request = _set_state(
        conn, request, "submitted", actor, "request.resubmitted", now=now
    )
    return _route_to_review(conn, request, actor, now, finance_threshold_cents, sla_hours)


def _advance_step(
    conn: sqlite3.Connection, request: dict, actor: str, role: str,
    now: datetime, sla_hours: int,
) -> dict:
    """Record a non-final step approval: stay in_review, move to the next step."""
    chain = json.loads(request["approval_chain"])
    next_step = request["current_step"] + 1
    sla_due = _iso(now + timedelta(hours=sla_hours))
    conn.execute(
        """UPDATE requests SET current_step = ?, sla_due_at = ?, updated_at = ?
           WHERE id = ?""",
        (next_step, sla_due, _iso(now), request["id"]),
    )
    conn.commit()
    record_request_event(
        conn, request["id"], "approval.recorded", actor, role=role,
        from_state="in_review", to_state="in_review",
        detail={
            "decision": "approve",
            "step": request["current_step"],
            "next_step": next_step,
            "next_role": chain[next_step],
            "sla_due_at": sla_due,
        },
        now=now,
    )
    return get_request_by_id(conn, request["id"])


def record_decision(
    conn: sqlite3.Connection,
    public_id: str,
    *,
    decision: str,
    role: str,
    actor: str,
    now: Optional[datetime] = None,
    finance_threshold_cents: int = 100_000,
    sla_hours: int = 48,
) -> dict:
    """Record an approver's decision on the pending step.

    The decision is accepted only when ``role`` owns the current step of
    the request's approval chain (role enforcement in code). A final
    approval moves the request to ``approved``; ``reject`` and
    ``request_changes`` move it to the matching exception state.
    """
    now = _now(now)
    if decision not in DECISIONS:
        raise InvalidDecision(
            f"Decision must be one of: {', '.join(DECISIONS)}."
        )
    request = get_request(conn, public_id)
    if request is None:
        raise KeyError(f"No request {public_id!r}.")
    if request["state"] not in ("in_review", "escalated"):
        raise InvalidDecision(
            f"Request {public_id} is {request['state']!r}; "
            "decisions are only accepted in 'in_review' or 'escalated'."
        )
    chain = json.loads(request["approval_chain"])
    expected_role = chain[request["current_step"]]
    if role != expected_role:
        raise ApprovalRoleError(
            f"Step {request['current_step']} requires role {expected_role!r}, "
            f"not {role!r}."
        )
    is_final = request["current_step"] == len(chain) - 1
    detail = {
        "decision": decision,
        "step": request["current_step"],
        "role": role,
        "chain": chain,
    }
    if decision == "approve" and not is_final:
        return _advance_step(conn, request, actor, role, now, sla_hours)
    timestamp = _iso(now)
    if decision == "approve":
        conn.execute(
            "UPDATE requests SET decided_by = ?, decided_at = ? WHERE id = ?",
            (actor, timestamp, request["id"]),
        )
        conn.commit()
        return _set_state(
            conn, get_request_by_id(conn, request["id"]), "approved", actor,
            "approval.recorded", role=role,
            detail={**detail, "decided_by": actor}, now=now,
        )
    if decision == "reject":
        conn.execute(
            "UPDATE requests SET decided_by = ?, decided_at = ? WHERE id = ?",
            (actor, timestamp, request["id"]),
        )
        conn.commit()
        return _set_state(
            conn, get_request_by_id(conn, request["id"]), "rejected", actor,
            "request.rejected", role=role,
            detail={**detail, "decided_by": actor}, now=now,
        )
    # request_changes
    return _set_state(
        conn, request, "changes_requested", actor, "request.changes_requested",
        role=role, detail=detail, now=now,
    )


def fulfill(
    conn: sqlite3.Connection, public_id: str, actor: str,
    *, now: Optional[datetime] = None,
) -> dict:
    """Mark an approved request fulfilled: approved -> fulfilled."""
    request = get_request(conn, public_id)
    if request is None:
        raise KeyError(f"No request {public_id!r}.")
    return _set_state(
        conn, request, "fulfilled", actor, "request.fulfilled", now=now
    )


def cancel(
    conn: sqlite3.Connection, public_id: str, actor: str,
    *, now: Optional[datetime] = None,
) -> dict:
    """Withdraw a request: any non-terminal, non-fulfilled state -> cancelled."""
    request = get_request(conn, public_id)
    if request is None:
        raise KeyError(f"No request {public_id!r}.")
    if request["state"] in ("approved", "rejected", "fulfilled"):
        raise InvalidDecision(
            f"Request {public_id} is {request['state']!r} and cannot be cancelled."
        )
    return _set_state(
        conn, request, "cancelled", actor, "request.cancelled", now=now
    )


def sweep_sla(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
    sla_hours: int = 48,
) -> list[dict]:
    """Escalate every in_review request whose step SLA has breached.

    Escalated requests are rerouted to the director role with a fresh SLA
    deadline. Deterministic: pass ``now`` to freeze the clock in tests.
    Returns the escalated request records.
    """
    now = _now(now)
    rows = conn.execute(
        """SELECT * FROM requests
           WHERE state = 'in_review' AND sla_due_at IS NOT NULL
             AND sla_due_at <= ?
           ORDER BY id ASC""",
        (_iso(now),),
    ).fetchall()
    escalated = []
    for row in rows:
        request = dict(row)
        chain = [ROLE_DIRECTOR]
        sla_due = _iso(now + timedelta(hours=sla_hours))
        conn.execute(
            """UPDATE requests
               SET approval_chain = ?, current_step = 0, sla_due_at = ?, updated_at = ?
               WHERE id = ?""",
            (json.dumps(chain), sla_due, _iso(now), request["id"]),
        )
        conn.commit()
        fresh = get_request_by_id(conn, request["id"])
        fresh = _set_state(
            conn, fresh, "escalated", "system", "request.escalated",
            detail={
                "previous_chain": json.loads(request["approval_chain"]),
                "previous_step": request["current_step"],
                "sla_due_at": request["sla_due_at"],
                "new_sla_due_at": sla_due,
            },
            now=now,
        )
        escalated.append(fresh)
    return escalated


def request_stats(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None
) -> dict:
    """Dashboard aggregates, computed directly from the database."""
    now = _now(now)
    rows = conn.execute(
        "SELECT state, COUNT(*) AS c FROM requests GROUP BY state"
    ).fetchall()
    by_state = {r["state"]: r["c"] for r in rows}
    trows = conn.execute(
        "SELECT request_type, COUNT(*) AS c FROM requests GROUP BY request_type"
    ).fetchall()
    by_type = {r["request_type"]: r["c"] for r in trows}
    total = conn.execute("SELECT COUNT(*) AS c FROM requests").fetchone()["c"]
    breached = conn.execute(
        """SELECT COUNT(*) AS c FROM requests
           WHERE state = 'in_review' AND sla_due_at IS NOT NULL AND sla_due_at <= ?""",
        (_iso(now),),
    ).fetchone()["c"]
    escalated = conn.execute(
        "SELECT COUNT(*) AS c FROM requests WHERE state = 'escalated'"
    ).fetchone()["c"]
    return {
        "total": total,
        "by_state": by_state,
        "by_type": by_type,
        "sla_breached": breached,
        "escalated": escalated,
    }
