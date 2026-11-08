"""Project P05 — Automation Reliability & Governance Center.

Health checks, retry policies, alerting, runbooks, and incidents over the
portfolio's own (synthetic) operational data.

Honesty note: probes run against this local demo system only. Alerts are
**recorded in the database and never sent anywhere** — there is no send
path in P05 by architecture (no email, webhook, SMS, or pager call
exists in this module). Retry jobs execute no real work: ``attempt_job``
records the outcome the *caller* reports, and computes the next delay
from the policy. Everything here is a governance *mechanism* demo on
synthetic data, not a record of real operations.

Grounding: retry backoff and dead-letter routing follow Q10
(``delivery.py``: exponential backoff with a cap, dead-letter after N
attempts); alert severity routing and the timed walkthrough harness
follow S01 (``netsec.py``); the audit event table follows the Q05/P04
event shape; incident lifecycle is P05's own state machine in
``workflow.py`` (``INCIDENT_WORKFLOW``).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from .db import MIGRATIONS_DIR, applied_migrations, utcnow_iso
from .workflow import ALERT_WORKFLOW, INCIDENT_WORKFLOW, InvalidTransition


class GovError(ValueError):
    """Raised for any invalid governance input or illegal state change."""


SEVERITIES = ("critical", "high", "medium", "low", "info")
CHECK_KINDS = ("liveness", "readiness")
CHECK_STATUSES = ("pass", "degraded", "fail")
JOB_STATUSES = ("pending", "scheduled", "retrying", "succeeded", "dead_lettered")
ALERT_STATUSES = ("open", "acked", "resolved")
OPERATORS = ("gt", "gte", "lt", "lte", "eq", "ne")

_NAME_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,64}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,64}$")

# Queue-depth probe allow-list: table -> {column, allowed values}.
# Identifiers come only from here; anything else is rejected before SQL.
_QUEUE_TABLES: dict[str, dict[str, Any]] = {
    "leads": {
        "column": "state",
        "values": {"received", "qualified", "routed", "booked",
                   "needs_review", "rejected", "cancelled"},
    },
    "missed_calls": {
        "column": "state",
        "values": {"pending", "attempted", "connected", "booked", "lost"},
    },
    "estimates": {
        "column": "state",
        "values": {"draft", "sent", "viewed", "followed_up",
                   "accepted", "declined", "expired"},
    },
    "docintel_documents": {
        "column": "state",
        "values": {"ingested", "needs_review", "accepted", "rejected"},
    },
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _now(now: Optional[str] = None) -> str:
    return now if now is not None else utcnow_iso()


def _check_actor(actor: str) -> str:
    actor = (actor or "system").strip() or "system"
    if len(actor) > 64:
        raise GovError("actor must be at most 64 characters")
    return actor


def _check_name(name: str, field: str = "name") -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise GovError(
            f"{field} must be 1-64 characters of letters, digits, spaces, "
            "underscores, or hyphens")
    return name


def _parse_iso(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise GovError(f"{field} must be an ISO-8601 timestamp")


def _record_event(conn: sqlite3.Connection, entity_type: str, entity_id: int,
                  event_type: str, actor: str, detail: Optional[dict] = None) -> int:
    cur = conn.execute(
        """INSERT INTO gov_events
           (entity_type, entity_id, event_type, actor, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, event_type, actor,
         json.dumps(detail or {}, sort_keys=True), utcnow_iso()),
    )
    return cur.lastrowid


def _as_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _decode_json(row: dict, *fields: str) -> dict:
    out = dict(row)
    for f in fields:
        if f in out and isinstance(out[f], str):
            out[f] = json.loads(out[f])
    return out


# ---------------------------------------------------------------------------
# Probes
#
# A probe returns (value, detail). ``value`` is a numeric "badness"
# measure: higher is worse. The check's warn/fail thresholds turn it
# into pass / degraded / fail. Boolean probes return 0 (good) or 1 (bad)
# with warn = fail = 0.
# ---------------------------------------------------------------------------
def _probe_db_reachable(conn: sqlite3.Connection, params: dict) -> tuple[Any, dict]:
    try:
        row = conn.execute("SELECT 1 AS ok").fetchone()
        tables = conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type = 'table'"
        ).fetchone()["c"]
    except sqlite3.Error as exc:
        return 1, {"error": str(exc)}
    ok = row is not None and row["ok"] == 1 and tables > 0
    return (0 if ok else 1), {"tables": tables}


def _probe_migrations_current(conn: sqlite3.Connection, params: dict) -> tuple[Any, dict]:
    applied = applied_migrations(conn)
    files = sorted(
        f for f in os.listdir(MIGRATIONS_DIR)
        if f.endswith(".sql") and not f.endswith(".down.sql")
    )
    pending = [f for f in files if f not in applied]
    return len(pending), {"pending": pending, "applied": len(applied)}


def _probe_queue_depth(conn: sqlite3.Connection, params: dict) -> tuple[Any, dict]:
    table = params.get("table")
    value = params.get("value")
    if table not in _QUEUE_TABLES:
        raise GovError(f"queue_depth: unknown table {table!r}")
    meta = _QUEUE_TABLES[table]
    if value not in meta["values"]:
        raise GovError(f"queue_depth: unknown value {value!r} for {table}")
    column = meta["column"]
    # Identifiers come only from the allow-list above; the value is bound.
    count = conn.execute(
        f"SELECT COUNT(*) AS c FROM {table} WHERE {column} = ?",
        (value,),
    ).fetchone()["c"]
    return count, {"table": table, "column": column, "value": value, "count": count}


def _probe_storage_tmp(conn: sqlite3.Connection, params: dict,
                       disk_usage_fn: Optional[Callable] = None) -> tuple[Any, dict]:
    path = params.get("path", "/tmp")
    usage = (disk_usage_fn or shutil.disk_usage)(path)
    total = usage.total or 1
    used_pct = round(100.0 * (total - usage.free) / total, 1)
    return used_pct, {"path": path, "used_pct": used_pct,
                      "free_bytes": usage.free, "total_bytes": total}


def _probe_app_smoke(conn: sqlite3.Connection, params: dict) -> tuple[Any, dict]:
    try:
        applied = applied_migrations(conn)
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    except sqlite3.Error as exc:
        return 1, {"error": str(exc)}
    missing = [t for t in ("gov_checks", "gov_policies", "gov_rules")
               if t not in tables]
    ok = bool(applied) and not missing
    return (0 if ok else 1), {"migrations_applied": len(applied),
                              "missing_tables": missing}


_PROBES: dict[str, Callable] = {
    "db_reachable": _probe_db_reachable,
    "migrations_current": _probe_migrations_current,
    "queue_depth": _probe_queue_depth,
    "storage_tmp": _probe_storage_tmp,
    "app_smoke": _probe_app_smoke,
}


def _evaluate_value(value: Any, warn: float, fail: float) -> str:
    """Turn a probe's numeric badness value into pass / degraded / fail."""
    if value is None:
        return "fail"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "fail"
    if number <= warn:
        return "pass"
    if number <= fail:
        return "degraded"
    return "fail"


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
def create_check(conn: sqlite3.Connection, name: str, subsystem: str,
                 kind: str, probe: str, params: Optional[dict] = None,
                 warn_threshold: float = 0, fail_threshold: float = 0,
                 description: str = "", actor: str = "system") -> dict:
    name = _check_name(name)
    actor = _check_actor(actor)
    if subsystem not in ("db", "queue", "storage", "app"):
        raise GovError(f"unknown subsystem {subsystem!r}")
    if kind not in CHECK_KINDS:
        raise GovError(f"unknown check kind {kind!r}")
    if probe not in _PROBES:
        raise GovError(f"unknown probe {probe!r}")
    if not isinstance(params, (dict, type(None))):
        raise GovError("params must be a JSON object")
    params = params or {}
    try:
        warn = float(warn_threshold)
        fail = float(fail_threshold)
    except (TypeError, ValueError):
        raise GovError("thresholds must be numbers")
    if warn > fail:
        raise GovError("warn_threshold must not exceed fail_threshold")
    if probe == "queue_depth":
        # Validate the allow-listed target now, not at first run.
        table = params.get("table")
        value = params.get("value")
        if table not in _QUEUE_TABLES or value not in _QUEUE_TABLES[table]["values"]:
            raise GovError(f"queue_depth: unknown table/value {table!r}/{value!r}")
    created = utcnow_iso()
    try:
        cur = conn.execute(
            """INSERT INTO gov_checks
               (name, subsystem, kind, probe, params_json,
                warn_threshold, fail_threshold, description, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, subsystem, kind, probe, json.dumps(params, sort_keys=True),
             warn, fail, description.strip(), actor, created),
        )
    except sqlite3.IntegrityError:
        raise GovError(f"check {name!r} already exists")
    check_id = cur.lastrowid
    _record_event(conn, "check", check_id, "check.created", actor,
                  {"name": name, "probe": probe})
    conn.commit()
    return get_check(conn, check_id)


def get_check(conn: sqlite3.Connection, check_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_checks WHERE id = ?", (check_id,)).fetchone()
    if row is None:
        raise GovError(f"No check {check_id}")
    return _decode_json(_as_dict(row), "params_json")


def get_check_by_name(conn: sqlite3.Connection, name: str) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_checks WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise GovError(f"No check {name!r}")
    return _decode_json(_as_dict(row), "params_json")


def list_checks(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM gov_checks ORDER BY id").fetchall()
    return [_decode_json(_as_dict(r), "params_json") for r in rows]


def _latest_run(conn: sqlite3.Connection, check_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM gov_check_runs WHERE check_id = ? ORDER BY id DESC LIMIT 1",
        (check_id,)).fetchone()
    if row is None:
        return None
    return _decode_json(_as_dict(row), "value_json", "detail_json")


def run_check(conn: sqlite3.Connection, check_id: int, actor: str = "system",
              now: Optional[str] = None,
              disk_usage_fn: Optional[Callable] = None) -> dict:
    """Execute one check's probe, record the run, evaluate alert rules.

    Returns the run dict with an ``alerts`` key listing the alert ids
    fired (or dedup-bumped) by this run. ``disk_usage_fn`` is injectable
    for deterministic tests of the storage probe.
    """
    actor = _check_actor(actor)
    check = get_check(conn, check_id)
    probe_fn = _PROBES[check["probe"]]
    started = time.monotonic()
    if check["probe"] == "storage_tmp":
        value, detail = probe_fn(conn, check["params_json"], disk_usage_fn)
    else:
        value, detail = probe_fn(conn, check["params_json"])
    duration_ms = max(0, int(round((time.monotonic() - started) * 1000)))
    status = _evaluate_value(value, check["warn_threshold"], check["fail_threshold"])
    created = _now(now)
    detail = dict(detail)
    detail["value"] = value
    cur = conn.execute(
        """INSERT INTO gov_check_runs
           (check_id, status, value_json, detail_json, duration_ms, actor, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (check_id, status, json.dumps(value), json.dumps(detail, sort_keys=True),
         duration_ms, actor, created),
    )
    run_id = cur.lastrowid
    _record_event(conn, "run", run_id, "run.recorded", actor,
                  {"check_id": check_id, "status": status, "value": value})
    conn.commit()
    run = get_check_run(conn, run_id)
    fired = evaluate_rules(conn, run, now=created)
    run["alerts"] = fired
    return run


def get_check_run(conn: sqlite3.Connection, run_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_check_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise GovError(f"No check run {run_id}")
    return _decode_json(_as_dict(row), "value_json", "detail_json")


def list_check_runs(conn: sqlite3.Connection, check_id: Optional[int] = None,
                    limit: int = 100) -> list[dict]:
    if check_id is None:
        rows = conn.execute(
            "SELECT * FROM gov_check_runs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM gov_check_runs WHERE check_id = ? ORDER BY id DESC LIMIT ?",
            (check_id, limit)).fetchall()
    return [_decode_json(_as_dict(r), "value_json", "detail_json") for r in rows]


def status_summary(conn: sqlite3.Connection) -> dict:
    """Overall health from the latest run of every check.

    overall is fail if any latest run is fail, degraded if any is
    degraded, pass if every check has a passing latest run, and unknown
    if any check has never run.
    """
    checks = list_checks(conn)
    entries = []
    worst = "pass"
    for check in checks:
        latest = _latest_run(conn, check["id"])
        status = latest["status"] if latest else "unknown"
        entries.append({"check": check, "latest_run": latest, "status": status})
        if status == "fail":
            worst = "fail"
        elif status == "degraded" and worst != "fail":
            worst = "degraded"
        elif status == "unknown" and worst == "pass":
            worst = "unknown"
    open_alerts = conn.execute(
        "SELECT COUNT(*) AS c FROM gov_alerts WHERE status IN ('open', 'acked')"
    ).fetchone()["c"]
    open_incidents = conn.execute(
        "SELECT COUNT(*) AS c FROM gov_incidents "
        "WHERE status IN ('open', 'triaged', 'mitigating')"
    ).fetchone()["c"]
    return {"overall": worst, "checks": entries,
            "open_alerts": open_alerts, "open_incidents": open_incidents}


# ---------------------------------------------------------------------------
# Retry policies (as data, versioned)
# ---------------------------------------------------------------------------
def _validate_policy_fields(max_attempts: int, backoff_base_s: float,
                            backoff_cap_s: float, jitter_max_s: float,
                            dead_letter_after: int) -> None:
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) \
            or not 1 <= max_attempts <= 10:
        raise GovError("max_attempts must be an integer from 1 to 10")
    for field, value in (("backoff_base_s", backoff_base_s),
                         ("backoff_cap_s", backoff_cap_s),
                         ("jitter_max_s", jitter_max_s)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise GovError(f"{field} must be a non-negative number")
    if backoff_base_s <= 0:
        raise GovError("backoff_base_s must be greater than 0")
    if backoff_cap_s < backoff_base_s:
        raise GovError("backoff_cap_s must not be less than backoff_base_s")
    if not isinstance(dead_letter_after, int) or isinstance(dead_letter_after, bool) \
            or dead_letter_after < 1:
        raise GovError("dead_letter_after must be an integer of at least 1")


def create_policy(conn: sqlite3.Connection, name: str, max_attempts: int = 5,
                  backoff_base_s: float = 30, backoff_cap_s: float = 3600,
                  jitter_max_s: float = 0, dead_letter_after: Optional[int] = None,
                  description: str = "", actor: str = "system") -> dict:
    name = _check_name(name)
    actor = _check_actor(actor)
    if dead_letter_after is None:
        dead_letter_after = max_attempts
    _validate_policy_fields(max_attempts, backoff_base_s, backoff_cap_s,
                            jitter_max_s, dead_letter_after)
    created = utcnow_iso()
    try:
        cur = conn.execute(
            """INSERT INTO gov_policies
               (name, version, status, max_attempts, backoff_base_s,
                backoff_cap_s, jitter_max_s, dead_letter_after,
                description, created_by, created_at)
               VALUES (?, 1, 'current', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, max_attempts, backoff_base_s, backoff_cap_s, jitter_max_s,
             dead_letter_after, description.strip(), actor, created),
        )
    except sqlite3.IntegrityError:
        raise GovError(f"policy {name!r} already exists")
    policy_id = cur.lastrowid
    _record_event(conn, "policy", policy_id, "policy.created", actor,
                  {"name": name, "version": 1})
    conn.commit()
    return get_policy(conn, policy_id)


def get_policy(conn: sqlite3.Connection, policy_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_policies WHERE id = ?", (policy_id,)).fetchone()
    if row is None:
        raise GovError(f"No policy {policy_id}")
    return _as_dict(row)


def get_policy_by_name(conn: sqlite3.Connection, name: str,
                       version: Optional[int] = None) -> dict:
    if version is None:
        row = conn.execute(
            "SELECT * FROM gov_policies WHERE name = ? AND status = 'current'",
            (name,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM gov_policies WHERE name = ? AND version = ?",
            (name, version)).fetchone()
    if row is None:
        raise GovError(f"No policy {name!r}")
    return _as_dict(row)


def list_policies(conn: sqlite3.Connection,
                  include_superseded: bool = False) -> list[dict]:
    if include_superseded:
        rows = conn.execute(
            "SELECT * FROM gov_policies ORDER BY name, version").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM gov_policies WHERE status = 'current' ORDER BY name"
        ).fetchall()
    return [_as_dict(r) for r in rows]


def supersede_policy(conn: sqlite3.Connection, name: str, max_attempts: int,
                     backoff_base_s: float, backoff_cap_s: float,
                     jitter_max_s: float = 0,
                     dead_letter_after: Optional[int] = None,
                     description: str = "", actor: str = "system") -> dict:
    current = get_policy_by_name(conn, name)
    if dead_letter_after is None:
        dead_letter_after = max_attempts
    _validate_policy_fields(max_attempts, backoff_base_s, backoff_cap_s,
                            jitter_max_s, dead_letter_after)
    actor = _check_actor(actor)
    new_version = current["version"] + 1
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO gov_policies
           (name, version, status, max_attempts, backoff_base_s,
            backoff_cap_s, jitter_max_s, dead_letter_after,
            description, created_by, created_at)
           VALUES (?, ?, 'current', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, new_version, max_attempts, backoff_base_s, backoff_cap_s,
         jitter_max_s, dead_letter_after, description.strip(), actor, created),
    )
    new_id = cur.lastrowid
    conn.execute(
        "UPDATE gov_policies SET status = 'superseded', superseded_by = ? "
        "WHERE id = ?", (new_id, current["id"]))
    _record_event(conn, "policy", new_id, "policy.superseded", actor,
                  {"name": name, "version": new_version,
                   "supersedes": current["id"]})
    conn.commit()
    return get_policy(conn, new_id)


def _jitter_seconds(policy: dict, attempts_completed: int) -> float:
    """Deterministic jitter: SHA-256 of policy id + attempt, scaled to
    [0, jitter_max_s). Same inputs always give the same delay."""
    jitter_max = float(policy["jitter_max_s"])
    if jitter_max <= 0:
        return 0.0
    digest = hashlib.sha256(
        f"{policy['id']}:{attempts_completed}".encode("utf-8")).hexdigest()
    fraction = int(digest[:8], 16) / 0xFFFFFFFF
    return fraction * jitter_max


def next_delay_s(policy: dict, attempts_completed: int) -> float:
    """Delay before the next attempt after ``attempts_completed`` failures.

    Exponential backoff ``base * 2**(n-1)`` capped at ``backoff_cap_s``,
    plus deterministic jitter. ``attempts_completed`` of 1 means the
    first failure: delay = base + jitter.
    """
    n = max(1, attempts_completed)
    base = float(policy["backoff_base_s"])
    cap = float(policy["backoff_cap_s"])
    delay = min(cap, base * (2 ** (n - 1)))
    return delay + _jitter_seconds(policy, n)


def should_retry(policy: dict, attempts: int) -> bool:
    limit = min(int(policy["max_attempts"]), int(policy["dead_letter_after"]))
    return attempts < limit


# ---------------------------------------------------------------------------
# Retry jobs
# ---------------------------------------------------------------------------
def create_job(conn: sqlite3.Connection, name: str, policy_id: int,
               payload: Optional[dict] = None, actor: str = "system",
               now: Optional[str] = None) -> dict:
    name = _check_name(name)
    actor = _check_actor(actor)
    policy = get_policy(conn, policy_id)  # raises when unknown
    if payload is not None and not isinstance(payload, dict):
        raise GovError("payload must be a JSON object")
    created = _now(now)
    cur = conn.execute(
        """INSERT INTO gov_jobs
           (name, policy_id, payload_json, status, attempts, next_run_at,
            actor, created_at, updated_at)
           VALUES (?, ?, ?, 'pending', 0, ?, ?, ?, ?)""",
        (name, policy["id"], json.dumps(payload or {}, sort_keys=True),
         created, actor, created, created),
    )
    job_id = cur.lastrowid
    _record_event(conn, "job", job_id, "job.created", actor,
                  {"name": name, "policy_id": policy["id"]})
    conn.commit()
    return get_job(conn, job_id)


def get_job(conn: sqlite3.Connection, job_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise GovError(f"No job {job_id}")
    return _decode_json(_as_dict(row), "payload_json")


def list_jobs(conn: sqlite3.Connection, status: Optional[str] = None,
              limit: int = 100) -> list[dict]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM gov_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    else:
        if status not in JOB_STATUSES:
            raise GovError(f"unknown job status {status!r}")
        rows = conn.execute(
            "SELECT * FROM gov_jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit)).fetchall()
    return [_decode_json(_as_dict(r), "payload_json") for r in rows]


def due_jobs(conn: sqlite3.Connection, now: Optional[str] = None,
             limit: int = 100) -> list[dict]:
    """Jobs ready to attempt: pending/scheduled/retrying with next_run_at <= now."""
    moment = _now(now)
    rows = conn.execute(
        """SELECT * FROM gov_jobs
           WHERE status IN ('pending', 'scheduled', 'retrying')
           AND next_run_at <= ? ORDER BY next_run_at, id LIMIT ?""",
        (moment, limit)).fetchall()
    return [_decode_json(_as_dict(r), "payload_json") for r in rows]


def attempt_job(conn: sqlite3.Connection, job_id: int, outcome: str,
                error: str = "", actor: str = "system",
                now: Optional[str] = None) -> dict:
    """Record one attempt's outcome, as reported by the caller.

    P05 executes no real work: the caller runs the job and reports
    ``success`` or ``failure``. On failure the policy decides the next
    delay; once attempts reach min(max_attempts, dead_letter_after) the
    job is dead-lettered and a gov_dead_letters row is written.
    """
    if outcome not in ("success", "failure"):
        raise GovError("outcome must be 'success' or 'failure'")
    actor = _check_actor(actor)
    job = get_job(conn, job_id)
    if job["status"] in ("succeeded", "dead_lettered"):
        raise GovError(f"job {job_id} is {job['status']} and cannot be attempted")
    policy = get_policy(conn, job["policy_id"])
    moment = _now(now)
    attempts = job["attempts"] + 1
    if outcome == "success":
        conn.execute(
            "UPDATE gov_jobs SET status = 'succeeded', attempts = ?, "
            "last_error = NULL, updated_at = ? WHERE id = ?",
            (attempts, moment, job_id))
        _record_event(conn, "job", job_id, "job.succeeded", actor,
                      {"attempts": attempts})
    else:
        limit = min(int(policy["max_attempts"]), int(policy["dead_letter_after"]))
        if attempts >= limit:
            conn.execute(
                "UPDATE gov_jobs SET status = 'dead_lettered', attempts = ?, "
                "last_error = ?, updated_at = ? WHERE id = ?",
                (attempts, error.strip() or None, moment, job_id))
            conn.execute(
                """INSERT INTO gov_dead_letters
                   (job_id, policy_id, attempts, last_error, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, policy["id"], attempts, error.strip() or None,
                 json.dumps(job["payload_json"], sort_keys=True), moment))
            _record_event(conn, "job", job_id, "job.dead_lettered", actor,
                          {"attempts": attempts, "error": error.strip()})
        else:
            delay = next_delay_s(policy, attempts)
            next_run = (datetime.fromisoformat(moment).timestamp() + delay)
            next_iso = datetime.fromtimestamp(
                next_run, tz=timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "UPDATE gov_jobs SET status = 'scheduled', attempts = ?, "
                "next_run_at = ?, last_error = ?, updated_at = ? WHERE id = ?",
                (attempts, next_iso, error.strip() or None, moment, job_id))
            _record_event(conn, "job", job_id, "job.scheduled", actor,
                          {"attempts": attempts, "next_delay_s": delay})
    conn.commit()
    return get_job(conn, job_id)


def list_dead_letters(conn: sqlite3.Connection, status: Optional[str] = None,
                      limit: int = 100) -> list[dict]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM gov_dead_letters ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    else:
        if status not in ("open", "replayed"):
            raise GovError(f"unknown dead-letter status {status!r}")
        rows = conn.execute(
            "SELECT * FROM gov_dead_letters WHERE status = ? "
            "ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
    return [_decode_json(_as_dict(r), "payload_json") for r in rows]


def replay_dead_letter(conn: sqlite3.Connection, dead_letter_id: int,
                       actor: str = "system",
                       now: Optional[str] = None) -> dict:
    """Requeue a dead-lettered job as a fresh job (attempts reset).

    The dead-letter row is kept and marked replayed — replay is a new
    job, not an edit of history.
    """
    actor = _check_actor(actor)
    row = conn.execute(
        "SELECT * FROM gov_dead_letters WHERE id = ?", (dead_letter_id,)).fetchone()
    if row is None:
        raise GovError(f"No dead letter {dead_letter_id}")
    dead = _decode_json(_as_dict(row), "payload_json")
    if dead["status"] != "open":
        raise GovError(f"dead letter {dead_letter_id} was already replayed")
    job = get_job(conn, dead["job_id"])
    new_job = create_job(conn, job["name"], dead["policy_id"],
                         payload=dead["payload_json"], actor=actor, now=now)
    conn.execute(
        "UPDATE gov_dead_letters SET status = 'replayed' WHERE id = ?",
        (dead_letter_id,))
    _record_event(conn, "job", new_job["id"], "job.replayed", actor,
                  {"dead_letter_id": dead_letter_id,
                   "from_job_id": dead["job_id"]})
    conn.commit()
    return new_job


# ---------------------------------------------------------------------------
# Alerting rules (as data; firing is recorded only, never sent)
# ---------------------------------------------------------------------------
def _compare(operator: str, value: Any, threshold: Decimal) -> bool:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False
    if operator == "gt":
        return number > threshold
    if operator == "gte":
        return number >= threshold
    if operator == "lt":
        return number < threshold
    if operator == "lte":
        return number <= threshold
    if operator == "eq":
        return number == threshold
    return number != threshold  # ne


def create_rule(conn: sqlite3.Connection, name: str, check_name: Optional[str],
                metric: str, operator: str, threshold: Any, severity: str,
                owner: str = "on-call", dedup_window_s: int = 3600,
                actor: str = "system") -> dict:
    name = _check_name(name)
    actor = _check_actor(actor)
    if check_name is not None:
        check_name = _check_name(check_name, "check_name")
        get_check_by_name(conn, check_name)  # raises when unknown
    metric = (metric or "value").strip()
    if not _KEY_RE.match(metric):
        raise GovError("metric must be 1-64 characters of letters, digits, "
                       "spaces, underscores, or hyphens")
    if operator not in OPERATORS:
        raise GovError(f"unknown operator {operator!r}")
    try:
        threshold_dec = Decimal(str(threshold))
    except (InvalidOperation, ValueError, TypeError):
        raise GovError("threshold must be a number")
    if severity not in SEVERITIES:
        raise GovError(f"unknown severity {severity!r}")
    if not isinstance(dedup_window_s, int) or isinstance(dedup_window_s, bool) \
            or dedup_window_s < 0:
        raise GovError("dedup_window_s must be a non-negative integer")
    owner = (owner or "on-call").strip() or "on-call"
    if len(owner) > 64:
        raise GovError("owner must be at most 64 characters")
    created = utcnow_iso()
    try:
        cur = conn.execute(
            """INSERT INTO gov_rules
               (name, check_name, metric, operator, threshold, severity,
                owner, channel, dedup_window_s, status, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'log', ?, 'active', ?, ?)""",
            (name, check_name, metric, operator, str(threshold_dec), severity,
             owner, dedup_window_s, actor, created),
        )
    except sqlite3.IntegrityError:
        raise GovError(f"rule {name!r} already exists")
    rule_id = cur.lastrowid
    _record_event(conn, "rule", rule_id, "rule.created", actor,
                  {"name": name, "severity": severity})
    conn.commit()
    return get_rule(conn, rule_id)


def get_rule(conn: sqlite3.Connection, rule_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_rules WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise GovError(f"No rule {rule_id}")
    return _as_dict(row)


def list_rules(conn: sqlite3.Connection, status: Optional[str] = None) -> list[dict]:
    if status is None:
        rows = conn.execute("SELECT * FROM gov_rules ORDER BY id").fetchall()
    else:
        if status not in ("active", "disabled"):
            raise GovError(f"unknown rule status {status!r}")
        rows = conn.execute(
            "SELECT * FROM gov_rules WHERE status = ? ORDER BY id",
            (status,)).fetchall()
    return [_as_dict(r) for r in rows]


def silence_rule(conn: sqlite3.Connection, rule_id: int, until_iso: str,
                 actor: str = "system") -> dict:
    """Silence a rule until ``until_iso``. Silenced rules do not fire;
    the suppression is recorded as an audit event when a firing is skipped."""
    actor = _check_actor(actor)
    rule = get_rule(conn, rule_id)
    until = _parse_iso(until_iso, "until")
    if until <= datetime.now(timezone.utc):
        raise GovError("silenced_until must be in the future")
    conn.execute(
        "UPDATE gov_rules SET silenced_until = ? WHERE id = ?",
        (until_iso, rule_id))
    _record_event(conn, "rule", rule_id, "rule.silenced", actor,
                  {"until": until_iso})
    conn.commit()
    return get_rule(conn, rule_id)


def _fingerprint(rule_id: int, check_id: Optional[int]) -> str:
    return hashlib.sha256(f"{rule_id}:{check_id}".encode("utf-8")).hexdigest()


def evaluate_rules(conn: sqlite3.Connection, check_run: dict,
                   now: Optional[str] = None) -> list[int]:
    """Evaluate active rules against one recorded check run.

    Returns the ids of alerts fired or dedup-bumped. Firing is recorded
    only — no alert is ever sent anywhere. A silenced rule is skipped
    and the suppression is audit-logged.
    """
    moment = _now(now)
    moment_dt = datetime.fromisoformat(moment)
    check = get_check(conn, check_run["check_id"])
    detail = check_run.get("detail_json", {})
    if isinstance(detail, str):
        detail = json.loads(detail)
    rules = [r for r in list_rules(conn, status="active")
             if r["check_name"] is None or r["check_name"] == check["name"]]
    fired: list[int] = []
    for rule in rules:
        metric = rule["metric"]
        if metric not in detail:
            continue
        threshold = Decimal(rule["threshold"])
        if not _compare(rule["operator"], detail[metric], threshold):
            continue
        if rule.get("silenced_until"):
            silenced_until = datetime.fromisoformat(rule["silenced_until"])
            if silenced_until > moment_dt:
                _record_event(conn, "rule", rule["id"], "rule.suppressed",
                              "system",
                              {"check_id": check["id"],
                               "silenced_until": rule["silenced_until"]})
                conn.commit()
                continue
        fingerprint = _fingerprint(rule["id"], check["id"])
        existing = conn.execute(
            """SELECT * FROM gov_alerts WHERE fingerprint = ?
               AND status IN ('open', 'acked') ORDER BY id DESC LIMIT 1""",
            (fingerprint,)).fetchone()
        window = int(rule["dedup_window_s"])
        if existing is not None:
            last_seen = datetime.fromisoformat(existing["last_seen"])
            if (moment_dt - last_seen).total_seconds() <= window:
                conn.execute(
                    "UPDATE gov_alerts SET count = count + 1, last_seen = ?, "
                    "detail_json = ? WHERE id = ?",
                    (moment,
                     json.dumps({"value": detail.get(metric),
                                 "check": check["name"]}, sort_keys=True),
                     existing["id"]))
                _record_event(conn, "alert", existing["id"], "alert.deduped",
                              "system", {"rule_id": rule["id"],
                                         "count": existing["count"] + 1})
                conn.commit()
                fired.append(existing["id"])
                continue
        cur = conn.execute(
            """INSERT INTO gov_alerts
               (fingerprint, rule_id, check_id, severity, status,
                first_seen, last_seen, count, detail_json, created_at)
               VALUES (?, ?, ?, ?, 'open', ?, ?, 1, ?, ?)""",
            (fingerprint, rule["id"], check["id"], rule["severity"],
             moment, moment,
             json.dumps({"value": detail.get(metric),
                         "check": check["name"]}, sort_keys=True), moment),
        )
        alert_id = cur.lastrowid
        _record_event(conn, "alert", alert_id, "alert.fired", "system",
                      {"rule_id": rule["id"], "check_id": check["id"],
                       "severity": rule["severity"]})
        conn.commit()
        fired.append(alert_id)
    return fired


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def get_alert(conn: sqlite3.Connection, alert_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise GovError(f"No alert {alert_id}")
    return _decode_json(_as_dict(row), "detail_json")


def list_alerts(conn: sqlite3.Connection, status: Optional[str] = None,
                limit: int = 100) -> list[dict]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM gov_alerts ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    else:
        if status not in ALERT_STATUSES:
            raise GovError(f"unknown alert status {status!r}")
        rows = conn.execute(
            "SELECT * FROM gov_alerts WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit)).fetchall()
    return [_decode_json(_as_dict(r), "detail_json") for r in rows]


def _transition_alert(conn: sqlite3.Connection, alert_id: int, to_status: str,
                      actor: str) -> dict:
    alert = get_alert(conn, alert_id)
    try:
        ALERT_WORKFLOW.check(alert["status"], to_status)
    except InvalidTransition as exc:
        raise GovError(str(exc))
    conn.execute(
        "UPDATE gov_alerts SET status = ? WHERE id = ?", (to_status, alert_id))
    _record_event(conn, "alert", alert_id, f"alert.{to_status}", actor,
                  {"from": alert["status"]})
    conn.commit()
    return get_alert(conn, alert_id)


def ack_alert(conn: sqlite3.Connection, alert_id: int,
              actor: str = "system") -> dict:
    return _transition_alert(conn, alert_id, "acked", _check_actor(actor))


def resolve_alert(conn: sqlite3.Connection, alert_id: int,
                  actor: str = "system") -> dict:
    return _transition_alert(conn, alert_id, "resolved", _check_actor(actor))


# ---------------------------------------------------------------------------
# Runbooks (versioned, keyed by alert key)
# ---------------------------------------------------------------------------
def _validate_steps(steps: Any) -> list[dict]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise GovError("steps must be a list of 1-20 steps")
    cleaned = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise GovError(f"step {i} must be an object")
        name = str(step.get("step", "")).strip()
        action = str(step.get("action", "")).strip()
        timebox = step.get("timebox_s")
        if not name or not action:
            raise GovError(f"step {i} needs a step name and an action")
        if not isinstance(timebox, int) or isinstance(timebox, bool) \
                or timebox <= 0:
            raise GovError(f"step {i} needs a positive integer timebox_s")
        cleaned.append({"step": name, "action": action, "timebox_s": timebox})
    return cleaned


def create_runbook(conn: sqlite3.Connection, name: str, alert_key: str,
                   steps: Any, actor: str = "system") -> dict:
    name = _check_name(name)
    actor = _check_actor(actor)
    alert_key = _check_name(alert_key, "alert_key")
    steps = _validate_steps(steps)
    created = utcnow_iso()
    try:
        cur = conn.execute(
            """INSERT INTO gov_runbooks
               (name, version, status, alert_key, steps_json, created_by, created_at)
               VALUES (?, 1, 'current', ?, ?, ?, ?)""",
            (name, alert_key, json.dumps(steps, sort_keys=True), actor, created),
        )
    except sqlite3.IntegrityError:
        raise GovError(f"runbook {name!r} already exists")
    runbook_id = cur.lastrowid
    _record_event(conn, "runbook", runbook_id, "runbook.created", actor,
                  {"name": name, "version": 1, "alert_key": alert_key})
    conn.commit()
    return get_runbook(conn, runbook_id)


def get_runbook(conn: sqlite3.Connection, runbook_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_runbooks WHERE id = ?", (runbook_id,)).fetchone()
    if row is None:
        raise GovError(f"No runbook {runbook_id}")
    return _decode_json(_as_dict(row), "steps_json")


def get_runbook_by_name(conn: sqlite3.Connection, name: str,
                        version: Optional[int] = None) -> dict:
    if version is None:
        row = conn.execute(
            "SELECT * FROM gov_runbooks WHERE name = ? AND status = 'current'",
            (name,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM gov_runbooks WHERE name = ? AND version = ?",
            (name, version)).fetchone()
    if row is None:
        raise GovError(f"No runbook {name!r}")
    return _decode_json(_as_dict(row), "steps_json")


def list_runbooks(conn: sqlite3.Connection,
                  include_superseded: bool = False) -> list[dict]:
    if include_superseded:
        rows = conn.execute(
            "SELECT * FROM gov_runbooks ORDER BY name, version").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM gov_runbooks WHERE status = 'current' ORDER BY name"
        ).fetchall()
    return [_decode_json(_as_dict(r), "steps_json") for r in rows]


def supersede_runbook(conn: sqlite3.Connection, name: str, alert_key: str,
                      steps: Any, actor: str = "system") -> dict:
    current = get_runbook_by_name(conn, name)
    alert_key = _check_name(alert_key, "alert_key")
    steps = _validate_steps(steps)
    actor = _check_actor(actor)
    new_version = current["version"] + 1
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO gov_runbooks
           (name, version, status, alert_key, steps_json, created_by, created_at)
           VALUES (?, ?, 'current', ?, ?, ?, ?)""",
        (name, new_version, alert_key, json.dumps(steps, sort_keys=True),
         actor, created),
    )
    new_id = cur.lastrowid
    conn.execute(
        "UPDATE gov_runbooks SET status = 'superseded', superseded_by = ? "
        "WHERE id = ?", (new_id, current["id"]))
    _record_event(conn, "runbook", new_id, "runbook.superseded", actor,
                  {"name": name, "version": new_version,
                   "supersedes": current["id"]})
    conn.commit()
    return get_runbook(conn, new_id)


def runbook_for_key(conn: sqlite3.Connection, alert_key: str) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_runbooks WHERE alert_key = ? AND status = 'current' "
        "ORDER BY id LIMIT 1", (alert_key,)).fetchone()
    if row is None:
        raise GovError(f"No current runbook for alert key {alert_key!r}")
    return _decode_json(_as_dict(row), "steps_json")


def walkthrough(conn: sqlite3.Connection, runbook_id: int,
                clock: Optional[Callable[[], float]] = None,
                step_work: Optional[Callable[[dict], None]] = None) -> dict:
    """Timed runbook walkthrough harness (S01 shape).

    Executes each step (``step_work`` does the synthetic work; the
    default is a no-op) and checks every step finishes inside its
    documented time box. ``clock`` is injectable for deterministic
    tests; wall-clock is also recorded so the harness is measurably fast.
    """
    runbook = get_runbook(conn, runbook_id)
    now = clock or time.monotonic
    wall_start = time.monotonic()
    step_results = []
    for step in runbook["steps_json"]:
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
        "runbook_id": runbook["id"],
        "runbook_name": runbook["name"],
        "version": runbook["version"],
        "alert_key": runbook["alert_key"],
        "steps": step_results,
        "all_within_timebox": all(s["within_timebox"] for s in step_results),
        "wall_elapsed_s": wall_elapsed,
    }


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
def create_incident(conn: sqlite3.Connection, title: str, severity: str,
                    source_alert_id: Optional[int] = None,
                    actor: str = "system") -> dict:
    title = (title or "").strip()
    if not title:
        raise GovError("title is required")
    if len(title) > 200:
        raise GovError("title must be at most 200 characters")
    if severity not in SEVERITIES:
        raise GovError(f"unknown severity {severity!r}")
    actor = _check_actor(actor)
    if source_alert_id is not None:
        get_alert(conn, source_alert_id)  # raises when unknown
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO gov_incidents
           (title, severity, status, source_alert_id, actor, created_at, updated_at)
           VALUES (?, ?, 'open', ?, ?, ?, ?)""",
        (title, severity, source_alert_id, actor, created, created),
    )
    incident_id = cur.lastrowid
    conn.execute(
        """INSERT INTO gov_incident_events
           (incident_id, event_type, actor, from_status, to_status, detail_json, created_at)
           VALUES (?, 'created', ?, NULL, 'open', ?, ?)""",
        (incident_id, actor,
         json.dumps({"title": title, "severity": severity}, sort_keys=True),
         created),
    )
    _record_event(conn, "incident", incident_id, "incident.created", actor,
                  {"title": title, "severity": severity})
    conn.commit()
    return get_incident(conn, incident_id)


def get_incident(conn: sqlite3.Connection, incident_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM gov_incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise GovError(f"incident {incident_id} not found")
    incident = _as_dict(row)
    incident["timeline"] = [
        dict(r) for r in conn.execute(
            "SELECT * FROM gov_incident_events WHERE incident_id = ? ORDER BY id",
            (incident_id,)).fetchall()
    ]
    return incident


def list_incidents(conn: sqlite3.Connection, status: Optional[str] = None,
                   limit: int = 100) -> list[dict]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM gov_incidents ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    else:
        if status not in INCIDENT_WORKFLOW.states:
            raise GovError(f"unknown incident status {status!r}")
        rows = conn.execute(
            "SELECT * FROM gov_incidents WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit)).fetchall()
    return [_as_dict(r) for r in rows]


def transition_incident(conn: sqlite3.Connection, incident_id: int,
                        to_status: str, actor: str = "system",
                        note: str = "") -> dict:
    """Move an incident through the P05 lifecycle.

    Resolving requires a resolution note — an incident is not resolved
    by silence. The note is stored on the incident and on the timeline.
    """
    actor = _check_actor(actor)
    incident = get_incident(conn, incident_id)
    if to_status not in INCIDENT_WORKFLOW.states:
        raise GovError(f"unknown status {to_status!r}")
    try:
        INCIDENT_WORKFLOW.check(incident["status"], to_status)
    except InvalidTransition as exc:
        raise GovError(str(exc))
    note = (note or "").strip()
    if to_status == "resolved" and not note:
        raise GovError("resolving an incident requires a resolution note")
    now = utcnow_iso()
    conn.execute(
        "UPDATE gov_incidents SET status = ?, updated_at = ?, "
        "resolution_note = ? WHERE id = ?",
        (to_status, now,
         note if to_status == "resolved" else incident.get("resolution_note"),
         incident_id),
    )
    conn.execute(
        """INSERT INTO gov_incident_events
           (incident_id, event_type, actor, from_status, to_status, detail_json, created_at)
           VALUES (?, 'transition', ?, ?, ?, ?, ?)""",
        (incident_id, actor, incident["status"], to_status,
         json.dumps({"note": note}) if note else None, now),
    )
    _record_event(conn, "incident", incident_id, "incident.transition", actor,
                  {"from": incident["status"], "to": to_status})
    conn.commit()
    return get_incident(conn, incident_id)


def add_incident_note(conn: sqlite3.Connection, incident_id: int, note: str,
                      actor: str = "system") -> dict:
    """Append a free-text note to the incident timeline (post-incident
    follow-ups live here). Notes never change the incident's status."""
    actor = _check_actor(actor)
    note = (note or "").strip()
    if not note:
        raise GovError("note is required")
    incident = get_incident(conn, incident_id)
    now = utcnow_iso()
    conn.execute(
        """INSERT INTO gov_incident_events
           (incident_id, event_type, actor, from_status, to_status, detail_json, created_at)
           VALUES (?, 'note', ?, ?, ?, ?, ?)""",
        (incident_id, actor, incident["status"], incident["status"],
         json.dumps({"note": note}, sort_keys=True), now),
    )
    _record_event(conn, "incident", incident_id, "incident.note", actor,
                  {"note": note[:200]})
    conn.commit()
    return get_incident(conn, incident_id)


# ---------------------------------------------------------------------------
# Demo seed (idempotent, synthetic only)
# ---------------------------------------------------------------------------
def seed_demo_data(conn: sqlite3.Connection, actor: str = "demo") -> dict:
    """Seed P05 demo definitions + one run of each check + one demo job.

    Idempotent: existing names are skipped, checks are only run when
    they have no runs yet, and the demo job/incident are created once.
    Returns counts of what was created this call.
    """
    actor = _check_actor(actor)
    created = {"checks": 0, "policies": 0, "rules": 0, "runbooks": 0,
               "runs": 0, "jobs": 0, "incidents": 0}

    checks = [
        ("DB-REACHABLE", "db", "liveness", "db_reachable", {}, 0, 0,
         "Database answers SELECT 1 and has tables."),
        ("MIGRATIONS-CURRENT", "db", "readiness", "migrations_current", {}, 0, 0,
         "No migration file is unapplied."),
        ("QUEUE-MISSED-CALLS", "queue", "readiness", "queue_depth",
         {"table": "missed_calls", "value": "pending"}, 5, 20,
         "Pending missed calls awaiting callback."),
        ("STORAGE-TMP", "storage", "readiness", "storage_tmp",
         {"path": "/tmp"}, 80, 95, "Share of /tmp used, in percent."),
        ("APP-SMOKE", "app", "liveness", "app_smoke", {}, 0, 0,
         "Migrations applied and governance tables present."),
    ]
    for name, subsystem, kind, probe, params, warn, fail, desc in checks:
        try:
            get_check_by_name(conn, name)
        except GovError:
            create_check(conn, name, subsystem, kind, probe, params,
                         warn, fail, desc, actor)
            created["checks"] += 1

    policies = [
        ("STANDARD-RETRY", 5, 30, 3600, 5, 5,
         "Default retry: up to 5 attempts, 30s base, 1h cap."),
        ("FAST-RETRY", 3, 5, 300, 2, 3,
         "Short retry: up to 3 attempts, 5s base, 5m cap."),
    ]
    for name, max_a, base, cap, jitter, dla, desc in policies:
        try:
            get_policy_by_name(conn, name)
        except GovError:
            create_policy(conn, name, max_a, base, cap, jitter, dla, desc, actor)
            created["policies"] += 1

    rules = [
        ("QUEUE-DEPTH-HIGH", "QUEUE-MISSED-CALLS", "value", "gt", 20, "high",
         "on-call", 3600),
        ("MIGRATIONS-PENDING", "MIGRATIONS-CURRENT", "value", "gt", 0, "critical",
         "on-call", 3600),
        ("STORAGE-HIGH", "STORAGE-TMP", "value", "gt", 90, "high",
         "on-call", 3600),
        ("DB-UNREACHABLE", "DB-REACHABLE", "value", "gt", 0, "critical",
         "on-call", 3600),
    ]
    for name, check_name, metric, op, thr, sev, owner, dedup in rules:
        existing = conn.execute(
            "SELECT id FROM gov_rules WHERE name = ?", (name,)).fetchone()
        if existing is None:
            create_rule(conn, name, check_name, metric, op, thr, sev,
                        owner, dedup, actor)
            created["rules"] += 1

    runbooks = [
        ("RB-CRITICAL", "critical", [
            {"step": "acknowledge", "action": "Open an incident from the alert.",
             "timebox_s": 900},
            {"step": "investigate", "action": "Check the latest probe run and "
             "the status summary; identify the failing subsystem.",
             "timebox_s": 3600},
            {"step": "mitigate", "action": "Apply the workaround or restart "
             "the affected subsystem; re-run the check.",
             "timebox_s": 14400},
            {"step": "resolve", "action": "Confirm the check passes, write "
             "the resolution note, resolve the incident.",
             "timebox_s": 28800},
        ]),
        ("RB-HIGH", "high", [
            {"step": "acknowledge", "action": "Open an incident from the alert.",
             "timebox_s": 3600},
            {"step": "investigate", "action": "Review the last 24h of check "
             "runs; decide contain vs. monitor.", "timebox_s": 28800},
            {"step": "resolve", "action": "Apply the fix or tune the alert; "
             "document; close the ticket.", "timebox_s": 172800},
        ]),
    ]
    for name, key, steps in runbooks:
        try:
            get_runbook_by_name(conn, name)
        except GovError:
            create_runbook(conn, name, key, steps, actor)
            created["runbooks"] += 1

    for check in list_checks(conn):
        if _latest_run(conn, check["id"]) is None:
            run_check(conn, check["id"], actor=actor)
            created["runs"] += 1

    existing_job = conn.execute(
        "SELECT id FROM gov_jobs WHERE name = ?", ("DEMO-WEBHOOK-DELIVERY",)
    ).fetchone()
    if existing_job is None:
        policy = get_policy_by_name(conn, "STANDARD-RETRY")
        create_job(conn, "DEMO-WEBHOOK-DELIVERY", policy["id"],
                   {"endpoint": "stub:crm-sink", "event_id": "EVT-DEMO-001"},
                   actor=actor)
        created["jobs"] += 1

    existing_incident = conn.execute(
        "SELECT id FROM gov_incidents WHERE title = ?",
        ("Demo: weekly governance review",)).fetchone()
    if existing_incident is None:
        create_incident(conn, "Demo: weekly governance review", "low",
                        actor=actor)
        created["incidents"] += 1

    return created
