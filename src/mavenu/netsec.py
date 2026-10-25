"""S01 — Network Security: defensive monitoring workflow as code.

Synthetic alert pipeline (synthetic events -> severity -> triage action per
the runbook) with a timed walkthrough harness, plus SQLite-backed incident
tickets and an alert-fatigue tuning log.

Lawful-lab scope only: every event is invented. Do not try this on networks
you don't own.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from typing import Any, Callable, Optional

from .db import utcnow_iso

# ---------------------------------------------------------------------------
# Alert catalog: synthetic alert types -> base severity + description
# ---------------------------------------------------------------------------
ALERT_TYPES: dict[str, dict[str, str]] = {
    "port_scan_detected": {
        "severity": "high",
        "description": "Multiple denied inbound probes from one WAN source "
                       "inside 60 seconds (lab attacker VM during validation).",
    },
    "failed_logins_burst": {
        "severity": "high",
        "description": "5+ failed SSH logins to a management interface in "
                       "10 minutes.",
    },
    "mgmt_login_failure": {
        "severity": "high",
        "description": "Any failed login on the management VLAN interface.",
    },
    "dns_tunneling_suspect": {
        "severity": "critical",
        "description": "Abnormal DNS query volume/shape from a single lab "
                       "host (simulated exfiltration pattern).",
    },
    "iot_outbound_tls_spike": {
        "severity": "medium",
        "description": "IoT segment TLS volume 3x above its 7-day lab "
                       "baseline.",
    },
    "rogue_dhcp_server": {
        "severity": "medium",
        "description": "DHCP offer seen from an address that is not the lab "
                       "gateway.",
    },
    "firmware_update_available": {
        "severity": "info",
        "description": "Vendor published a firmware update for a lab IoT "
                       "device.",
    },
    "wan_inbound_blocked": {
        "severity": "low",
        "description": "Unsolicited inbound WAN packet denied by "
                       "deny-wan-inbound (routine internet background noise).",
    },
    "guest_dhcp_churn": {
        "severity": "low",
        "description": "High DHCP lease churn on the guest VLAN "
                       "(phones joining/leaving).",
    },
}

SEVERITIES = ("info", "low", "medium", "high", "critical")

# ---------------------------------------------------------------------------
# Triage runbook as data: severity -> ordered steps with time boxes.
# Time boxes are the documented SLA for the walkthrough harness.
# ---------------------------------------------------------------------------
RUNBOOK: dict[str, list[dict[str, Any]]] = {
    "critical": [
        {"step": "acknowledge", "action": "Page on-call; open incident ticket.",
         "timebox_s": 300},
        {"step": "isolate", "action": "Quarantine the suspect host at the "
         "lab switch (port shutdown); preserve logs.",
         "timebox_s": 1800},
        {"step": "scope", "action": "List all other hosts the suspect talked "
         "to in the last 24h of lab logs.",
         "timebox_s": 3600},
        {"step": "resolve", "action": "Re-image from known-good lab snapshot; "
         "verify; close ticket with notes.",
         "timebox_s": 14400},
    ],
    "high": [
        {"step": "acknowledge", "action": "Open incident ticket; notify owner.",
         "timebox_s": 900},
        {"step": "verify", "action": "Confirm the alert is not lab test "
         "traffic (check validation schedule).",
         "timebox_s": 1800},
        {"step": "contain", "action": "Block the offending source at the "
         "firewall (temporary rule, documented).",
         "timebox_s": 3600},
        {"step": "resolve", "action": "Remove the temporary rule after the "
         "cause is fixed; document; close ticket.",
         "timebox_s": 28800},
    ],
    "medium": [
        {"step": "acknowledge", "action": "Open incident ticket.",
         "timebox_s": 7200},
        {"step": "investigate", "action": "Review the last 24h of relevant "
         "lab logs; decide contain vs. monitor.",
         "timebox_s": 28800},
        {"step": "resolve", "action": "Apply the fix or tune the alert; "
         "document; close ticket.",
         "timebox_s": 172800},
    ],
    "low": [
        {"step": "review", "action": "Batch-review at the daily log review; "
         "tune if it is noise.",
         "timebox_s": 86400},
    ],
    "info": [
        {"step": "note", "action": "Log it; act at the next maintenance "
         "window.",
         "timebox_s": 604800},
    ],
}


def severity_of(alert_type: str) -> str:
    """Base severity for a synthetic alert type (KeyError if unknown)."""
    return ALERT_TYPES[alert_type]["severity"]


def triage_steps(severity: str) -> list[dict[str, Any]]:
    return [dict(s) for s in RUNBOOK[severity]]


def synthetic_alert(alert_type: str, source_ip: str = "203.0.113.9",
                    rng: Optional[random.Random] = None) -> dict[str, Any]:
    """Build a synthetic alert event (invented data, never real traffic)."""
    r = rng or random.Random()
    severity = severity_of(alert_type)
    return {
        "alert_id": f"SYN-{r.randint(100000, 999999)}",
        "alert_type": alert_type,
        "severity": severity,
        "source_ip": source_ip,  # TEST-NET-3 documentation range
        "detail": ALERT_TYPES[alert_type]["description"],
        "occurred_at": utcnow_iso(),
    }


def triage(alert: dict[str, Any],
           tunings: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Apply alert-fatigue tuning, then attach the runbook steps.

    A tuning entry for the alert type marks it suppressed (with the logged
    reason) — the fatigue control — while the steps remain visible so the
    suppression is reviewable, not silent.
    """
    out = dict(alert)
    applied = [t for t in (tunings or [])
               if t.get("alert_type") == alert["alert_type"]]
    out["suppressed"] = bool(applied)
    out["suppression_reason"] = applied[0]["reason"] if applied else None
    out["steps"] = triage_steps(alert["severity"])
    return out


def walkthrough(triage_result: dict[str, Any],
                clock: Optional[Callable[[], float]] = None,
                step_work: Optional[Callable[[dict[str, Any]], None]] = None
                ) -> dict[str, Any]:
    """Timed runbook walkthrough harness.

    Executes each triage step (``step_work`` does the synthetic work; the
    default is a no-op) and checks every step finishes inside its documented
    time box. ``clock`` is injectable for deterministic tests; wall-clock is
    also recorded so the harness itself is measurably fast.
    """
    now = clock or time.monotonic
    wall_start = time.monotonic()
    step_results = []
    for step in triage_result["steps"]:
        start = now()
        if step_work is not None:
            step_work(step)
        elapsed = now() - start
        step_results.append({
            "step": step["step"],
            "action": step["action"],
            "timebox_s": step["timebox_s"],
            "elapsed_s": elapsed,
            "within_timebox": elapsed <= step["timebox_s"],
        })
    wall_elapsed = time.monotonic() - wall_start
    return {
        "alert_id": triage_result.get("alert_id"),
        "alert_type": triage_result.get("alert_type"),
        "severity": triage_result.get("severity"),
        "suppressed": triage_result.get("suppressed", False),
        "steps": step_results,
        "all_within_timebox": all(s["within_timebox"] for s in step_results),
        "wall_elapsed_s": wall_elapsed,
    }


# ---------------------------------------------------------------------------
# Incident tickets (SQLite)
# ---------------------------------------------------------------------------
INCIDENT_STATES = ("open", "triaged", "contained", "resolved", "closed")
INCIDENT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("triaged",),
    "triaged": ("contained",),
    "contained": ("resolved",),
    "resolved": ("closed", "open"),   # closed, or reopened for follow-up
    "closed": ("open",),              # reopen
}


class IncidentError(ValueError):
    pass


def create_incident(conn: sqlite3.Connection, title: str, severity: str,
                    source_alert_type: Optional[str] = None,
                    actor: str = "lab-operator") -> int:
    if severity not in SEVERITIES:
        raise IncidentError(f"unknown severity {severity!r}")
    if not title.strip():
        raise IncidentError("title is required")
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO netsec_incidents
           (title, severity, status, source_alert_type, actor, created_at, updated_at)
           VALUES (?, ?, 'open', ?, ?, ?, ?)""",
        (title.strip(), severity, source_alert_type, actor, created, created),
    )
    incident_id = cur.lastrowid
    conn.execute(
        """INSERT INTO netsec_incident_events
           (incident_id, event_type, actor, from_status, to_status, detail, created_at)
           VALUES (?, 'created', ?, NULL, 'open', ?, ?)""",
        (incident_id, actor,
         json.dumps({"title": title.strip(), "severity": severity}), created),
    )
    conn.commit()
    return incident_id


def transition_incident(conn: sqlite3.Connection, incident_id: int,
                        to_status: str, actor: str = "lab-operator",
                        note: str = "") -> None:
    if to_status not in INCIDENT_STATES:
        raise IncidentError(f"unknown status {to_status!r}")
    row = conn.execute(
        "SELECT status FROM netsec_incidents WHERE id = ?", (incident_id,)
    ).fetchone()
    if row is None:
        raise IncidentError(f"incident {incident_id} not found")
    from_status = row["status"]
    allowed = INCIDENT_TRANSITIONS[from_status]
    if to_status not in allowed:
        raise IncidentError(
            f"illegal transition {from_status!r} -> {to_status!r}; "
            f"allowed: {list(allowed)}")
    now = utcnow_iso()
    conn.execute(
        "UPDATE netsec_incidents SET status = ?, updated_at = ? WHERE id = ?",
        (to_status, now, incident_id),
    )
    conn.execute(
        """INSERT INTO netsec_incident_events
           (incident_id, event_type, actor, from_status, to_status, detail, created_at)
           VALUES (?, 'transition', ?, ?, ?, ?, ?)""",
        (incident_id, actor, from_status, to_status,
         json.dumps({"note": note}) if note else None, now),
    )
    conn.commit()


def get_incident(conn: sqlite3.Connection, incident_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM netsec_incidents WHERE id = ?", (incident_id,)
    ).fetchone()
    if row is None:
        raise IncidentError(f"incident {incident_id} not found")
    incident = dict(row)
    incident["timeline"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM netsec_incident_events WHERE incident_id = ? "
            "ORDER BY id", (incident_id,)
        ).fetchall()
    ]
    return incident


def list_incidents(conn: sqlite3.Connection,
                   status: Optional[str] = None) -> list[dict[str, Any]]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM netsec_incidents ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM netsec_incidents WHERE status = ? ORDER BY id DESC",
            (status,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Alert log + alert-fatigue tuning log (SQLite)
# ---------------------------------------------------------------------------
def record_alert(conn: sqlite3.Connection, alert: dict[str, Any],
                 triage_result: dict[str, Any]) -> int:
    """Store an alert; idempotent on the natural key ``alert_id`` so a
    repeated deterministic seed is a no-op instead of an error."""
    existing = conn.execute(
        "SELECT id FROM netsec_alerts WHERE alert_id = ?",
        (alert["alert_id"],)).fetchone()
    if existing is not None:
        return existing["id"]
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO netsec_alerts
           (alert_id, alert_type, severity, source_ip, suppressed, detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (alert["alert_id"], alert["alert_type"], alert["severity"],
         alert["source_ip"], int(bool(triage_result.get("suppressed"))),
         json.dumps({"description": alert["detail"],
                     "steps": [s["step"] for s in triage_result["steps"]]}),
         created),
    )
    conn.commit()
    return cur.lastrowid


def log_tuning(conn: sqlite3.Connection, alert_type: str, action: str,
               reason: str, actor: str = "lab-operator") -> int:
    """Record an alert-fatigue decision (what was silenced/throttled and why)."""
    if alert_type not in ALERT_TYPES:
        raise IncidentError(f"unknown alert type {alert_type!r}")
    if action not in ("silence", "threshold", "de-escalate"):
        raise IncidentError(f"unknown tuning action {action!r}")
    if not reason.strip():
        raise IncidentError("a tuning decision must document its reason")
    cur = conn.execute(
        """INSERT INTO netsec_tuning (alert_type, action, reason, actor, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (alert_type, action, reason.strip(), actor, utcnow_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_tuning(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM netsec_tuning ORDER BY id").fetchall()]


def save_ruleset_version(conn: sqlite3.Connection, actor: str = "lab-operator",
                         version: Optional[str] = None) -> int:
    """Version the firewall ruleset as data (config rollback support)."""
    from . import firewall as fw
    cur = conn.execute(
        """INSERT INTO netsec_rule_versions (version, ruleset_json, actor, created_at)
           VALUES (?, ?, ?, ?)""",
        (version or fw.RULESET_VERSION,
         json.dumps([r.as_dict() for r in fw.RULESET]),
         actor, utcnow_iso()),
    )
    conn.commit()
    return cur.lastrowid


def seed_demo(conn: sqlite3.Connection, seed: int = 7) -> dict[str, int]:
    """Seed synthetic demo data: tuning log, alerts, one incident lifecycle.

    Idempotent on the tuning seed rows (natural key alert_type+action).
    """
    rng = random.Random(seed)
    base_tunings = [
        ("wan_inbound_blocked", "threshold",
         "Routine internet background noise: aggregate at >50/hr instead of "
         "paging; the deny is expected and logged."),
        ("guest_dhcp_churn", "silence",
         "Phones joining/leaving guest Wi-Fi is normal; reviewed in the daily "
         "batch instead of alerting."),
        ("firmware_update_available", "de-escalate",
         "Informational only; handled at the monthly maintenance window."),
    ]
    tuning_rows = 0
    for alert_type, action, reason in base_tunings:
        exists = conn.execute(
            "SELECT 1 FROM netsec_tuning WHERE alert_type = ? AND action = ?",
            (alert_type, action)).fetchone()
        if not exists:
            log_tuning(conn, alert_type, action, reason, actor="seed")
            tuning_rows += 1
    tunings = list_tuning(conn)
    alert_rows = 0
    for alert_type in ("port_scan_detected", "wan_inbound_blocked",
                       "iot_outbound_tls_spike"):
        alert = synthetic_alert(alert_type, rng=rng)
        triaged = triage(alert, tunings)
        record_alert(conn, alert, triaged)
        alert_rows += 1
    incident_id = create_incident(
        conn, "Simulated port scan from lab attacker VM", "high",
        source_alert_type="port_scan_detected", actor="seed")
    save_ruleset_version(conn, actor="seed")
    return {"tuning": tuning_rows, "alerts": alert_rows,
            "incidents": 1, "incident_id": incident_id,
            "rule_versions": 1}
