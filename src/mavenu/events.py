"""Structured event logging.

Every consequential action in the portfolio is recorded twice:
  1. As a row in the database (queryable audit trail).
  2. As a JSON line on stdout (structured operational log).

Nothing sensitive is ever logged: payloads are limited to identifiers and
state names, never raw contact details beyond what the business record holds.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from typing import Any, Optional

from .db import utcnow_iso


def record_event(
    conn: sqlite3.Connection,
    lead_id: int,
    event_type: str,
    actor: str,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> int:
    """Insert an audit event and emit the structured log line. Returns event id."""
    created = utcnow_iso()
    detail_json = json.dumps(detail, sort_keys=True) if detail is not None else None
    cur = conn.execute(
        """
        INSERT INTO lead_events (lead_id, event_type, actor, from_state, to_state, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (lead_id, event_type, actor, from_state, to_state, detail_json, created),
    )
    event_id = cur.lastrowid
    conn.commit()  # the audit trail is durable the moment it is recorded
    log_line = {
        "ts": created,
        "event": event_type,
        "event_id": event_id,
        "lead_id": lead_id,
        "actor": actor,
        "from_state": from_state,
        "to_state": to_state,
        "detail": detail or {},
    }
    print(json.dumps(log_line, sort_keys=True), file=sys.stdout, flush=True)
    return event_id


def log_system_event(event_type: str, detail: Optional[dict[str, Any]] = None) -> None:
    """Emit a structured log line for something with no lead attached (e.g. startup)."""
    print(
        json.dumps(
            {
                "ts": utcnow_iso(),
                "event": event_type,
                "actor": "system",
                "detail": detail or {},
            },
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
