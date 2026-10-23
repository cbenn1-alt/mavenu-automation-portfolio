"""Project Q04 — Conversational Booking Agent: service layer.

Owns the conversation lifecycle over SQLite: start, per-turn processing,
slot persistence (masked), handoff escalation packages, and bookings.

Safety invariants enforced here (tested, see tests/test_booking_agent.py):

* Every agent AND caller turn is logged to ``booking_turns`` with a
  gapless ``turn_index`` and a per-turn decision log (state_before /
  state_after / action / confidence / masked extracted slots / reason).
* Caller text and slot values are MASKED before storage (phone digits,
  email addresses). Raw PII never reaches the database.
* Availability text comes ONLY from the ``BookingAdapter``. The agent
  never invents times.
* A ``booking_bookings`` row is written ONLY after
  ``BookingAdapter.create_booking()`` returns a reference. If the adapter
  raises, the conversation is preserved and handed off with reason
  ``booking_failed`` — zero bookings without adapter confirmation.
* Handoff reasons are a closed set; the escalation package carries the
  masked transcript + masked slots + reason to the human queue.

All timestamps are UTC ISO-8601; every mutating call accepts an
injectable ``now`` (frozen clock) so the logic is deterministic in tests.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Protocol

from .db import utcnow_iso
from .dialogue import (
    BOOKED,
    CONFIDENCE_THRESHOLD,
    CONFIRM,
    HANDOFF,
    MAX_TURNS,
    DialogueManager,
    DialoguePolicy,
    TurnResult,
    mask_slot_value,
    mask_text,
)
from .events import log_system_event


# ---------------------------------------------------------------------------
# Booking adapter seam (same interface pattern as P01's BookingAdapter).
# ---------------------------------------------------------------------------


class BookingError(Exception):
    """Raised when the booking integration fails. The conversation is kept."""


class BookingAdapter(Protocol):
    """Replaceable seam for the scheduling system.

    The demo adapter below is deterministic and writes to SQLite. A real
    adapter (Calendly, Housecall Pro, etc.) would implement this protocol;
    the dialogue manager never sees the difference — and never invents
    availability itself.
    """

    name: str

    def get_availability(self, window_hint: str) -> list[dict[str, str]]:
        """Return concrete bookable slots for the caller's preferred window.

        Each slot: {"slot_id": ..., "when": ...}. The agent may ONLY
        present these strings to the caller — never generated times.
        """
        ...

    def create_booking(self, payload: Mapping[str, Any]) -> str:
        """Create the appointment. Returns a booking reference."""
        ...


# Deterministic demo availability: the same window hint always yields the
# same slots, so tests and demos are reproducible. These are invented demo
# slots, not real technician schedules.
_DEMO_SLOTS = (
    {"slot_id": "AV-101", "when": "Monday morning"},
    {"slot_id": "AV-102", "when": "Monday afternoon"},
    {"slot_id": "AV-103", "when": "Tuesday morning"},
    {"slot_id": "AV-104", "when": "Tuesday afternoon"},
    {"slot_id": "AV-105", "when": "Wednesday morning"},
)


class DemoBookingAdapter:
    """Deterministic in-process stand-in for an external scheduling system.

    ``get_availability`` returns invented demo slots (rotated
    deterministically by the window hint so different windows show
    different slots). ``create_booking`` writes a ``booking_bookings`` row
    and returns a reference. ``fail=True`` simulates an integration outage:
    availability returns empty and ``create_booking`` raises, so the
    failure path (conversation preserved, handoff with reason
    ``booking_failed``) can be tested without any real external service.
    """

    name = "demo-booking-q04"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def get_availability(self, window_hint: str) -> list[dict[str, str]]:
        if self.fail:
            return []
        offset = sum(ord(c) for c in window_hint) % len(_DEMO_SLOTS)
        rotated = _DEMO_SLOTS[offset:] + _DEMO_SLOTS[:offset]
        return [dict(s) for s in rotated[:3]]

    def create_booking(self, payload: Mapping[str, Any]) -> str:
        if self.fail:
            raise BookingError("simulated booking integration failure")
        return f"QB-{payload['conversation_public_id']}-001"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

HANDOFF_REASONS = (
    "low_confidence",
    "max_turns",
    "suspicious_input",
    "contradictory_input",
    "slot_declined",
    "booking_failed",
)

RETENTION_DAYS = 90  # closed conversations lose transcript text after this


def _now_or(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _now_iso(now: Optional[datetime]) -> str:
    return _now_or(now).isoformat(timespec="seconds")


def _next_public_id(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) AS c FROM booking_conversations").fetchone()["c"]
    return f"CONV-{n + 1:06d}"


def _get_conversation(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM booking_conversations WHERE public_id = ?", (public_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown conversation {public_id!r}")
    return row


def _filled_slots(conn: sqlite3.Connection, conversation_id: int) -> dict[str, str]:
    rows = conn.execute(
        "SELECT slot_name, value_masked FROM booking_slots WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchall()
    return {r["slot_name"]: r["value_masked"] for r in rows}


def _log_turn(
    conn: sqlite3.Connection,
    conversation_id: int,
    role: str,
    text: str,
    confidence: Optional[float],
    decision: dict[str, Any],
    now: Optional[datetime],
) -> int:
    """Append one turn with a gapless turn_index. Returns the new turn_count."""
    row = conn.execute(
        "SELECT COALESCE(MAX(turn_index), -1) AS m FROM booking_turns WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    turn_index = row["m"] + 1
    masked = mask_text(text) if role == "caller" else text
    conn.execute(
        """
        INSERT INTO booking_turns
            (conversation_id, turn_index, role, text, confidence, decision_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            turn_index,
            role,
            masked,
            confidence,
            json.dumps(decision, sort_keys=True),
            _now_iso(now),
        ),
    )
    conn.execute(
        "UPDATE booking_conversations SET turn_count = turn_count + 1, updated_at = ? "
        "WHERE id = ?",
        (_now_iso(now), conversation_id),
    )
    return turn_index


def _store_slots(
    conn: sqlite3.Connection,
    conversation_id: int,
    extracted: Mapping[str, str],
    confidences: Mapping[str, float],
    now: Optional[datetime],
) -> None:
    for slot, value in extracted.items():
        if slot == "answer" or slot.startswith("offered_"):
            continue  # transient dialogue metadata, not a caller slot
        masked = mask_slot_value(slot, value)
        conn.execute(
            """
            INSERT INTO booking_slots
                (conversation_id, slot_name, value_masked, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (conversation_id, slot_name)
            DO UPDATE SET value_masked = excluded.value_masked,
                          confidence = excluded.confidence,
                          updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                slot,
                masked,
                confidences.get(slot, 0.0),
                _now_iso(now),
                _now_iso(now),
            ),
        )


def _set_state(
    conn: sqlite3.Connection,
    conversation_id: int,
    state: str,
    now: Optional[datetime],
    handoff_reason: Optional[str] = None,
    booking_ref: Optional[str] = None,
) -> None:
    conn.execute(
        """
        UPDATE booking_conversations
        SET state = ?, handoff_reason = COALESCE(?, handoff_reason),
            booking_ref = COALESCE(?, booking_ref), updated_at = ?
        WHERE id = ?
        """,
        (state, handoff_reason, booking_ref, _now_iso(now), conversation_id),
    )


def _escalate(
    conn: sqlite3.Connection,
    conversation: sqlite3.Row,
    reason: str,
    detail: str,
    now: Optional[datetime],
) -> None:
    """Write the handoff escalation package to the human queue."""
    transcript = _transcript_rows(conn, conversation["id"])
    slots = _filled_slots(conn, conversation["id"])
    conn.execute(
        """
        INSERT INTO booking_handoffs
            (conversation_id, reason, reason_detail, transcript_json, slots_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            conversation["id"],
            reason,
            detail,
            json.dumps(transcript),
            json.dumps(slots, sort_keys=True),
            _now_iso(now),
        ),
    )
    log_system_event(
        "booking_agent.handoff",
        {
            "conversation": conversation["public_id"],
            "reason": reason,
            "turns": len(transcript),
        },
    )


def _transcript_rows(conn: sqlite3.Connection, conversation_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT turn_index, role, text, confidence, decision_json, created_at
        FROM booking_turns WHERE conversation_id = ? ORDER BY turn_index
        """,
        (conversation_id,),
    ).fetchall()
    return [
        {
            "turn": r["turn_index"],
            "role": r["role"],
            "text": r["text"],
            "confidence": r["confidence"],
            "decision": json.loads(r["decision_json"]),
            "at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def start_conversation(
    conn: sqlite3.Connection,
    now: Optional[datetime] = None,
    policy: Optional[DialoguePolicy] = None,
) -> dict[str, Any]:
    """Open a conversation; the agent's first turn identifies it as automated."""
    manager = DialogueManager(policy)
    public_id = _next_public_id(conn)
    cur = conn.execute(
        """
        INSERT INTO booking_conversations (public_id, state, created_at, updated_at)
        VALUES (?, 'greeting', ?, ?)
        """,
        (public_id, _now_iso(now), _now_iso(now)),
    )
    conversation_id = cur.lastrowid
    greeting = manager.start()
    _log_turn(
        conn,
        conversation_id,
        "agent",
        greeting.agent_message,
        greeting.confidence,
        {
            "state_before": greeting.transition[0],
            "state_after": greeting.transition[1],
            "action": greeting.action,
            "confidence": greeting.confidence,
            "extracted": {},
            "reason": None,
        },
        now,
    )
    _set_state(conn, conversation_id, greeting.state, now)
    conn.commit()
    log_system_event("booking_agent.started", {"conversation": public_id})
    return {
        "public_id": public_id,
        "state": greeting.state,
        "agent_message": greeting.agent_message,
        "handoff": False,
    }


def send_turn(
    conn: sqlite3.Connection,
    public_id: str,
    text: str,
    now: Optional[datetime] = None,
    adapter: Optional[BookingAdapter] = None,
    policy: Optional[DialoguePolicy] = None,
) -> dict[str, Any]:
    """Process one caller utterance and return the agent's reply.

    Never raises for conversational reasons: low confidence, turn-cap,
    suspicious or contradictory input all become handoffs with a full
    escalation package. Raises KeyError for an unknown conversation and
    ValueError for a turn on a terminal conversation.
    """
    adapter = adapter or DemoBookingAdapter()
    manager = DialogueManager(policy)
    conversation = _get_conversation(conn, public_id)
    state = conversation["state"]
    if state in (BOOKED, HANDOFF):
        raise ValueError(f"conversation {public_id} is already {state}")

    text = (text or "").strip()
    if not text:
        text = "(no input)"

    turns_before = conversation["turn_count"]
    _log_turn(
        conn,
        conversation["id"],
        "caller",
        text,
        None,
        {"state_before": state, "state_after": state, "action": "receive",
         "confidence": None, "extracted": {}, "reason": None},
        now,
    )

    filled = _filled_slots(conn, conversation["id"])
    result: TurnResult = manager.step(
        text, state, filled, turn_count=turns_before
    )

    # Persist any newly extracted slots (masked at write time).
    if result.extracted:
        _store_slots(conn, conversation["id"], result.extracted,
                     _last_confidences(manager, text, state, filled), now)

    if result.action == "book":
        return _complete_booking(conn, conversation, result, adapter, now)

    if result.handoff:
        # Log the agent's handoff notice first so the escalation package
        # snapshots the complete transcript.
        _log_agent_turn(conn, conversation["id"], result, now)
        _escalate(conn, conversation, result.handoff_reason or "low_confidence",
                  result.agent_message, now)
        _set_state(conn, conversation["id"], HANDOFF, now,
                   handoff_reason=result.handoff_reason)
        conn.commit()
        return _turn_payload(public_id, result)

    if result.state == CONFIRM and result.action == "ask":
        # Entering confirm: fetch adapter availability and present ONLY it.
        slots = adapter.get_availability(filled.get("window", ""))
        if not slots:
            # No availability from the adapter -> handoff, never invent times.
            reason = "booking_failed"
            detail = "the booking system returned no availability; a human will follow up"
            result = manager._handoff(CONFIRM, reason, detail, 0.0)
            _log_agent_turn(conn, conversation["id"], result, now)
            _escalate(conn, conversation, reason, detail, now)
            _set_state(conn, conversation["id"], HANDOFF, now, handoff_reason=reason)
            conn.commit()
            return _turn_payload(public_id, result)
        offer = slots[0]
        result.agent_message = DialogueManager.confirm_prompt(offer["when"], offer["slot_id"])
        result.extracted = {"offered_slot_id": offer["slot_id"],
                            "offered_slot_when": offer["when"]}

    _set_state(conn, conversation["id"], result.state, now)
    _log_agent_turn(conn, conversation["id"], result, now)
    conn.commit()
    return _turn_payload(public_id, result)


def _last_confidences(
    manager: DialogueManager, text: str, state: str, filled: dict[str, str]
) -> dict[str, float]:
    """Re-run the policy to recover per-slot confidences for persistence.

    Deterministic: the policy is pure, so re-running is exact.
    """
    return manager.policy.interpret(text, state, filled).confidences


def _log_agent_turn(
    conn: sqlite3.Connection,
    conversation_id: int,
    result: TurnResult,
    now: Optional[datetime],
) -> None:
    _log_turn(
        conn,
        conversation_id,
        "agent",
        result.agent_message,
        result.confidence,
        {
            "state_before": result.transition[0],
            "state_after": result.transition[1],
            "action": result.action,
            "confidence": result.confidence,
            "extracted": {k: mask_slot_value(k, v) if k in
                           ("contact_name", "contact_phone") else v
                           for k, v in result.extracted.items()},
            "reason": result.handoff_reason,
        },
        now,
    )


def _complete_booking(
    conn: sqlite3.Connection,
    conversation: sqlite3.Row,
    result: TurnResult,
    adapter: BookingAdapter,
    now: Optional[datetime],
) -> dict[str, Any]:
    """Book via the adapter; write the booking row ONLY on confirmation."""
    filled = _filled_slots(conn, conversation["id"])
    payload = {
        "conversation_public_id": conversation["public_id"],
        "service": filled.get("service"),
        "location": filled.get("location"),
        "window": filled.get("window"),
        "contact_name": filled.get("contact_name"),
        "contact_phone": filled.get("contact_phone"),
    }
    try:
        ref = adapter.create_booking(payload)
    except BookingError as exc:
        reason = "booking_failed"
        detail = f"booking adapter '{adapter.name}' failed: {exc}"
        handoff_result = DialogueManager()._handoff(CONFIRM, reason, detail, 0.0)
        _log_agent_turn(conn, conversation["id"], handoff_result, now)
        _escalate(conn, conversation, reason, detail, now)
        _set_state(conn, conversation["id"], HANDOFF, now, handoff_reason=reason)
        conn.commit()
        return _turn_payload(conversation["public_id"], handoff_result)

    # Adapter confirmed -> and only now -> persist the booking.
    slot_when = filled.get("window", "")
    conn.execute(
        """
        INSERT INTO booking_bookings
            (conversation_id, booking_ref, adapter_name, slot_when, slots_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            conversation["id"],
            ref,
            adapter.name,
            slot_when,
            json.dumps(filled, sort_keys=True),
            _now_iso(now),
        ),
    )
    _set_state(conn, conversation["id"], BOOKED, now, booking_ref=ref)
    booked_result = TurnResult(
        state=BOOKED,
        agent_message=(
            f"You're booked! Your confirmation reference is {ref}. "
            "We'll see you then — reply here if anything changes and a "
            "person on our team will help."
        ),
        confidence=result.confidence,
        action="book",
        extracted=result.extracted,
        transition=(CONFIRM, BOOKED),
    )
    _log_agent_turn(conn, conversation["id"], booked_result, now)
    conn.commit()
    log_system_event("booking_agent.booked",
                     {"conversation": conversation["public_id"], "ref": ref})
    return _turn_payload(conversation["public_id"], booked_result)


def _turn_payload(public_id: str, result: TurnResult) -> dict[str, Any]:
    return {
        "public_id": public_id,
        "state": result.state,
        "agent_message": result.agent_message,
        "confidence": result.confidence,
        "handoff": result.handoff,
        "handoff_reason": result.handoff_reason,
        "extracted": result.extracted,
    }


def get_conversation(conn: sqlite3.Connection, public_id: str) -> dict[str, Any]:
    """Full transcript + slots + state for one conversation."""
    conversation = _get_conversation(conn, public_id)
    return {
        "public_id": conversation["public_id"],
        "state": conversation["state"],
        "turn_count": conversation["turn_count"],
        "handoff_reason": conversation["handoff_reason"],
        "booking_ref": conversation["booking_ref"],
        "slots": _filled_slots(conn, conversation["id"]),
        "turns": _transcript_rows(conn, conversation["id"]),
        "created_at": conversation["created_at"],
        "updated_at": conversation["updated_at"],
    }


def handoff_queue(conn: sqlite3.Connection, status: str = "open") -> list[dict[str, Any]]:
    """Escalation packages awaiting a human, newest first."""
    rows = conn.execute(
        """
        SELECT h.*, c.public_id AS conversation_public_id
        FROM booking_handoffs h
        JOIN booking_conversations c ON c.id = h.conversation_id
        WHERE h.status = ?
        ORDER BY h.id DESC
        """,
        (status,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "conversation_public_id": r["conversation_public_id"],
            "reason": r["reason"],
            "reason_detail": r["reason_detail"],
            "slots": json.loads(r["slots_json"]),
            "transcript": json.loads(r["transcript_json"]),
            "status": r["status"],
            "created_at": r["created_at"],
        })
    return out


def set_handoff_status(
    conn: sqlite3.Connection, handoff_id: int, status: str
) -> None:
    """Claim or resolve a handoff (human queue workflow)."""
    if status not in ("open", "claimed", "resolved"):
        raise ValueError(f"bad handoff status {status!r}")
    cur = conn.execute(
        "UPDATE booking_handoffs SET status = ? WHERE id = ?", (status, handoff_id)
    )
    if cur.rowcount == 0:
        raise KeyError(f"unknown handoff {handoff_id}")
    conn.commit()


def list_bookings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All adapter-confirmed bookings, newest first."""
    rows = conn.execute(
        """
        SELECT b.*, c.public_id AS conversation_public_id
        FROM booking_bookings b
        JOIN booking_conversations c ON c.id = b.conversation_id
        ORDER BY b.id DESC
        """
    ).fetchall()
    return [
        {
            "booking_ref": r["booking_ref"],
            "conversation_public_id": r["conversation_public_id"],
            "adapter_name": r["adapter_name"],
            "slot_when": r["slot_when"],
            "slots": json.loads(r["slots_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def purge_old_conversations(
    conn: sqlite3.Connection,
    now: Optional[datetime] = None,
    retention_days: int = RETENTION_DAYS,
) -> dict[str, int]:
    """Retention enforcement: drop transcript text + slot values for old
    closed conversations (state booked/handoff, updated_at older than the
    retention window). Booking references and handoff metadata are kept;
    only the conversational content is purged. Returns counts.
    """
    from datetime import timedelta

    cutoff = (_now_or(now) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    ids = [
        r["id"]
        for r in conn.execute(
            """
            SELECT id FROM booking_conversations
            WHERE state IN ('booked', 'handoff') AND updated_at < ?
            """,
            (cutoff,),
        ).fetchall()
    ]
    turns = slots = 0
    for cid in ids:
        cur = conn.execute("DELETE FROM booking_turns WHERE conversation_id = ?", (cid,))
        turns += cur.rowcount
        cur = conn.execute(
            "UPDATE booking_slots SET value_masked = '[purged]' "
            "WHERE conversation_id = ? AND value_masked != '[purged]'",
            (cid,),
        )
        slots += cur.rowcount
    conn.commit()
    log_system_event(
        "booking_agent.purged",
        {"conversations": len(ids), "turns": turns, "slots": slots},
    )
    return {"conversations": len(ids), "turns": turns, "slots": slots}
