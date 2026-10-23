"""Q10 — Webhook Integration Hub: versioned routing rules + dry-run.

Rules: ``event_type`` (+ JSON conditions) → ordered action list.
Actions:
  * ``log``      — append a structured log line + lineage note (no side effects
                   beyond observability).
  * ``transform``— project envelope fields into a derived envelope, stored in
                   ``webhook_derived``. Derived envelopes NEVER re-enter
                   routing (documented loop guard).
  * ``forward``  — enqueue a delivery to a stub endpoint
                   (see ``delivery.enqueue_delivery``).

``dry_run()`` returns exactly what ``apply_routes()`` would do, without
executing anything. The test suite asserts dry-run/real-run parity.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

from .db import utcnow_iso
from .webhooks import record_lineage, redacted_summary, utcnow

ACTION_TYPES = ("log", "transform", "forward")

CONDITION_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains",
                 "startswith", "exists", "in")


class RuleError(ValueError):
    """Raised for invalid rule definitions."""


# ---------------------------------------------------------------------------
# Condition evaluation (dotted paths over the envelope)
# ---------------------------------------------------------------------------
def _resolve_path(envelope: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """Resolve 'payload.lead.amount' style paths. Returns (found, value)."""
    current: Any = envelope
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def condition_matches(condition: Mapping[str, Any], envelope: Mapping[str, Any]) -> bool:
    """Evaluate one condition dict {"field", "op", "value"} against an envelope."""
    field = condition.get("field")
    op = condition.get("op")
    if not isinstance(field, str) or op not in CONDITION_OPS:
        raise RuleError(f"invalid condition: {condition!r}")
    found, value = _resolve_path(envelope, field)
    want = condition.get("value")
    if op == "exists":
        return found == bool(want)
    if not found:
        return False
    try:
        if op == "eq":
            return value == want
        if op == "ne":
            return value != want
        if op == "gt":
            return value > want
        if op == "gte":
            return value >= want
        if op == "lt":
            return value < want
        if op == "lte":
            return value <= want
        if op == "contains":
            return want in value
        if op == "startswith":
            return isinstance(value, str) and value.startswith(want)
        if op == "in":
            return value in want
    except TypeError:
        # Incomparable types never match — a condition must not crash routing.
        return False
    return False  # pragma: no cover


def rule_matches(rule: Mapping[str, Any], envelope: Mapping[str, Any]) -> bool:
    if not rule["enabled"]:
        return False
    if rule["event_type"] != "*" and rule["event_type"] != envelope.get("event_type"):
        return False
    conditions = json.loads(rule["conditions_json"])
    return all(condition_matches(c, envelope) for c in conditions)


# ---------------------------------------------------------------------------
# Rule CRUD (versioned)
# ---------------------------------------------------------------------------
def _validate_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        raise RuleError("actions must be a list")
    out = []
    for a in actions:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            raise RuleError(f"invalid action: {a!r}")
        if a["type"] == "forward" and not a.get("endpoint"):
            raise RuleError("forward actions require 'endpoint'")
        if a["type"] == "transform" and not isinstance(a.get("fields"), dict):
            raise RuleError("transform actions require a 'fields' object")
        out.append(dict(a))
    return out


def _validate_conditions(conditions: Any) -> list[dict[str, Any]]:
    if not isinstance(conditions, list):
        raise RuleError("conditions must be a list")
    for c in conditions:
        if (not isinstance(c, dict) or not isinstance(c.get("field"), str)
                or c.get("op") not in CONDITION_OPS):
            raise RuleError(f"invalid condition: {c!r}")
    return [dict(c) for c in conditions]


def create_rule(
    conn: sqlite3.Connection,
    *,
    name: str,
    event_type: str = "*",
    conditions: Optional[list[dict[str, Any]]] = None,
    actions: Optional[list[dict[str, Any]]] = None,
    priority: int = 100,
    enabled: bool = True,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if not name or not isinstance(name, str):
        raise RuleError("rule name must be a non-empty string")
    if not event_type or not isinstance(event_type, str):
        raise RuleError("event_type must be a non-empty string")
    conditions = _validate_conditions(conditions or [])
    actions = _validate_actions(actions or [])
    ts = (now or utcnow()).isoformat()
    try:
        cur = conn.execute(
            """
            INSERT INTO webhook_routes
                (name, version, event_type, conditions_json, actions_json,
                 priority, enabled, created_at, updated_at)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, event_type, json.dumps(conditions), json.dumps(actions),
             priority, 1 if enabled else 0, ts, ts),
        )
    except sqlite3.IntegrityError as exc:
        raise RuleError(f"rule name {name!r} already exists") from exc
    conn.commit()
    return get_rule(conn, cur.lastrowid)


def get_rule(conn: sqlite3.Connection, rule_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM webhook_routes WHERE id = ?", (rule_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown rule id {rule_id!r}")
    return dict(row)


def list_rules(
    conn: sqlite3.Connection, *, enabled: Optional[bool] = None
) -> list[dict[str, Any]]:
    if enabled is None:
        rows = conn.execute(
            "SELECT * FROM webhook_routes ORDER BY priority, id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM webhook_routes WHERE enabled = ? ORDER BY priority, id",
            (1 if enabled else 0,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_rule(
    conn: sqlite3.Connection, rule_id: int, *,
    now: Optional[datetime] = None, **fields: Any,
) -> dict[str, Any]:
    """Update a rule; any change bumps ``version`` (routing history stays explainable)."""
    rule = get_rule(conn, rule_id)
    allowed = {"name", "event_type", "conditions", "actions", "priority", "enabled"}
    unknown = set(fields) - allowed
    if unknown:
        raise RuleError(f"unknown rule fields: {sorted(unknown)}")
    values: dict[str, Any] = {}
    if "name" in fields:
        if not fields["name"] or not isinstance(fields["name"], str):
            raise RuleError("rule name must be a non-empty string")
        values["name"] = fields["name"]
    if "event_type" in fields:
        if not fields["event_type"] or not isinstance(fields["event_type"], str):
            raise RuleError("event_type must be a non-empty string")
        values["event_type"] = fields["event_type"]
    if "conditions" in fields:
        values["conditions_json"] = json.dumps(_validate_conditions(fields["conditions"]))
    if "actions" in fields:
        values["actions_json"] = json.dumps(_validate_actions(fields["actions"]))
    if "priority" in fields:
        values["priority"] = int(fields["priority"])
    if "enabled" in fields:
        values["enabled"] = 1 if fields["enabled"] else 0
    if not values:
        return rule
    values["version"] = rule["version"] + 1
    values["updated_at"] = (now or utcnow()).isoformat()
    sets = ", ".join(f"{k} = ?" for k in values)
    try:
        conn.execute(
            f"UPDATE webhook_routes SET {sets} WHERE id = ?",
            (*values.values(), rule_id),
        )
    except sqlite3.IntegrityError as exc:
        raise RuleError(f"rule name {fields.get('name')!r} already exists") from exc
    conn.commit()
    return get_rule(conn, rule_id)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    cur = conn.execute("DELETE FROM webhook_routes WHERE id = ?", (rule_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise KeyError(f"unknown rule id {rule_id!r}")


def match_rules(conn: sqlite3.Connection, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    """All enabled rules matching the envelope, ordered by (priority, id)."""
    return [r for r in list_rules(conn, enabled=True) if rule_matches(r, envelope)]


# ---------------------------------------------------------------------------
# Planning (dry-run) and execution
# ---------------------------------------------------------------------------
def plan_actions(
    conn: sqlite3.Connection, envelope: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Compute the ordered (rule, action) plan — no side effects.

    Shared by dry_run() and apply_routes(): parity between the two is the
    point, and the test suite pins it.
    """
    plan = []
    for rule in match_rules(conn, envelope):
        for action in json.loads(rule["actions_json"]):
            plan.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "rule_version": rule["version"],
                "action": action,
            })
    return plan


def dry_run(conn: sqlite3.Connection, envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Show what apply_routes() WOULD do — zero side effects."""
    plan = plan_actions(conn, envelope)
    matched = [r for r in match_rules(conn, envelope)]
    return {
        "event_id": envelope.get("event_id"),
        "event_type": envelope.get("event_type"),
        "matched_rules": [
            {"id": r["id"], "name": r["name"], "version": r["version"],
             "priority": r["priority"]}
            for r in matched
        ],
        "actions": [
            {"rule_id": p["rule_id"], "rule_name": p["rule_name"],
             "rule_version": p["rule_version"], "action": p["action"]}
            for p in plan
        ],
        "would_forward_to": sorted({
            p["action"]["endpoint"] for p in plan if p["action"]["type"] == "forward"
        }),
        "payload_summary": redacted_summary(envelope.get("payload")),
    }


def apply_routes(
    conn: sqlite3.Connection,
    envelope: Mapping[str, Any],
    endpoints: Mapping[str, Callable[..., Any]],
    *,
    actor: str = "router",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Execute the routing plan for one envelope.

    * ``log`` actions → structured stdout line + lineage note.
    * ``transform`` actions → derived envelope stored (never re-routed).
    * ``forward`` actions → delivery rows enqueued (idempotent).
    Lineage: received → routed → queued (forward) / delivered (log/transform only).
    """
    from . import delivery as _delivery
    event_id = envelope["event_id"]
    from_state = _delivery.event_current_state(conn, event_id)
    plan = plan_actions(conn, envelope)
    executed: list[dict[str, Any]] = []
    created = (now or utcnow()).isoformat()
    for step in plan:
        action = step["action"]
        atype = action["type"]
        if atype == "log":
            message = action.get("message", f"event {event_id} matched rule {step['rule_name']}")
            print(json.dumps({
                "ts": created, "service": "webhook-hub", "action": "log",
                "event_id": event_id, "rule": step["rule_name"],
                "message": str(message)[:200],
                "payload": redacted_summary(envelope.get("payload")),
            }, sort_keys=True), flush=True)
        elif atype == "transform":
            derived = _project_fields(action["fields"], envelope)
            conn.execute(
                """
                INSERT INTO webhook_derived
                    (event_id, rule_id, rule_version, derived_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, step["rule_id"], step["rule_version"],
                 json.dumps(derived, sort_keys=True), created),
            )
            conn.commit()
        elif atype == "forward":
            _delivery.enqueue_delivery(
                conn, event_id, action["endpoint"],
                rule_id=step["rule_id"], rule_version=step["rule_version"],
                now=now, actor=actor,
            )
        executed.append({
            "rule_id": step["rule_id"], "rule_name": step["rule_name"],
            "rule_version": step["rule_version"], "action": action,
        })
    record_lineage(
        conn, event_id, "routed", from_state=from_state, actor=actor,
        created=created,
        detail={"matched_rules": [e["rule_name"] for e in executed],
                "actions": len(executed),
                "payload": redacted_summary(envelope.get("payload"))},
    )
    forwarded = any(e["action"]["type"] == "forward" for e in executed)
    if forwarded:
        record_lineage(
            conn, event_id, "queued",
            from_state="routed", actor=actor, created=created,
            detail={"endpoints": sorted({
                e["action"]["endpoint"] for e in executed
                if e["action"]["type"] == "forward"})},
        )
    _delivery.settle_event(conn, event_id, actor=actor, now=now)
    return {
        "event_id": event_id,
        "matched_rules": [e["rule_name"] for e in executed],
        "executed": executed,
        "forwarded": forwarded,
    }


def _project_fields(fields: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Project envelope values into a derived envelope (transform action).

    ``fields`` maps output key → dotted source path or {"literal": value}.
    A transform never re-enters routing — this is the documented loop guard.
    """
    derived: dict[str, Any] = {
        "derived_from": envelope.get("event_id"),
        "derived_at": utcnow_iso(),
    }
    for out_key, spec in fields.items():
        if isinstance(spec, dict) and "literal" in spec:
            derived[out_key] = spec["literal"]
        elif isinstance(spec, str):
            found, value = _resolve_path(envelope, spec)
            derived[out_key] = value if found else None
        else:
            raise RuleError(f"invalid transform field spec for {out_key!r}: {spec!r}")
    return derived


# ---------------------------------------------------------------------------
# Demo seed rules (idempotent; for DEMO.md walkthroughs)
# ---------------------------------------------------------------------------
def seed_demo_rules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Create the three demo rules if they don't exist. Idempotent."""
    existing = {r["name"] for r in list_rules(conn)}
    made = []
    defs = [
        {
            "name": "form-leads-to-crm",
            "event_type": "lead.created",
            "conditions": [{"field": "source", "op": "eq", "value": "demo-form"}],
            "actions": [
                {"type": "log", "message": "new lead from demo form"},
                {"type": "forward", "endpoint": "stub:crm-sink"},
            ],
            "priority": 10,
        },
        {
            "name": "bookings-to-calendar",
            "event_type": "booking.created",
            "conditions": [],
            "actions": [
                {"type": "transform", "fields": {
                    "booking_ref": "payload.booking_ref",
                    "when": "payload.when",
                    "calendar": {"literal": "demo-calendar"},
                }},
                {"type": "forward", "endpoint": "stub:calendar-sink"},
            ],
            "priority": 20,
        },
        {
            "name": "high-value-leads-to-sheet",
            "event_type": "lead.created",
            "conditions": [{"field": "payload.amount", "op": "gte", "value": 1000}],
            "actions": [
                {"type": "log", "message": "high-value lead"},
                {"type": "forward", "endpoint": "stub:sheet-sink"},
            ],
            "priority": 30,
        },
    ]
    for d in defs:
        if d["name"] not in existing:
            made.append(create_rule(conn, **d))
    return made
