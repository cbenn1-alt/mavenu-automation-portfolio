"""Project Q07 — Multi-Location KPI Rollup Pipeline.

Pipeline: register location + schema map -> ingest CSV -> validate ->
stage (good rows) / quarantine (bad rows, each with a reason) -> compute
per-location KPIs -> rollup across locations with drill-down lineage.

- **Ingest** (``ingest_csv``): per-location CSV parsed through the
  location's configured schema map (canonical field -> source column).
  Schema drift is explicit: unknown CSV columns are quarantined as
  per-column entries (source_row NULL) + a ``schema_drift`` alert, while
  good rows still flow; a *mapped* column missing from the CSV quarantines
  every row with a reason (nothing silently dropped). Idempotency is on the
  batch's natural key (location, period, label) — re-uploading the same
  batch is a no-op; a different CSV for the same period is a new batch, so
  no source_row collision and no double counting.
- **Validate**: row-level checks; every bad row lands in ``kpi_quarantine``
  with a machine-readable reason. Zero silent drops: every input data row
  is either staged or quarantined.
- **KPI** (see ``kpi_defs.py``): versioned, documented formulas over Decimal
  aggregates. ``compute_location_kpis`` writes ``kpi_values`` + full
  ``kpi_lineage``; ``compute_rollup`` consolidates across locations
  (``location_id`` NULL) with lineage to every source row.
- **Restatement**: ``update_definition`` + ``restate_period``. The old
  definition row is superseded (never edited), old values keep status
  'current' -> flipped to 'superseded' with the restatement id, new values
  are recomputed, and ``kpi_restatements`` records the change.

Money is Decimal (stored as text), never float. Clock is injectable for
tests; production callers leave it None (real wall clock).

ALL DATA IS SYNTHETIC DEMONSTRATION DATA.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from . import kpi_defs
from .db import utcnow_iso

#: Canonical staging fields every schema map must cover.
CANONICAL_FIELDS = (
    "job_id",
    "completed_date",
    "revenue",
    "costs",
    "is_callback",
    "tech_days",
)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_TRUE = {"y", "yes", "true", "1", "t"}
_FALSE = {"n", "no", "false", "0", "f"}


class KpiPipelineError(Exception):
    """Domain error for the rollup pipeline (bad config, bad input)."""


# ---------------------------------------------------------------------------
# Location + schema-map registration
# ---------------------------------------------------------------------------


def register_location(
    conn: sqlite3.Connection,
    code: str,
    name: str,
    schema_map: dict[str, str],
    schema_version: str = "v1",
    actor: str = "system",
    clock: Callable[[], str] = utcnow_iso,
) -> int:
    """Register a location and its configured CSV schema map.

    ``schema_map`` is canonical field -> source CSV column. Raises
    KpiPipelineError when a canonical field is missing or the map is
    otherwise invalid.
    """
    code = (code or "").strip().lower()
    name = (name or "").strip()
    schema_version = (schema_version or "").strip()
    if not code:
        raise KpiPipelineError("location code is required")
    if not name:
        raise KpiPipelineError("location name is required")
    if not schema_version:
        raise KpiPipelineError("schema_version is required")
    if not isinstance(schema_map, dict):
        raise KpiPipelineError("schema_map must be a dict")
    missing = [f for f in CANONICAL_FIELDS if not (schema_map.get(f) or "").strip()]
    if missing:
        raise KpiPipelineError(
            f"schema_map missing canonical field(s): {', '.join(missing)}"
        )
    extras = [k for k in schema_map if k not in CANONICAL_FIELDS]
    if extras:
        raise KpiPipelineError(
            f"schema_map has unknown canonical field(s): {', '.join(extras)}"
        )
    now = clock()
    row = conn.execute(
        "SELECT id FROM kpi_locations WHERE code = ?", (code,)
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO kpi_locations (code, name, active, created_at) "
            "VALUES (?, ?, 1, ?)",
            (code, name, now),
        )
        location_id = cur.lastrowid
        _record_event(conn, "location", location_id, "location.registered",
                      actor, {"code": code, "name": name}, clock)
    else:
        location_id = row["id"]
        conn.execute(
            "UPDATE kpi_locations SET name = ? WHERE id = ?", (name, location_id)
        )
    existing = conn.execute(
        "SELECT id FROM kpi_schema_maps WHERE location_id = ? AND schema_version = ?",
        (location_id, schema_version),
    ).fetchone()
    clean_map = {f: schema_map[f].strip() for f in CANONICAL_FIELDS}
    if existing is None:
        cur = conn.execute(
            """INSERT INTO kpi_schema_maps
               (location_id, schema_version, map_json, created_by, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (location_id, schema_version, json.dumps(clean_map, sort_keys=True),
             actor, now),
        )
        map_id = cur.lastrowid
        _record_event(conn, "schema_map", map_id, "schema_map.registered",
                      actor, {"location_code": code,
                              "schema_version": schema_version}, clock)
    else:
        map_id = existing["id"]
    conn.commit()
    return location_id


def get_schema_map(
    conn: sqlite3.Connection, location_code: str
) -> tuple[int, int, dict[str, str], str]:
    """Return (location_id, map_id, schema_map, schema_version) — latest version."""
    row = conn.execute(
        "SELECT id FROM kpi_locations WHERE code = ? AND active = 1",
        (location_code.strip().lower(),),
    ).fetchone()
    if row is None:
        raise KpiPipelineError(
            f"Unknown or inactive location {location_code!r}")
    location_id = row["id"]
    mrow = conn.execute(
        """SELECT id, schema_version, map_json FROM kpi_schema_maps
           WHERE location_id = ? ORDER BY id DESC LIMIT 1""",
        (location_id,),
    ).fetchone()
    if mrow is None:
        raise KpiPipelineError(
            f"No schema map registered for location {location_code!r}")
    return location_id, mrow["id"], json.loads(mrow["map_json"]), mrow["schema_version"]


# ---------------------------------------------------------------------------
# Ingest + validate
# ---------------------------------------------------------------------------


def _parse_bool(raw: str) -> Optional[bool]:
    token = (raw or "").strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    return None


def _parse_money(raw: str) -> Optional[Decimal]:
    text = (raw or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value


def _parse_date(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not DATE_RE.match(text):
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def ingest_csv(
    conn: sqlite3.Connection,
    location_code: str,
    period: str,
    csv_text: str,
    actor: str = "system",
    label: Optional[str] = None,
    clock: Callable[[], str] = utcnow_iso,
) -> dict:
    """Ingest one location's CSV for one period through its schema map.

    Returns {"staged": n, "quarantined": n, "alerts": n,
             "quarantine_reasons": [...], "schema_map_id": id,
             "ingest_id": id, "deduped": bool}.
    Idempotency: (location, period, label) is the batch's natural key.
    Re-uploading the same batch is a no-op (``deduped`` True, no new rows).
    A *different* CSV for the same period is a new batch — staged rows keep
    flowing and nothing is double counted. When ``label`` is omitted it
    defaults to the SHA-256 of the CSV text.
    """
    import hashlib

    period = (period or "").strip()
    if not PERIOD_RE.match(period):
        raise KpiPipelineError(
            f"period must be 'YYYY-MM', got {period!r}")
    location_id, map_id, schema_map, schema_version = get_schema_map(
        conn, location_code)
    label = (label or "").strip()
    if not label:
        label = "csv:" + hashlib.sha256(
            (csv_text or "").encode("utf-8")).hexdigest()[:16]
    existing = conn.execute(
        "SELECT id FROM kpi_ingests "
        "WHERE location_id = ? AND period = ? AND label = ?",
        (location_id, period, label),
    ).fetchone()
    if existing is not None:
        # Same batch already ingested: no-op, nothing duplicates.
        return {"staged": 0, "quarantined": 0, "alerts": 0,
                "quarantine_reasons": [], "schema_map_id": map_id,
                "ingest_id": existing["id"], "deduped": True}
    now = clock()
    cur = conn.execute(
        """INSERT INTO kpi_ingests
           (location_id, period, label, actor, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (location_id, period, label, actor, now),
    )
    ingest_id = cur.lastrowid
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    headers = reader.fieldnames or []
    if not headers:
        raise KpiPipelineError("CSV has no header row")
    mapped_columns = set(schema_map.values())

    alerts = 0
    # --- schema drift: unknown columns -----------------------------------
    unknown_columns = [h for h in headers if h not in mapped_columns]
    for col in unknown_columns:
        sample = [row.get(col, "") for row in _peek_rows(csv_text, col)]
        conn.execute(
            """INSERT INTO kpi_quarantine
               (location_id, period, source_row, reason, raw_json, created_at)
               VALUES (?, ?, NULL, ?, ?, ?)""",
            (location_id, period, f"unknown_column:{col}",
             json.dumps({"column": col, "sample_values": sample[:5]},
                        sort_keys=True), now),
        )
        _raise_alert(conn, "schema_drift", location_id, period,
                     {"column": col, "schema_version": schema_version,
                      "note": "CSV column not covered by the configured "
                              "schema map; values held in quarantine."},
                     actor, clock)
        alerts += 1
    # --- schema drift: mapped column missing from the CSV ----------------
    missing_columns = [c for c in mapped_columns if c not in headers]
    quarantined = 0
    staged = 0
    reasons: list[str] = []
    rows = list(reader)
    if missing_columns:
        for idx, row in enumerate(rows, start=1):
            reason = "missing_mapped_column:" + ",".join(sorted(missing_columns))
            conn.execute(
                """INSERT INTO kpi_quarantine
                   (location_id, period, source_row, reason, raw_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (location_id, period, idx, reason,
                 json.dumps({h: row.get(h, "") for h in headers},
                            sort_keys=True), now),
            )
            quarantined += 1
            if reason not in reasons:
                reasons.append(reason)
        _raise_alert(conn, "schema_drift", location_id, period,
                     {"missing_mapped_columns": sorted(missing_columns),
                      "schema_version": schema_version,
                      "note": "Configured schema-map column(s) absent from "
                              "the CSV; all rows quarantined."},
                     actor, clock)
        alerts += 1
        stats = {
            "staged": 0, "quarantined": quarantined, "alerts": alerts,
            "quarantine_reasons": reasons, "schema_map_id": map_id,
            "ingest_id": ingest_id, "deduped": False,
        }
        _record_event(conn, "ingest", ingest_id, "ingest.completed", actor,
                      {"location_code": location_code, "period": period,
                       "label": label, **stats}, clock)
        conn.commit()
        return stats
    # --- per-row validate + stage -----------------------------------------
    for idx, row in enumerate(rows, start=1):
        mapped = {f: (row.get(schema_map[f]) or "") for f in CANONICAL_FIELDS}
        reason = _validate_mapped(mapped)
        if reason is not None:
            conn.execute(
                """INSERT INTO kpi_quarantine
                   (location_id, period, source_row, reason, raw_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (location_id, period, idx, reason,
                 json.dumps(mapped, sort_keys=True), now),
            )
            quarantined += 1
            if reason not in reasons:
                reasons.append(reason)
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO kpi_staging
               (ingest_id, location_id, schema_map_id, period, source_row,
                job_id, completed_date, revenue, costs, is_callback,
                tech_days, raw_json, staged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ingest_id, location_id, map_id, period, idx,
             mapped["job_id"].strip(),
             mapped["completed_date"].strip(), str(mapped["_revenue"]),
             str(mapped["_costs"]), 1 if mapped["_is_callback"] else 0,
             str(mapped["_tech_days"]),
             json.dumps(mapped, sort_keys=True, default=str), now),
        )
        if cur.rowcount:
            staged += 1
    stats = {
        "staged": staged, "quarantined": quarantined, "alerts": alerts,
        "quarantine_reasons": reasons, "schema_map_id": map_id,
        "ingest_id": ingest_id, "deduped": False,
    }
    _record_event(conn, "ingest", ingest_id, "ingest.completed", actor,
                  {"location_code": location_code, "period": period,
                   "label": label, **stats}, clock)
    conn.commit()
    return stats


def _peek_rows(csv_text: str, col: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    return list(reader)


def _validate_mapped(mapped: dict) -> Optional[str]:
    """Validate one mapped row. Returns a quarantine reason, or None if good.

    Parsed values are stashed back into ``mapped`` under private keys.
    """
    if not mapped["job_id"].strip():
        return "missing_job_id"
    date = _parse_date(mapped["completed_date"])
    if date is None:
        return f"invalid_completed_date:{mapped['completed_date'].strip()}"
    mapped["completed_date"] = date
    revenue = _parse_money(mapped["revenue"])
    if revenue is None or revenue < 0:
        return f"invalid_revenue:{mapped['revenue'].strip()}"
    mapped["_revenue"] = revenue
    costs = _parse_money(mapped["costs"])
    if costs is None or costs < 0:
        return f"invalid_costs:{mapped['costs'].strip()}"
    mapped["_costs"] = costs
    flag = _parse_bool(mapped["is_callback"])
    if flag is None:
        return f"invalid_is_callback:{mapped['is_callback'].strip()}"
    mapped["_is_callback"] = flag
    tech_days = _parse_money(mapped["tech_days"])
    if tech_days is None or tech_days < 0:
        return f"invalid_tech_days:{mapped['tech_days'].strip()}"
    mapped["_tech_days"] = tech_days
    return None


def _raise_alert(
    conn: sqlite3.Connection, alert_type: str,
    location_id: Optional[int], period: Optional[str], detail: dict,
    actor: str, clock: Callable[[], str],
) -> int:
    cur = conn.execute(
        """INSERT INTO kpi_alerts
           (alert_type, location_id, period, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (alert_type, location_id, period,
         json.dumps(detail, sort_keys=True), clock()),
    )
    alert_id = cur.lastrowid
    _record_event(conn, "alert", alert_id, f"alert.{alert_type}", actor,
                  {"location_id": location_id, "period": period,
                   **detail}, clock)
    return alert_id


def resolve_alert(conn: sqlite3.Connection, alert_id: int,
                  actor: str, clock: Callable[[], str] = utcnow_iso) -> None:
    cur = conn.execute(
        "UPDATE kpi_alerts SET resolved_at = ?, resolved_by = ? "
        "WHERE id = ? AND resolved_at IS NULL",
        (clock(), actor, alert_id),
    )
    if cur.rowcount == 0:
        raise KpiPipelineError(f"Alert {alert_id} not found or already resolved")
    _record_event(conn, "alert", alert_id, "alert.resolved", actor, {}, clock)
    conn.commit()


# ---------------------------------------------------------------------------
# KPI computation + rollup (with drill-down lineage)
# ---------------------------------------------------------------------------


def _staged_rows(conn: sqlite3.Connection, period: str,
                 location_id: Optional[int]) -> list[dict]:
    if location_id is None:
        cur = conn.execute(
            "SELECT id, location_id, job_id, revenue, costs, is_callback, "
            "tech_days FROM kpi_staging WHERE period = ? ORDER BY id",
            (period,),
        )
    else:
        cur = conn.execute(
            "SELECT id, location_id, job_id, revenue, costs, is_callback, "
            "tech_days FROM kpi_staging WHERE period = ? AND location_id = ? "
            "ORDER BY id",
            (period, location_id),
        )
    return [
        {
            "staging_id": r["id"],
            "location_id": r["location_id"],
            "job_id": r["job_id"],
            "revenue": Decimal(r["revenue"]),
            "costs": Decimal(r["costs"]),
            "is_callback": bool(r["is_callback"]),
            "tech_days": Decimal(r["tech_days"]),
        }
        for r in cur
    ]


def _store_values(
    conn: sqlite3.Connection, period: str, location_id: Optional[int],
    values: dict[str, Optional[Decimal]],
    definitions: dict[str, kpi_defs.KpiDefinition],
    agg_inputs: dict, staging_ids: list[int],
    actor: str, clock: Callable[[], str],
) -> list[int]:
    """Upsert current kpi_values + rewrite lineage. Returns value ids."""
    now = clock()
    value_ids: list[int] = []
    for name, value in values.items():
        definition = definitions[name]
        cur = conn.execute(
            """INSERT INTO kpi_values
               (period, location_id, kpi_name, definition_id, value,
                inputs_json, status, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, 'current', ?)
               ON CONFLICT (period, COALESCE(location_id, -1), kpi_name,
                            definition_id)
               DO UPDATE SET value = excluded.value,
                             inputs_json = excluded.inputs_json,
                             computed_at = excluded.computed_at""",
            (period, location_id, name, definition.id,
             None if value is None else str(value),
             json.dumps(agg_inputs, sort_keys=True, default=str), now),
        )
        row = conn.execute(
            """SELECT id FROM kpi_values
               WHERE period = ? AND COALESCE(location_id, -1) = COALESCE(?, -1)
                 AND kpi_name = ? AND definition_id = ?""",
            (period, location_id, name, definition.id),
        ).fetchone()
        value_id = row["id"]
        conn.execute("DELETE FROM kpi_lineage WHERE kpi_value_id = ?",
                     (value_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO kpi_lineage (kpi_value_id, staging_row_id) "
            "VALUES (?, ?)",
            [(value_id, sid) for sid in staging_ids],
        )
        _record_event(conn, "kpi_value", value_id, "kpi_value.computed",
                      actor, {"period": period, "location_id": location_id,
                              "kpi": name, "definition": definition.version,
                              "value": None if value is None else str(value)},
                      clock)
        value_ids.append(value_id)
    conn.commit()
    return value_ids


def compute_location_kpis(
    conn: sqlite3.Connection, location_code: str, period: str,
    actor: str = "system",
    clock: Callable[[], str] = utcnow_iso,
) -> dict[str, Optional[str]]:
    """Compute the five KPIs for one location + period (current definitions)."""
    row = conn.execute(
        "SELECT id FROM kpi_locations WHERE code = ?",
        (location_code.strip().lower(),),
    ).fetchone()
    if row is None:
        raise KpiPipelineError(f"Unknown location {location_code!r}")
    location_id = row["id"]
    definitions = kpi_defs.get_current_definitions(conn)
    rows = _staged_rows(conn, period, location_id)
    values = kpi_defs.compute_all(rows, definitions)
    agg = kpi_defs.aggregate(rows)
    _store_values(conn, period, location_id, values, definitions,
                  _agg_inputs(agg), [r["staging_id"] for r in rows],
                  actor, clock)
    return {n: (None if v is None else str(v)) for n, v in values.items()}


def compute_rollup(
    conn: sqlite3.Connection, period: str,
    actor: str = "system",
    clock: Callable[[], str] = utcnow_iso,
) -> dict[str, Optional[str]]:
    """Compute the cross-location rollup KPIs for one period.

    The rollup aggregates every staged row for the period — every
    consolidated number traces to its source rows via kpi_lineage.
    """
    definitions = kpi_defs.get_current_definitions(conn)
    rows = _staged_rows(conn, period, None)
    values = kpi_defs.compute_all(rows, definitions)
    agg = kpi_defs.aggregate(rows)
    _store_values(conn, period, None, values, definitions,
                  _agg_inputs(agg), [r["staging_id"] for r in rows],
                  actor, clock)
    return {n: (None if v is None else str(v)) for n, v in values.items()}


def _agg_inputs(agg: dict) -> dict:
    return {
        "completed_jobs": agg["jobs"],
        "callbacks": agg["callbacks"],
        "revenue": str(agg["revenue"]),
        "costs": str(agg["costs"]),
        "tech_days": str(agg["tech_days"]),
    }


def get_drilldown(conn: sqlite3.Connection, kpi_value_id: int) -> dict:
    """Return a KPI value with every staging row that fed it."""
    value = conn.execute(
        """SELECT v.*, d.name AS def_name, d.version AS def_version,
                  l.code AS location_code
           FROM kpi_values v
           JOIN kpi_definitions d ON d.id = v.definition_id
           LEFT JOIN kpi_locations l ON l.id = v.location_id
           WHERE v.id = ?""",
        (kpi_value_id,),
    ).fetchone()
    if value is None:
        raise KpiPipelineError(f"KPI value {kpi_value_id} not found")
    rows = conn.execute(
        """SELECT s.id, s.job_id, s.completed_date, s.revenue, s.costs,
                  s.is_callback, s.tech_days, s.source_row,
                  loc.code AS location_code
           FROM kpi_lineage g
           JOIN kpi_staging s ON s.id = g.staging_row_id
           JOIN kpi_locations loc ON loc.id = s.location_id
           WHERE g.kpi_value_id = ?
           ORDER BY loc.code, s.source_row""",
        (kpi_value_id,),
    ).fetchall()
    return {"value": dict(value), "rows": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Definition versioning + restatement
# ---------------------------------------------------------------------------


def restate_period(
    conn: sqlite3.Connection, period: str, reason: str,
    actor: str = "system",
    clock: Callable[[], str] = utcnow_iso,
) -> dict:
    """Recompute a period's KPIs under the CURRENT definitions.

    Current values whose definition is no longer current are superseded
    (never deleted): they flip to status='superseded' pointing at the
    restatement row, and fresh rows are computed with full lineage.
    Values whose definition is still current are recomputed in place.
    """
    reason = (reason or "").strip()
    if not reason:
        raise KpiPipelineError("restatement reason is required")
    current_defs = kpi_defs.get_current_definitions(conn)
    restatements = 0
    # Supersede current values computed under an older definition version.
    for name, new_def in current_defs.items():
        old_rows = conn.execute(
            """SELECT v.id, v.definition_id, v.location_id
               FROM kpi_values v
               JOIN kpi_definitions d ON d.id = v.definition_id
               WHERE v.period = ? AND v.kpi_name = ? AND v.status = 'current'
                 AND v.definition_id != ?""",
            (period, name, new_def.id),
        ).fetchall()
        for old in old_rows:
            cur = conn.execute(
                """INSERT INTO kpi_restatements
                   (period, definition_id_old, definition_id_new, reason,
                    actor, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (period, old["definition_id"], new_def.id, reason,
                 actor, clock()),
            )
            restatement_id = cur.lastrowid
            conn.execute(
                "UPDATE kpi_values SET status = 'superseded', "
                "restatement_id = ? WHERE id = ?",
                (restatement_id, old["id"]),
            )
            _record_event(conn, "restatement", restatement_id,
                          "restatement.applied", actor,
                          {"period": period, "kpi": name,
                           "old_definition_id": old["definition_id"],
                           "new_definition_id": new_def.id}, clock)
            restatements += 1
    conn.commit()
    # Recompute: every location that has staged rows, plus the rollup.
    location_ids = [r["location_id"] for r in conn.execute(
        "SELECT DISTINCT location_id FROM kpi_staging WHERE period = ?",
        (period,),
    )]
    codes = {
        r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM kpi_locations")
    }
    recomputed: dict[str, dict[str, Optional[str]]] = {}
    for code, lid in codes.items():
        if lid in location_ids:
            recomputed[code] = compute_location_kpis(
                conn, code, period, actor=actor, clock=clock)
    recomputed["__rollup__"] = compute_rollup(conn, period, actor=actor,
                                              clock=clock)
    return {"restatements": restatements, "recomputed": recomputed}


# ---------------------------------------------------------------------------
# Read helpers (web UI / API)
# ---------------------------------------------------------------------------


def list_locations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT l.id, l.code, l.name, l.active,
                  (SELECT schema_version FROM kpi_schema_maps m
                   WHERE m.location_id = l.id ORDER BY m.id DESC LIMIT 1)
                    AS schema_version
           FROM kpi_locations l ORDER BY l.code"""
    ).fetchall()
    return [dict(r) for r in rows]


def list_quarantine(conn: sqlite3.Connection, period: Optional[str] = None,
                    limit: int = 200) -> list[dict]:
    sql = ("""SELECT q.*, l.code AS location_code FROM kpi_quarantine q
              JOIN kpi_locations l ON l.id = q.location_id""")
    params: list = []
    if period:
        sql += " WHERE q.period = ?"
        params.append(period)
    sql += " ORDER BY q.id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_alerts(conn: sqlite3.Connection, open_only: bool = True,
                limit: int = 200) -> list[dict]:
    sql = ("""SELECT a.*, l.code AS location_code FROM kpi_alerts a
              LEFT JOIN kpi_locations l ON l.id = a.location_id""")
    params: list = []
    if open_only:
        sql += " WHERE a.resolved_at IS NULL"
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_restatements(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """SELECT r.*, do.name AS kpi_name, do.version AS old_version,
                  dn.version AS new_version
           FROM kpi_restatements r
           JOIN kpi_definitions do ON do.id = r.definition_id_old
           JOIN kpi_definitions dn ON dn.id = r.definition_id_new
           ORDER BY r.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_definitions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, version, formula_json, includes_text, excludes_text,"
        " status, created_by, created_at FROM kpi_definitions "
        "ORDER BY name, version"
    ).fetchall()
    return [dict(r) for r in rows]


def dashboard_values(conn: sqlite3.Connection, period: str) -> list[dict]:
    """Current per-location + rollup KPI values for a period."""
    rows = conn.execute(
        """SELECT v.*, l.code AS location_code, d.version AS def_version
           FROM kpi_values v
           LEFT JOIN kpi_locations l ON l.id = v.location_id
           JOIN kpi_definitions d ON d.id = v.definition_id
           WHERE v.period = ? AND v.status = 'current'
           ORDER BY COALESCE(l.code, '~'), v.kpi_name""",
        (period,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_periods(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT period FROM kpi_staging ORDER BY period DESC"
    ).fetchall()
    return [r["period"] for r in rows]


def _record_event(
    conn: sqlite3.Connection, entity_type: str, entity_id: int,
    event_type: str, actor: str, detail: dict,
    clock: Callable[[], str] = utcnow_iso,
) -> int:
    cur = conn.execute(
        """INSERT INTO kpi_events
           (entity_type, entity_id, event_type, actor, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, event_type, actor,
         json.dumps(detail, sort_keys=True), clock()),
    )
    conn.commit()
    return cur.lastrowid
