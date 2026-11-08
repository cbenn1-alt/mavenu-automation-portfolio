"""Project P04 — SQL Operations Intelligence.

A SQL analytics layer over the portfolio's operational SQLite data.
Queries are structured specs stored as JSON — never raw SQL from a
caller. The compiler maps every identifier through an allow-listed
registry and binds every value as a ``?`` parameter, so no user input
ever reaches SQL text. Averages and rates are computed in Python from
exact COUNT/SUM aggregates (SQLite AVG is never used for money).

ALL DATA THIS MODULE PROCESSES IS SYNTHETIC DEMONSTRATION DATA.
The operational rows analysed (leads, missed calls, estimates,
invoices, payments, documents) are invented fixtures from the other
portfolio projects. This is not a production database, not a BI tool
for real business records, and not a substitute for real reporting
controls. Timings are measured on fixtures only.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import time
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Optional

from .db import utcnow_iso

#: Hard cap on aggregated result rows per execution (fail-closed).
MAX_RESULT_ROWS = 1000
#: Hard cap on source rows returned by a drill-down.
MAX_DRILLDOWN_ROWS = 200
#: Money averages are quantized to cents; rates/scores to 6 places.
MONEY_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.000001")

#: Grain labels: 'none' | 'day' | 'week' | 'month'. Week uses SQLite
#: strftime('%Y-W%W') — Monday-first weeks, week 00 for days before
#: the first Monday. The label is a display bucket, not an ISO week.
GRAINS = ("none", "day", "week", "month")

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _\-]{0,60}$")
_METRIC_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class SqlOpsError(Exception):
    """Domain error for SQL Operations Intelligence problems."""


# ---------------------------------------------------------------------------
# Source registry — the ONLY tables/columns a query may touch.
#
# kind: 'dimension' (group/filter), 'metric' (aggregate input),
#       'both' (dimension or metric). type: 'text' | 'int' | 'money'
#       | 'real'. 'values' lists the allowed values for enum columns;
#       free-text columns have no list (any non-empty string <= 200 chars).
# ---------------------------------------------------------------------------

TABLES: dict[str, dict[str, Any]] = {
    "leads": {
        "date_column": "created_at",
        "id_column": "id",
        "public_id_column": "public_id",
        "columns": {
            "service": {"kind": "dimension", "type": "text",
                        "values": ("hvac", "plumbing", "electrical", "roofing", "landscaping")},
            "state": {"kind": "dimension", "type": "text",
                      "values": ("received", "qualified", "needs_review", "routed",
                                 "booked", "rejected", "cancelled")},
            "zip": {"kind": "dimension", "type": "text"},
            "urgency": {"kind": "dimension", "type": "text",
                        "values": ("standard", "priority")},
            "email": {"kind": "metric", "type": "text"},
        },
    },
    "missed_calls": {
        "date_column": "missed_at",
        "id_column": "id",
        "public_id_column": "public_id",
        "columns": {
            "state": {"kind": "dimension", "type": "text",
                      "values": ("pending", "attempted", "connected", "booked", "lost")},
            "source": {"kind": "dimension", "type": "text",
                       "values": ("csv", "webhook", "demo")},
            "duration_seconds": {"kind": "metric", "type": "int"},
            "urgency_score": {"kind": "metric", "type": "real"},
        },
    },
    "estimates": {
        "date_column": "created_at",
        "id_column": "id",
        "public_id_column": "public_id",
        "columns": {
            "service_type": {"kind": "dimension", "type": "text",
                             "values": ("hvac", "plumbing", "electrical", "roofing", "landscaping")},
            "state": {"kind": "dimension", "type": "text",
                      "values": ("draft", "sent", "viewed", "followed_up",
                                 "accepted", "declined", "expired")},
            "estimator": {"kind": "dimension", "type": "text"},
            "amount_cents": {"kind": "metric", "type": "money"},
        },
    },
    "recon_invoices": {
        "date_column": "issued_date",
        "id_column": "id",
        "public_id_column": "invoice_id",
        "columns": {
            "customer": {"kind": "dimension", "type": "text"},
            "amount_cents": {"kind": "metric", "type": "money"},
        },
    },
    "recon_payments": {
        "date_column": "paid_date",
        "id_column": "id",
        "public_id_column": "payment_id",
        "columns": {
            "customer": {"kind": "dimension", "type": "text"},
            "amount_cents": {"kind": "metric", "type": "money"},
        },
    },
    "docintel_documents": {
        "date_column": "created_at",
        "id_column": "id",
        "public_id_column": "doc_id",
        "columns": {
            "doc_type": {"kind": "dimension", "type": "text",
                         "values": ("invoice", "receipt", "contract")},
            "state": {"kind": "dimension", "type": "text",
                      "values": ("ingested", "needs_review", "accepted", "rejected")},
        },
    },
}

#: Metric kinds and what they need. 'count' takes no column; 'rate'
#: takes a numerator equality filter on a dimension column.
METRIC_KINDS = ("count", "sum", "avg", "min", "max", "distinct", "rate")


# ---------------------------------------------------------------------------
# Spec validation + compilation
# ---------------------------------------------------------------------------

def _validate_iso_date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SqlOpsError(f"{field} must be an ISO date string (YYYY-MM-DD)")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise SqlOpsError(f"{field} must be an ISO date string (YYYY-MM-DD)")
    if len(value) != 10:
        raise SqlOpsError(f"{field} must be an ISO date string (YYYY-MM-DD)")
    return value


def _validate_value(table: str, column: str, value: Any) -> Any:
    """Validate one filter value against the registry. Returns it unchanged."""
    col = TABLES[table]["columns"][column]
    allowed = col.get("values")
    if allowed is not None:
        if not isinstance(value, str) or value not in allowed:
            raise SqlOpsError(
                f"Invalid value {value!r} for {table}.{column}: "
                f"must be one of {', '.join(allowed)}"
            )
        return value
    if col["type"] == "text":
        if not isinstance(value, str) or not value or len(value) > 200:
            raise SqlOpsError(
                f"Invalid value for {table}.{column}: non-empty string <= 200 chars"
            )
        return value
    raise SqlOpsError(f"Column {table}.{column} cannot be used as a filter")


def _validate_filter(table: str, filt: Any) -> dict:
    if not isinstance(filt, dict):
        raise SqlOpsError("Each filter must be an object")
    keys = set(filt)
    if keys != {"column", "op", "value"}:
        raise SqlOpsError("Each filter must have exactly column, op, value")
    column = filt["column"]
    op = filt["op"]
    if column not in TABLES[table]["columns"]:
        raise SqlOpsError(f"Unknown column {column!r} for table {table!r}")
    if TABLES[table]["columns"][column]["kind"] == "metric":
        raise SqlOpsError(f"Column {column!r} is not filterable (metric-only)")
    if op not in ("=", "in"):
        raise SqlOpsError(f"Unsupported filter op {op!r}: use '=' or 'in'")
    if op == "=":
        value = _validate_value(table, column, filt["value"])
    else:
        raw = filt["value"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
            raise SqlOpsError("An 'in' filter needs a list of 1..50 values")
        value = [_validate_value(table, column, v) for v in raw]
    return {"column": column, "op": op, "value": value}


def _validate_metric(table: str, metric: Any) -> dict:
    if not isinstance(metric, dict):
        raise SqlOpsError("Each metric must be an object")
    kind = metric.get("kind")
    if kind not in METRIC_KINDS:
        raise SqlOpsError(f"Unknown metric kind {kind!r}")
    if kind == "count":
        if set(metric) != {"kind"}:
            raise SqlOpsError("A 'count' metric takes no other keys")
        return {"kind": "count"}
    if kind == "rate":
        if set(metric) != {"kind", "name", "numerator"}:
            raise SqlOpsError("A 'rate' metric needs exactly kind, name, numerator")
        name = metric["name"]
        if not isinstance(name, str) or not _METRIC_NAME_RE.fullmatch(name):
            raise SqlOpsError(
                f"Invalid rate name {name!r}: lowercase letters, digits, "
                "underscores, starting with a letter"
            )
        num = metric["numerator"]
        if not isinstance(num, dict) or set(num) != {"column", "value"}:
            raise SqlOpsError("A rate numerator needs exactly column and value")
        column = num["column"]
        if column not in TABLES[table]["columns"]:
            raise SqlOpsError(f"Unknown column {column!r} for table {table!r}")
        if TABLES[table]["columns"][column]["kind"] == "metric":
            raise SqlOpsError(f"Column {column!r} cannot be a rate numerator")
        value = _validate_value(table, column, num["value"])
        return {"kind": "rate", "name": name,
                "numerator": {"column": column, "value": value}}
    # sum / avg / min / max / distinct
    if set(metric) != {"kind", "column"}:
        raise SqlOpsError(f"A {kind!r} metric needs exactly kind and column")
    column = metric["column"]
    if column not in TABLES[table]["columns"]:
        raise SqlOpsError(f"Unknown column {column!r} for table {table!r}")
    col = TABLES[table]["columns"][column]
    if kind == "distinct":
        if col["kind"] == "metric" and col["type"] not in ("text",):
            raise SqlOpsError(f"Column {column!r} cannot be counted distinctly")
    elif col["type"] not in ("int", "money", "real"):
        raise SqlOpsError(
            f"Column {column!r} is {col['type']!r} and cannot be used with {kind!r}"
        )
    return {"kind": kind, "column": column}


def validate_spec(spec: Any) -> dict:
    """Validate a query spec and return its normalized (canonical) form.

    Raises SqlOpsError on anything outside the registry — before any
    SQL is built or executed.
    """
    if not isinstance(spec, dict):
        raise SqlOpsError("Query spec must be an object")
    if set(spec) != {"table", "dimensions", "metrics", "filters", "grain"}:
        raise SqlOpsError(
            "Query spec must have exactly table, dimensions, metrics, "
            "filters, grain"
        )
    table = spec["table"]
    if table not in TABLES:
        raise SqlOpsError(f"Unknown table {table!r}")
    dims = spec["dimensions"]
    if not isinstance(dims, list) or len(dims) > 2:
        raise SqlOpsError("dimensions must be a list of 0..2 column names")
    for d in dims:
        if d not in TABLES[table]["columns"]:
            raise SqlOpsError(f"Unknown column {d!r} for table {table!r}")
        if TABLES[table]["columns"][d]["kind"] == "metric":
            raise SqlOpsError(f"Column {d!r} cannot be a dimension")
    if len(set(dims)) != len(dims):
        raise SqlOpsError("dimensions must be unique")
    metrics = spec["metrics"]
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 5:
        raise SqlOpsError("metrics must be a list of 1..5 metrics")
    metrics = [_validate_metric(table, m) for m in metrics]
    names = [metric_output_name(m) for m in metrics]
    if len(set(names)) != len(names):
        raise SqlOpsError("Metric output names must be unique")
    grain = spec["grain"]
    if grain not in GRAINS:
        raise SqlOpsError(f"Unknown grain {grain!r}: use one of {', '.join(GRAINS)}")
    filters = spec["filters"]
    if not isinstance(filters, list):
        raise SqlOpsError("filters must be a list")
    filters = [_validate_filter(table, f) for f in filters]
    return {
        "table": table,
        "dimensions": list(dims),
        "metrics": metrics,
        "filters": filters,
        "grain": grain,
    }


def metric_output_name(metric: dict) -> str:
    """The output column name for one validated metric."""
    kind = metric["kind"]
    if kind == "count":
        return "count"
    if kind == "rate":
        return metric["name"]
    return f"{kind}_{metric['column']}"


def _grain_expr(table: str, grain: str) -> Optional[str]:
    """SQL expression for a grain bucket over the table's date column."""
    col = f'"{TABLES[table]["date_column"]}"'
    if grain == "day":
        return f"substr(date({col}), 1, 10)"
    if grain == "month":
        return f"substr(date({col}), 1, 7)"
    if grain == "week":
        return f"strftime('%Y-W%W', date({col}))"
    return None


def compile_query(spec: dict, period_start: str, period_end: str) -> tuple[str, list]:
    """Compile a validated spec + period into parameterized SQL.

    Identifiers come only from the registry (never from caller input);
    every value is a ``?`` parameter. Returns (sql, params).
    """
    spec = validate_spec(spec)
    period_start = _validate_iso_date(period_start, "period_start")
    period_end = _validate_iso_date(period_end, "period_end")
    if period_start > period_end:
        raise SqlOpsError("period_start must be on or before period_end")
    table = spec["table"]
    date_col = TABLES[table]["date_column"]
    select: list[str] = []
    group_by: list[str] = []
    grain_expr = _grain_expr(table, spec["grain"])
    if grain_expr is not None:
        select.append(f"{grain_expr} AS period")
        group_by.append(grain_expr)
    for dim in spec["dimensions"]:
        select.append(f'"{dim}"')
        group_by.append(f'"{dim}"')
    # Hidden helper aggregates: avg/rate need SUM + COUNT from SQL;
    # the Python layer turns them into exact Decimals.
    # NOTE: parameters are bound in SQL-text order — SELECT-list
    # placeholders (rate numerators) come before WHERE placeholders.
    select_params: list = []
    for metric in spec["metrics"]:
        kind = metric["kind"]
        if kind == "count":
            select.append("COUNT(*) AS count")
        elif kind == "sum":
            select.append(f"SUM(\"{metric['column']}\") AS {metric_output_name(metric)}")
        elif kind == "min":
            select.append(f"MIN(\"{metric['column']}\") AS {metric_output_name(metric)}")
        elif kind == "max":
            select.append(f"MAX(\"{metric['column']}\") AS {metric_output_name(metric)}")
        elif kind == "distinct":
            select.append(
                f"COUNT(DISTINCT \"{metric['column']}\") AS {metric_output_name(metric)}"
            )
        elif kind == "avg":
            select.append(f"SUM(\"{metric['column']}\") AS _avg_{metric['column']}_sum")
            select.append(f"COUNT(\"{metric['column']}\") AS _avg_{metric['column']}_n")
        elif kind == "rate":
            num = metric["numerator"]
            select.append(
                f"SUM(CASE WHEN \"{num['column']}\" = ? THEN 1 ELSE 0 END) "
                f"AS _rate_{metric['name']}_num"
            )
            select_params.append(num["value"])
    select.append("COUNT(*) AS _row_count")
    where = [f"date(\"{date_col}\") >= ?", f"date(\"{date_col}\") <= ?"]
    where_params: list = [period_start, period_end]
    for filt in spec["filters"]:
        if filt["op"] == "=":
            where.append(f"\"{filt['column']}\" = ?")
            where_params.append(filt["value"])
        else:
            placeholders = ", ".join("?" for _ in filt["value"])
            where.append(f"\"{filt['column']}\" IN ({placeholders})")
            where_params.extend(filt["value"])
    sql = (
        f"SELECT {', '.join(select)} FROM \"{table}\" "
        f"WHERE {' AND '.join(where)}"
    )
    if group_by:
        sql += f" GROUP BY {', '.join(group_by)} ORDER BY {', '.join(group_by)}"
    return sql, select_params + where_params


def _quantize_avg(column: str, table: str, value: Decimal) -> Decimal:
    col_type = TABLES[table]["columns"][column]["type"]
    if col_type == "money":
        return value.quantize(MONEY_QUANT)
    if col_type == "int":
        return value.quantize(MONEY_QUANT)
    return value.quantize(RATE_QUANT)


def _finalize_row(spec: dict, row: dict) -> dict:
    """Turn one raw SQL row into a result row: strip helpers, finish avgs/rates."""
    table = spec["table"]
    dims: dict[str, Any] = {}
    if spec["grain"] != "none":
        dims["period"] = row["period"]
    for dim in spec["dimensions"]:
        dims[dim] = row[dim]
    metrics: dict[str, Any] = {}
    for metric in spec["metrics"]:
        kind = metric["kind"]
        out = metric_output_name(metric)
        if kind == "count":
            metrics[out] = row["count"]
        elif kind in ("sum", "min", "max", "distinct"):
            metrics[out] = row[out]
        elif kind == "avg":
            total = row[f"_avg_{metric['column']}_sum"]
            n = row[f"_avg_{metric['column']}_n"]
            if total is None or n == 0:
                metrics[out] = None
            else:
                # str() first: SUM of a REAL column is a float, and
                # Decimal(float) would carry binary noise into the result.
                metrics[out] = _quantize_avg(
                    metric["column"], table, Decimal(str(total)) / Decimal(n)
                )
        elif kind == "rate":
            num = row[f"_rate_{metric['name']}_num"]
            den = row["_row_count"]
            if den == 0 or num is None:
                metrics[out] = None
            else:
                metrics[out] = (Decimal(num) / Decimal(den)).quantize(RATE_QUANT)
    return {"dimensions": dims, "metrics": metrics}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _execute(
    conn: sqlite3.Connection, spec: dict, period_start: str, period_end: str,
    max_rows: int = MAX_RESULT_ROWS,
) -> list[dict]:
    """Compile + execute, returning finalized result rows (no run recorded)."""
    sql, params = compile_query(spec, period_start, period_end)
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    raw = cur.fetchall()
    if len(raw) > max_rows:
        raise SqlOpsError(
            f"Result has {len(raw)} groups, over the {max_rows} cap — "
            "narrow the period or add a filter"
        )
    return [_finalize_row(spec, dict(zip(cols, r))) for r in raw]


# ---------------------------------------------------------------------------
# Query lifecycle (versioned, never edited in place)
# ---------------------------------------------------------------------------

def _record_event(
    conn: sqlite3.Connection, entity_type: str, entity_id: int,
    event_type: str, actor: str, detail: Optional[dict] = None,
    clock: Callable[[], str] = utcnow_iso,
) -> int:
    cur = conn.execute(
        """INSERT INTO sqlops_events
           (entity_type, entity_id, event_type, actor, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, event_type, actor,
         json.dumps(detail or {}, sort_keys=True), clock()),
    )
    conn.commit()
    return cur.lastrowid


def _check_actor(actor: str) -> str:
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
        raise SqlOpsError("actor must be a non-empty string <= 100 chars")
    return actor.strip()


def create_query(
    conn: sqlite3.Connection, name: str, spec: Any, description: str = "",
    actor: str = "system",
) -> dict:
    """Save a new query as version 1 (current). Raises on bad spec/name."""
    actor = _check_actor(actor)
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise SqlOpsError(
            "Query name must start with a letter and contain only letters, "
            "digits, spaces, underscores, hyphens (<= 60 chars)"
        )
    if not isinstance(description, str) or len(description) > 500:
        raise SqlOpsError("description must be a string <= 500 chars")
    spec = validate_spec(spec)
    exists = conn.execute(
        "SELECT id FROM sqlops_queries WHERE name = ?", (name,)
    ).fetchone()
    if exists is not None:
        raise SqlOpsError(f"A query named {name!r} already exists — supersede it instead")
    cur = conn.execute(
        """INSERT INTO sqlops_queries
           (name, description, spec_json, version, status, created_by, created_at)
           VALUES (?, ?, ?, 1, 'current', ?, ?)""",
        (name, description, json.dumps(spec, sort_keys=True), actor, utcnow_iso()),
    )
    conn.commit()
    _record_event(conn, "query", cur.lastrowid, "query.created",
                  actor, {"name": name, "version": 1})
    return get_query(conn, name)


def get_query_by_id(conn: sqlite3.Connection, query_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM sqlops_queries WHERE id = ?", (query_id,)
    ).fetchone()
    if row is None:
        raise SqlOpsError(f"No query with id {query_id}")
    return _query_dict(row)


def get_query(conn: sqlite3.Connection, name: str, version: Optional[int] = None) -> dict:
    if version is None:
        row = conn.execute(
            "SELECT * FROM sqlops_queries WHERE name = ? AND status = 'current'",
            (name,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM sqlops_queries WHERE name = ? AND version = ?",
            (name, version),
        ).fetchone()
    if row is None:
        raise SqlOpsError(f"No query named {name!r}" + (f" version {version}" if version else ""))
    return _query_dict(row)


def _query_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "spec": json.loads(row["spec_json"]),
        "version": row["version"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "superseded_by": row["superseded_by"],
    }


def list_queries(conn: sqlite3.Connection, include_superseded: bool = False) -> list[dict]:
    sql = "SELECT * FROM sqlops_queries"
    if not include_superseded:
        sql += " WHERE status = 'current'"
    sql += " ORDER BY name, version"
    return [_query_dict(r) for r in conn.execute(sql)]


def supersede_query(
    conn: sqlite3.Connection, name: str, spec: Any, actor: str = "system",
) -> dict:
    """Replace a query's spec with a new version; the old version is kept."""
    actor = _check_actor(actor)
    spec = validate_spec(spec)
    current = get_query(conn, name)
    new_version = current["version"] + 1
    cur = conn.execute(
        """INSERT INTO sqlops_queries
           (name, description, spec_json, version, status, created_by, created_at)
           VALUES (?, ?, ?, ?, 'current', ?, ?)""",
        (name, current["description"], json.dumps(spec, sort_keys=True),
         new_version, actor, utcnow_iso()),
    )
    conn.execute(
        "UPDATE sqlops_queries SET status = 'superseded', superseded_by = ? WHERE id = ?",
        (cur.lastrowid, current["id"]),
    )
    conn.commit()
    _record_event(conn, "query", cur.lastrowid, "query.superseded",
                  actor, {"name": name, "new_version": new_version,
                          "previous_version": current["version"]})
    return get_query(conn, name)


# ---------------------------------------------------------------------------
# Execution, runs, drill-down, compare, snapshots, export
# ---------------------------------------------------------------------------

def run_query(
    conn: sqlite3.Connection, query_id: int, period_start: str, period_end: str,
    actor: str = "system", max_rows: int = MAX_RESULT_ROWS,
) -> dict:
    """Execute a saved query over a period and record the run (audit).

    Failed executions are recorded too (status 'error'), so the run
    history is a truthful record of what was attempted.
    """
    actor = _check_actor(actor)
    started = time.monotonic()
    row = conn.execute(
        "SELECT * FROM sqlops_queries WHERE id = ?", (query_id,)
    ).fetchone()
    if row is None:
        raise SqlOpsError(f"No query with id {query_id}")
    query = _query_dict(row)
    spec = query["spec"]
    try:
        results = _execute(conn, spec, period_start, period_end, max_rows=max_rows)
        status, error_text = "ok", None
    except SqlOpsError as exc:
        results, status, error_text = [], "error", str(exc)
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    cur = conn.execute(
        """INSERT INTO sqlops_runs
           (query_id, query_version, spec_json, period_start, period_end,
            status, rows_returned, duration_ms, result_json, error_text,
            actor, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (query_id, query["version"], json.dumps(spec, sort_keys=True),
         period_start, period_end, status, len(results), duration_ms,
         json.dumps(_jsonable(results), sort_keys=True), error_text,
         actor, utcnow_iso()),
    )
    conn.commit()
    _record_event(conn, "run", cur.lastrowid,
                  "run.error" if status == "error" else "run.ok",
                  actor, {"query_id": query_id, "version": query["version"]})
    run = get_run(conn, cur.lastrowid)
    if status == "error":
        raise SqlOpsError(error_text or "Query execution failed")
    return run


def get_run(conn: sqlite3.Connection, run_id: int) -> dict:
    row = conn.execute("SELECT * FROM sqlops_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise SqlOpsError(f"No run with id {run_id}")
    return {
        "id": row["id"],
        "query_id": row["query_id"],
        "query_version": row["query_version"],
        "spec": json.loads(row["spec_json"]),
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "status": row["status"],
        "rows_returned": row["rows_returned"],
        "duration_ms": row["duration_ms"],
        "results": json.loads(row["result_json"]),
        "error_text": row["error_text"],
        "actor": row["actor"],
        "created_at": row["created_at"],
    }


def list_runs(conn: sqlite3.Connection, query_id: Optional[int] = None) -> list[dict]:
    if query_id is None:
        rows = conn.execute("SELECT * FROM sqlops_runs ORDER BY id DESC")
    else:
        rows = conn.execute(
            "SELECT * FROM sqlops_runs WHERE query_id = ? ORDER BY id DESC",
            (query_id,),
        )
    return [get_run(conn, r["id"]) for r in rows]


def drill_down(
    conn: sqlite3.Connection, run_id: int, dimension: str, value: Any,
    actor: str = "system", limit: int = MAX_DRILLDOWN_ROWS,
) -> dict:
    """Lineage: return the source rows behind one result group of a run.

    ``dimension`` is a dimension of the run's spec (or 'period' for a
    grain bucket); ``value`` is the group value. Returns at most
    ``limit`` source rows, ordered by date then id. The row columns
    are the registry columns only — no hashed identifiers or audit
    tables leak through (caller_id_hash is not in the registry at all).
    """
    actor = _check_actor(actor)
    run = get_run(conn, run_id)
    spec = run["spec"]
    table = spec["table"]
    date_col = TABLES[table]["date_column"]
    extra_where: list[str] = []
    params: list = [run["period_start"], run["period_end"]]
    if dimension == "period" and spec["grain"] != "none":
        grain = spec["grain"]
        if not isinstance(value, str):
            raise SqlOpsError("A period drill-down value must be a string bucket")
        if grain == "day":
            extra_where.append(f"date(\"{date_col}\") = ?")
        elif grain == "month":
            extra_where.append(f"substr(date(\"{date_col}\"), 1, 7) = ?")
        else:  # week
            extra_where.append(f"strftime('%Y-W%W', date(\"{date_col}\")) = ?")
        params.append(value)
    elif dimension in spec["dimensions"]:
        if value is None:
            extra_where.append(f"\"{dimension}\" IS NULL")
        else:
            _validate_value(table, dimension, value)
            extra_where.append(f"\"{dimension}\" = ?")
            params.append(value)
    else:
        raise SqlOpsError(
            f"Cannot drill down on {dimension!r}: not a dimension of this run"
        )
    # Apply the run's own filters too, so the rows match the group.
    for filt in spec["filters"]:
        if filt["op"] == "=":
            extra_where.append(f"\"{filt['column']}\" = ?")
            params.append(filt["value"])
        else:
            placeholders = ", ".join("?" for _ in filt["value"])
            extra_where.append(f"\"{filt['column']}\" IN ({placeholders})")
            params.extend(filt["value"])
    cols = [TABLES[table]["public_id_column"], date_col]
    for dim in spec["dimensions"]:
        if dim not in cols:
            cols.append(dim)
    for metric in spec["metrics"]:
        if metric["kind"] in ("sum", "avg", "min", "max", "distinct"):
            if metric["column"] not in cols:
                cols.append(metric["column"])
    select = ", ".join(f'"{c}"' for c in cols)
    where = [f"date(\"{date_col}\") >= ?", f"date(\"{date_col}\") <= ?"] + extra_where
    sql = (
        f"SELECT {select} FROM \"{table}\" WHERE {' AND '.join(where)} "
        f"ORDER BY date(\"{date_col}\"), \"{TABLES[table]['id_column']}\" LIMIT ?"
    )
    params.append(limit + 1)
    cur = conn.execute(sql, params)
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    truncated = len(rows) > limit
    rows = rows[:limit]
    _record_event(conn, "run", run_id, "run.drill_down", actor,
                  {"dimension": dimension, "value": value, "rows": len(rows)})
    return {
        "run_id": run_id,
        "dimension": dimension,
        "value": value,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


def compare_periods(
    conn: sqlite3.Connection, query_id: int,
    period_a: tuple[str, str], period_b: tuple[str, str],
    actor: str = "system", max_rows: int = MAX_RESULT_ROWS,
) -> dict:
    """Run one query over two periods and return per-group deltas.

    Both executions are recorded as runs. Delta = B − A; percent change
    is NULL when A is 0 or NULL (division by zero is never invented).
    """
    actor = _check_actor(actor)
    run_a = run_query(conn, query_id, period_a[0], period_a[1], actor=actor, max_rows=max_rows)
    run_b = run_query(conn, query_id, period_b[0], period_b[1], actor=actor, max_rows=max_rows)

    def key(result_row: dict) -> str:
        return json.dumps(result_row["dimensions"], sort_keys=True, default=str)

    by_key_a = {key(r): r for r in run_a["results"]}
    by_key_b = {key(r): r for r in run_b["results"]}
    rows = []
    for k in sorted(set(by_key_a) | set(by_key_b)):
        ra = by_key_a.get(k)
        rb = by_key_b.get(k)
        dims = (ra or rb)["dimensions"]
        metric_names = set()
        if ra:
            metric_names |= set(ra["metrics"])
        if rb:
            metric_names |= set(rb["metrics"])
        metrics = {}
        for name in sorted(metric_names):
            a = ra["metrics"].get(name) if ra else None
            b = rb["metrics"].get(name) if rb else None
            delta = pct = None
            if a is not None and b is not None:
                delta = _decimal_sub(b, a)
                da = Decimal(str(a))
                if da != 0:
                    pct = ((Decimal(str(b)) - da) / da * 100).quantize(RATE_QUANT)
            metrics[name] = {"a": a, "b": b, "delta": delta, "pct": pct}
        rows.append({"dimensions": dims, "metrics": metrics})
    return {
        "query_id": query_id,
        "query_version": run_b["query_version"],
        "period_a": {"start": period_a[0], "end": period_a[1], "run_id": run_a["id"]},
        "period_b": {"start": period_b[0], "end": period_b[1], "run_id": run_b["id"]},
        "rows": rows,
    }


def _decimal_sub(b: Any, a: Any) -> Any:
    """b − a preserving int-ness for ints, Decimal for decimals."""
    if isinstance(a, int) and isinstance(b, int):
        return b - a
    return (Decimal(str(b)) - Decimal(str(a)))


def _fingerprint(spec: dict, period_start: str, period_end: str, results: list) -> str:
    payload = json.dumps(
        {"spec": spec, "period": [period_start, period_end], "results": results},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def snapshot_run(conn: sqlite3.Connection, run_id: int, actor: str = "system") -> dict:
    """Materialise a run's result as a snapshot with a fingerprint."""
    actor = _check_actor(actor)
    run = get_run(conn, run_id)
    if run["status"] != "ok":
        raise SqlOpsError("Cannot snapshot a failed run")
    fp = _fingerprint(run["spec"], run["period_start"], run["period_end"], run["results"])
    cur = conn.execute(
        """INSERT INTO sqlops_snapshots
           (run_id, query_id, query_version, fingerprint, result_json,
            row_count, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, run["query_id"], run["query_version"], fp,
         json.dumps(run["results"], sort_keys=True),
         run["rows_returned"], actor, utcnow_iso()),
    )
    conn.commit()
    _record_event(conn, "snapshot", cur.lastrowid, "snapshot.created",
                  actor, {"run_id": run_id, "fingerprint": fp})
    return get_snapshot(conn, cur.lastrowid)


def get_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM sqlops_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if row is None:
        raise SqlOpsError(f"No snapshot with id {snapshot_id}")
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "query_id": row["query_id"],
        "query_version": row["query_version"],
        "fingerprint": row["fingerprint"],
        "results": json.loads(row["result_json"]),
        "row_count": row["row_count"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


def snapshot_status(conn: sqlite3.Connection, snapshot_id: int) -> dict:
    """Re-execute the snapshot's query over its period: 'current' or 'stale'.

    Staleness means the answer changed — the fingerprint covers the
    spec, the period, and the result rows. This check does not write
    a run row (it is a read, not an execution to audit).
    """
    snap = get_snapshot(conn, snapshot_id)
    run = get_run(conn, snap["run_id"])
    current = _execute(conn, run["spec"], run["period_start"], run["period_end"])
    fp = _fingerprint(run["spec"], run["period_start"], run["period_end"],
                      _jsonable(current))
    return {
        "snapshot_id": snapshot_id,
        "status": "current" if fp == snap["fingerprint"] else "stale",
        "fingerprint": snap["fingerprint"],
        "current_fingerprint": fp,
    }


def export_run(conn: sqlite3.Connection, run_id: int, fmt: str) -> str:
    """Export a run's result as CSV or JSON text."""
    run = get_run(conn, run_id)
    if fmt == "json":
        return json.dumps(run["results"], indent=2, sort_keys=True, default=str)
    if fmt == "csv":
        results = run["results"]
        dim_keys: list[str] = []
        metric_keys: list[str] = []
        for r in results:
            for k in r["dimensions"]:
                if k not in dim_keys:
                    dim_keys.append(k)
            for k in r["metrics"]:
                if k not in metric_keys:
                    metric_keys.append(k)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(dim_keys + metric_keys)
        for r in results:
            writer.writerow(
                [r["dimensions"].get(k) for k in dim_keys]
                + [r["metrics"].get(k) for k in metric_keys]
            )
        return buf.getvalue()
    raise SqlOpsError(f"Unknown export format {fmt!r}: use 'csv' or 'json'")


def query_history(conn: sqlite3.Connection, query_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM sqlops_events WHERE entity_type = 'query' AND entity_id = ? ORDER BY id",
        (query_id,),
    )
    return [
        {"id": r["id"], "event_type": r["event_type"], "actor": r["actor"],
         "detail": json.loads(r["detail_json"]), "created_at": r["created_at"]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Demo seed data — deterministic synthetic fixtures with a hand-computed
# oracle (see projects/project04/TEST_PLAN.md). Idempotent: a second
# call inserts nothing.
# ---------------------------------------------------------------------------

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seed_demo_data(conn: sqlite3.Connection, actor: str = "demo") -> dict:
    """Insert the P04 demo dataset. Returns counts inserted per table."""
    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM leads WHERE public_id LIKE 'LD-SQL-%'"
    ).fetchone()["c"]
    if existing:
        return {"already_seeded": True, "inserted": {}}
    now = utcnow_iso()

    def ts(d: str) -> str:
        return f"{d}T12:00:00+00:00"

    leads = [
        ("LD-SQL-001", "Dana Rivera", "hvac", "58102", "qualified", "2026-10-05"),
        ("LD-SQL-002", "Sam Chen", "hvac", "58102", "qualified", "2026-10-12"),
        ("LD-SQL-003", "Priya Nair", "plumbing", "58103", "received", "2026-10-06"),
        ("LD-SQL-004", "Omar Haddad", "plumbing", "58102", "booked", "2026-10-20"),
        ("LD-SQL-005", "Lee Park", "electrical", "58103", "qualified", "2026-10-21"),
        ("LD-SQL-006", "Ana Ruiz", "electrical", "58102", "rejected", "2026-10-22"),
        ("LD-SQL-007", "Tom Becker", "hvac", "58103", "booked", "2026-11-02"),
        ("LD-SQL-008", "Mia Torres", "roofing", "58102", "received", "2026-11-03"),
    ]
    for i, (pid, name, service, zipc, state, d) in enumerate(leads):
        phone = f"70155501{i:02d}"
        email = f"{name.lower().replace(' ', '.')}@example.com"
        conn.execute(
            """INSERT INTO leads
               (public_id, name, phone, email, service, zip, notes, urgency,
                state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, '', 'standard', ?, ?, ?)""",
            (pid, name, phone, email, service, zipc, state, ts(d), ts(d)),
        )
    calls = [
        ("MC-SQL-001", "2026-10-05", "pending", 45, 0.90),
        ("MC-SQL-002", "2026-10-06", "booked", 120, 0.80),
        ("MC-SQL-003", "2026-10-07", "lost", 30, 0.30),
        ("MC-SQL-004", "2026-10-20", "connected", 90, 0.60),
        ("MC-SQL-005", "2026-10-21", "booked", 150, 0.85),
        ("MC-SQL-006", "2026-11-03", "pending", 60, 0.50),
    ]
    for pid, d, state, dur, urg in calls:
        h = _sha(f"555010{pid[-3:]}")
        conn.execute(
            """INSERT INTO missed_calls
               (public_id, missed_at, caller_id_masked, caller_id_hash,
                duration_seconds, urgency_score, state, dedup_key,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, ts(d), f"••••••{pid[-4:]}", h, dur, urg, state,
             f"{h}|{ts(d)}", ts(d), ts(d)),
        )
    estimates = [
        ("EST-SQL-001", "Acme Test Co", "hvac", "Dana", 150000, "accepted", "2026-10-08"),
        ("EST-SQL-002", "Acme Test Co", "hvac", "Dana", 80000, "sent", "2026-10-09"),
        ("EST-SQL-003", "Beta Fixtures LLC", "plumbing", "Sam", 220000, "accepted", "2026-10-15"),
        ("EST-SQL-004", "Beta Fixtures LLC", "plumbing", "Sam", 95000, "declined", "2026-10-16"),
        ("EST-SQL-005", "Acme Test Co", "electrical", "Dana", 310000, "accepted", "2026-10-28"),
        ("EST-SQL-006", "Acme Test Co", "hvac", "Sam", 120000, "sent", "2026-11-04"),
    ]
    for pid, cust, service, est, cents, state, d in estimates:
        conn.execute(
            """INSERT INTO estimates
               (public_id, customer_name, service_type, estimator, amount_cents,
                state, sent_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, cust, service, est, cents, state, ts(d), ts(d), ts(d)),
        )
    invoices = [
        ("INV-SQL-001", "Acme Test Co", 50000, "2026-10-02", "2026-10-16"),
        ("INV-SQL-002", "Acme Test Co", 75000, "2026-10-03", "2026-10-17"),
        ("INV-SQL-003", "Beta Fixtures LLC", 120000, "2026-10-10", "2026-10-24"),
        ("INV-SQL-004", "Beta Fixtures LLC", 30000, "2026-10-20", "2026-11-03"),
        ("INV-SQL-005", "Acme Test Co", 90000, "2026-11-02", "2026-11-16"),
    ]
    for iid, cust, cents, issued, due in invoices:
        conn.execute(
            """INSERT INTO recon_invoices
               (invoice_id, customer, amount_cents, issued_date, due_date,
                source_row, ingest_batch, created_at)
               VALUES (?, ?, ?, ?, ?, 1, 'sqlops-demo', ?)""",
            (iid, cust, cents, issued, due, now),
        )
    payments = [
        ("PAY-SQL-001", "Acme Test Co", 50000, "2026-10-05"),
        ("PAY-SQL-002", "Acme Test Co", 75000, "2026-10-06"),
        ("PAY-SQL-003", "Beta Fixtures LLC", 120000, "2026-10-12"),
        ("PAY-SQL-004", "Beta Fixtures LLC", 30000, "2026-11-01"),
    ]
    for pid, cust, cents, paid in payments:
        conn.execute(
            """INSERT INTO recon_payments
               (payment_id, customer, amount_cents, paid_date,
                source_row, ingest_batch, created_at)
               VALUES (?, ?, ?, ?, 1, 'sqlops-demo', ?)""",
            (pid, cust, cents, paid, now),
        )
    docs = [
        ("DOC-SQL-001", "invoice", "accepted", "2026-10-04"),
        ("DOC-SQL-002", "invoice", "needs_review", "2026-10-05"),
        ("DOC-SQL-003", "receipt", "accepted", "2026-10-18"),
        ("DOC-SQL-004", "contract", "needs_review", "2026-11-05"),
    ]
    for did, dtype, state, d in docs:
        conn.execute(
            """INSERT INTO docintel_documents
               (doc_id, doc_type, source_format, source_text, state, actor,
                created_at, updated_at)
               VALUES (?, ?, 'text', 'synthetic fixture', ?, ?, ?, ?)""",
            (did, dtype, state, actor, ts(d), ts(d)),
        )
    conn.commit()
    return {
        "already_seeded": False,
        "inserted": {
            "leads": len(leads), "missed_calls": len(calls),
            "estimates": len(estimates), "recon_invoices": len(invoices),
            "recon_payments": len(payments), "docintel_documents": len(docs),
        },
    }
