"""Project Q07 — versioned KPI definitions.

The five standardized KPIs, their documented formulas, and what each
metric includes/excludes. Every definition carries a version label; a
definition is NEVER edited in place — a change inserts a new version and
supersedes the old one, and the restatement log preserves history.

Money is Decimal, never float. Rates are quantized to 6 decimal places
(divisions are exact Decimal divisions followed by quantization so
hand-computations match byte-for-byte).

ALL DATA THIS MODULE PROCESSES IS SYNTHETIC DEMONSTRATION DATA. The
formulas are documented assumptions, not audited financial metrics.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from .db import utcnow_iso

#: The standardized KPI set (spec §2).
KPI_NAMES = (
    "revenue",
    "gross_margin",
    "callback_rate",
    "average_ticket",
    "bookings_per_tech_day",
)

#: Rates/ratios are quantized to this precision after exact division.
RATE_QUANT = Decimal("0.000001")
#: Money totals are quantized to cents.
MONEY_QUANT = Decimal("0.01")

#: v1 definition text: what each metric includes and excludes.
V1_DOCS: dict[str, tuple[str, str, str]] = {
    "revenue": (
        "SUM(revenue) over completed, staged job rows in the period.",
        "Revenue as recorded in each location's CSV (pre-tax as recorded); "
        "completed jobs only (the jobs table is the completed-work log); "
        "quarantined rows are excluded.",
        "Quarantined rows; canceled or quoted-but-not-completed work (not "
        "present in the jobs CSV); overhead not recorded in the source CSV.",
    ),
    "gross_margin": (
        "(SUM(revenue) - SUM(costs)) / SUM(revenue); NULL when revenue = 0.",
        "Job-level revenue and costs exactly as recorded in the source "
        "CSV (the schema map documents which source columns those are); "
        "completed jobs only.",
        "Overhead not present in the source CSV (rent, office salaries); "
        "tax; quarantined rows.",
    ),
    "callback_rate": (
        "COUNT(callback jobs) / COUNT(all completed jobs); NULL when no "
        "completed jobs.",
        "A 'callback job' is any staged row whose is_callback flag is true "
        "(the schema map documents which source column/values that is).",
        "Quarantined rows; first-visit jobs are in the denominator only.",
    ),
    "average_ticket": (
        "SUM(revenue) / COUNT(all completed jobs); NULL when no completed "
        "jobs.",
        "Same revenue and job set as `revenue`; callbacks count as jobs in "
        "the denominator.",
        "Quarantined rows; non-completed work.",
    ),
    "bookings_per_tech_day": (
        "COUNT(all completed jobs) / SUM(tech_days); NULL when total "
        "tech_days = 0.",
        "tech_days as recorded in the source CSV (one technician-day = one "
        "tech on the job for one day, per the schema map's source column).",
        "Quarantined rows; non-completed work.",
    ),
}

#: v2 change: gross_margin deducts a documented callback-rework cost
#: (a flat, disclosed assumption) per callback job from the numerator.
CALLBACK_REWORK_COST = Decimal("50.00")

V2_GROSS_MARGIN_DOC = (
    "(SUM(revenue) - SUM(costs) - 50.00 * COUNT(callback jobs)) / "
    "SUM(revenue); NULL when revenue = 0.",
    "Everything in gross_margin v1, PLUS a documented, flat callback "
    "rework cost of $50.00 per callback job — a disclosed assumption, "
    "not a measured cost.",
    "Same as gross_margin v1. The $50 rework cost is a placeholder "
    "assumption: replace with real rework accounting before using this "
    "for decisions.",
)


class KpiError(Exception):
    """Domain error for KPI definition/computation problems."""


@dataclass(frozen=True)
class KpiDefinition:
    id: int
    name: str
    version: str
    formula: str
    includes: str
    excludes: str
    status: str  # 'current' | 'superseded'


def _quant_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANT)


def compute_kpi(
    name: str,
    version: str,
    revenue: Decimal,
    costs: Decimal,
    jobs: int,
    callbacks: int,
    tech_days: Decimal,
) -> Optional[Decimal]:
    """Compute one KPI from period aggregates using a versioned formula.

    All inputs are already-aggregated Decimals/ints from staged rows.
    Returns None when the formula is undefined (zero denominator).
    """
    if name == "revenue":
        return revenue.quantize(MONEY_QUANT)
    if name == "gross_margin":
        if revenue == 0:
            return None
        if version == "v1":
            return _quant_rate((revenue - costs) / revenue)
        if version == "v2":
            rework = CALLBACK_REWORK_COST * Decimal(callbacks)
            return _quant_rate((revenue - costs - rework) / revenue)
        raise KpiError(f"Unknown version {version!r} for KPI {name!r}")
    if name == "callback_rate":
        if jobs == 0:
            return None
        return _quant_rate(Decimal(callbacks) / Decimal(jobs))
    if name == "average_ticket":
        if jobs == 0:
            return None
        return (revenue / Decimal(jobs)).quantize(MONEY_QUANT)
    if name == "bookings_per_tech_day":
        if tech_days == 0:
            return None
        return _quant_rate(Decimal(jobs) / tech_days)
    raise KpiError(f"Unknown KPI {name!r}")


def aggregate(rows: list[dict]) -> dict:
    """Aggregate staged-row dicts into the five KPI inputs.

    Each row: {'revenue': Decimal, 'costs': Decimal, 'is_callback': bool,
    'tech_days': Decimal}.
    """
    revenue = Decimal("0")
    costs = Decimal("0")
    tech_days = Decimal("0")
    jobs = 0
    callbacks = 0
    for row in rows:
        revenue += row["revenue"]
        costs += row["costs"]
        tech_days += row["tech_days"]
        jobs += 1
        if row["is_callback"]:
            callbacks += 1
    return {
        "revenue": revenue,
        "costs": costs,
        "tech_days": tech_days,
        "jobs": jobs,
        "callbacks": callbacks,
    }


def compute_all(rows: list[dict], definitions: dict[str, KpiDefinition]) -> dict[str, Optional[Decimal]]:
    """Compute every KPI in ``definitions`` (name -> definition) from rows."""
    agg = aggregate(rows)
    return {
        name: compute_kpi(
            name, d.version, agg["revenue"], agg["costs"],
            agg["jobs"], agg["callbacks"], agg["tech_days"],
        )
        for name, d in definitions.items()
    }


# ---------------------------------------------------------------------------
# Definition registry (DB-backed; versioned, never edited in place)
# ---------------------------------------------------------------------------


def seed_default_definitions(
    conn: sqlite3.Connection,
    actor: str = "system",
    clock: Callable[[], str] = utcnow_iso,
) -> list[KpiDefinition]:
    """Insert v1 of all five KPIs (idempotent: skips rows already present)."""
    defs: list[KpiDefinition] = []
    for name in KPI_NAMES:
        formula, includes, excludes = V1_DOCS[name]
        row = conn.execute(
            "SELECT id, name, version, formula_json, includes_text, excludes_text, status "
            "FROM kpi_definitions WHERE name = ? AND version = 'v1'",
            (name,),
        ).fetchone()
        if row is None:
            import json

            cur = conn.execute(
                """INSERT INTO kpi_definitions
                   (name, version, formula_json, includes_text, excludes_text,
                    status, created_by, created_at)
                   VALUES (?, 'v1', ?, ?, ?, 'current', ?, ?)""",
                (name, _formula_json(formula), includes, excludes, actor, clock()),
            )
            defs.append(_from_row(dict(
                id=cur.lastrowid, name=name, version="v1", formula_json=_formula_json(formula),
                includes_text=includes, excludes_text=excludes, status="current",
            )))
        else:
            defs.append(_from_row(dict(row)))
    conn.commit()
    return defs


def _formula_json(formula: str) -> str:
    import json

    return json.dumps(
        {
            "formula": formula,
            "rounding": "money totals to cents (0.01); rates/ratios to 6 "
                        "decimal places after exact Decimal division",
            "money": "Decimal only, never float",
        },
        sort_keys=True,
    )


def _from_row(row: dict) -> KpiDefinition:
    import json

    formula = json.loads(row["formula_json"])["formula"]
    return KpiDefinition(
        id=row["id"], name=row["name"], version=row["version"],
        formula=formula, includes=row["includes_text"],
        excludes=row["excludes_text"], status=row["status"],
    )


def get_current_definitions(conn: sqlite3.Connection) -> dict[str, KpiDefinition]:
    """Return the current definition for each KPI name."""
    defs: dict[str, KpiDefinition] = {}
    for row in conn.execute(
        "SELECT id, name, version, formula_json, includes_text, excludes_text, status "
        "FROM kpi_definitions WHERE status = 'current'"
    ):
        d = _from_row(dict(row))
        defs[d.name] = d
    missing = [n for n in KPI_NAMES if n not in defs]
    if missing:
        raise KpiError(f"No current definition for KPI(s): {', '.join(missing)}")
    return defs


def get_definition(conn: sqlite3.Connection, name: str, version: str) -> KpiDefinition:
    row = conn.execute(
        "SELECT id, name, version, formula_json, includes_text, excludes_text, status "
        "FROM kpi_definitions WHERE name = ? AND version = ?",
        (name, version),
    ).fetchone()
    if row is None:
        raise KpiError(f"No KPI definition for {name!r} version {version!r}")
    return _from_row(dict(row))


def update_definition(
    conn: sqlite3.Connection,
    name: str,
    new_version: str,
    formula: str,
    includes: str,
    excludes: str,
    actor: str = "system",
    clock: Callable[[], str] = utcnow_iso,
) -> KpiDefinition:
    """Version a KPI definition: supersede the current row, insert the new one.

    The old formula row is never edited — history is preserved.
    """
    if name not in KPI_NAMES:
        raise KpiError(f"Unknown KPI {name!r}")
    current = conn.execute(
        "SELECT id FROM kpi_definitions WHERE name = ? AND status = 'current'",
        (name,),
    ).fetchone()
    if current is None:
        raise KpiError(f"No current definition for KPI {name!r}")
    exists = conn.execute(
        "SELECT id FROM kpi_definitions WHERE name = ? AND version = ?",
        (name, new_version),
    ).fetchone()
    if exists is not None:
        raise KpiError(f"Definition {name!r} version {new_version!r} already exists")
    conn.execute(
        "UPDATE kpi_definitions SET status = 'superseded' WHERE id = ?",
        (current["id"],),
    )
    cur = conn.execute(
        """INSERT INTO kpi_definitions
           (name, version, formula_json, includes_text, excludes_text,
            status, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, 'current', ?, ?)""",
        (name, new_version, _formula_json(formula), includes, excludes, actor, clock()),
    )
    conn.commit()
    _record_event(conn, "definition", current["id"], "definition.superseded",
                  actor, {"name": name, "new_version": new_version}, clock)
    return get_definition(conn, name, new_version)


def _record_event(
    conn: sqlite3.Connection, entity_type: str, entity_id: int,
    event_type: str, actor: str, detail: dict,
    clock: Callable[[], str] = utcnow_iso,
) -> int:
    import json

    cur = conn.execute(
        """INSERT INTO kpi_events
           (entity_type, entity_id, event_type, actor, detail_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, event_type, actor,
         json.dumps(detail, sort_keys=True), clock()),
    )
    conn.commit()
    return cur.lastrowid
