"""Tests for Q07 — Multi-Location KPI Rollup Pipeline.

All location names, job IDs, revenue/cost figures, and tech-day counts
below are synthetic fixture data. No real businesses, no real financials.

Fixture design (intentional schema differences per location):
- north: ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days
- south: Job #,Service Date,Amount,Expenses,CB,CrewDays
- west:  id,completed,total,parts_labor,return_visit,days
Each fixture CSV has 1 planted bad row (quarantined with a reason).
"""
import csv
import io
from decimal import Decimal

import pytest

from mavenu import kpi_defs, kpi_pipeline as kp
from mavenu.db import rollback_migration, run_migrations

PERIOD = "2026-09"

NORTH_MAP = {
    "job_id": "ticket_id", "completed_date": "date", "revenue": "rev_usd",
    "costs": "cost_usd", "is_callback": "callback_flag",
    "tech_days": "tech_days",
}
SOUTH_MAP = {
    "job_id": "Job #", "completed_date": "Service Date", "revenue": "Amount",
    "costs": "Expenses", "is_callback": "CB", "tech_days": "CrewDays",
}
WEST_MAP = {
    "job_id": "id", "completed_date": "completed", "revenue": "total",
    "costs": "parts_labor", "is_callback": "return_visit",
    "tech_days": "days",
}

NORTH_CSV = (
    "ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days\n"
    "T-100,2026-09-03,450.00,180.00,N,1.0\n"
    "T-101,2026-09-05,275.50,120.00,Y,0.5\n"
    "T-102,2026-09-08,620.00,200.00,N,1.0\n"
    "T-103,2026-09-10,abc,50.00,N,1.0\n"          # bad revenue -> quarantine
)

SOUTH_CSV = (
    "Job #,Service Date,Amount,Expenses,CB,CrewDays\n"
    "9001,2026-09-04,300.00,90.00,no,0.5\n"
    "9002,2026-09-07,525.25,210.00,yes,1.0\n"
    ",2026-09-09,150.00,40.00,no,0.5\n"            # missing job id -> quarantine
)

WEST_CSV = (
    "id,completed,total,parts_labor,return_visit,days\n"
    "W-1,2026-09-02,800.00,320.00,0,2.0\n"
    "W-2,2026-09-11,199.99,75.00,1,0.5\n"
)

# Hand-computed aggregates (literal fixture arithmetic).
NORTH = {"jobs": 3, "revenue": Decimal("1345.50"), "costs": Decimal("500.00"),
         "callbacks": 1, "tech_days": Decimal("2.5")}
SOUTH = {"jobs": 2, "revenue": Decimal("825.25"), "costs": Decimal("300.00"),
         "callbacks": 1, "tech_days": Decimal("1.5")}
WEST = {"jobs": 2, "revenue": Decimal("999.99"), "costs": Decimal("395.00"),
        "callbacks": 1, "tech_days": Decimal("2.5")}
ROLLUP = {"jobs": 7, "revenue": Decimal("3170.74"), "costs": Decimal("1195.00"),
          "callbacks": 3, "tech_days": Decimal("6.5")}

Q = Decimal("0.000001")


def _hand(agg):
    """Hand-compute the v1 KPI set from literal aggregates."""
    rev, costs, jobs, cb, td = (agg["revenue"], agg["costs"], agg["jobs"],
                                agg["callbacks"], agg["tech_days"])
    return {
        "revenue": rev.quantize(Decimal("0.01")),
        "gross_margin": ((rev - costs) / rev).quantize(Q),
        "callback_rate": (Decimal(cb) / Decimal(jobs)).quantize(Q),
        "average_ticket": (rev / Decimal(jobs)).quantize(Decimal("0.01")),
        "bookings_per_tech_day": (Decimal(jobs) / td).quantize(Q),
    }


@pytest.fixture
def seeded(conn):
    kp.register_location(conn, "north", "North Shop", NORTH_MAP,
                         actor="tester")
    kp.register_location(conn, "south", "South Shop", SOUTH_MAP,
                         actor="tester")
    kp.register_location(conn, "west", "West Shop", WEST_MAP,
                         actor="tester")
    kpi_defs.seed_default_definitions(conn, actor="tester")
    return conn


@pytest.fixture
def ingested(seeded):
    conn = seeded
    kp.ingest_csv(conn, "north", PERIOD, NORTH_CSV, actor="tester")
    kp.ingest_csv(conn, "south", PERIOD, SOUTH_CSV, actor="tester")
    kp.ingest_csv(conn, "west", PERIOD, WEST_CSV, actor="tester")
    return conn


# ---------------------------------------------------------------------------
# Registration / schema-map config
# ---------------------------------------------------------------------------

def test_register_location_requires_all_canonical_fields(conn):
    bad = dict(NORTH_MAP)
    del bad["costs"]
    with pytest.raises(kp.KpiPipelineError, match="missing canonical"):
        kp.register_location(conn, "x", "X Shop", bad)


def test_register_location_rejects_unknown_canonical_field(conn):
    bad = dict(NORTH_MAP)
    bad["bogus"] = "col"
    with pytest.raises(kp.KpiPipelineError, match="unknown canonical"):
        kp.register_location(conn, "x", "X Shop", bad)


def test_register_location_idempotent_reregister(conn):
    a = kp.register_location(conn, "north", "North Shop", NORTH_MAP)
    b = kp.register_location(conn, "north", "North Shop", NORTH_MAP)
    assert a == b


# ---------------------------------------------------------------------------
# Ingest + validation + quarantine
# ---------------------------------------------------------------------------

def test_ingest_stages_good_rows_and_quarantines_bad(seeded):
    conn = seeded
    stats = kp.ingest_csv(conn, "north", PERIOD, NORTH_CSV, actor="tester")
    assert stats["staged"] == 3
    assert stats["quarantined"] == 1
    assert stats["alerts"] == 0
    rows = kp.list_quarantine(conn, period=PERIOD)
    assert len(rows) == 1
    assert rows[0]["source_row"] == 4
    assert rows[0]["reason"] == "invalid_revenue:abc"


def test_ingest_missing_job_id_quarantined(seeded):
    conn = seeded
    stats = kp.ingest_csv(conn, "south", PERIOD, SOUTH_CSV, actor="tester")
    assert stats["staged"] == 2
    assert stats["quarantined"] == 1
    rows = kp.list_quarantine(conn, period=PERIOD)
    assert rows[0]["reason"] == "missing_job_id"


def test_zero_silent_drops_every_row_staged_or_quarantined_with_reason(seeded):
    conn = seeded
    for code, csv_text, n_rows in (("north", NORTH_CSV, 4),
                                   ("south", SOUTH_CSV, 3),
                                   ("west", WEST_CSV, 2)):
        stats = kp.ingest_csv(conn, code, PERIOD, csv_text, actor="tester")
        # every input data row is staged or quarantined (row-level entries)
        row_quarantined = sum(
            1 for q in kp.list_quarantine(conn, period=PERIOD)
            if q["location_code"] == code and q["source_row"] is not None)
        assert stats["staged"] + row_quarantined == n_rows, code
    for q in kp.list_quarantine(conn, period=PERIOD):
        assert q["reason"], "quarantined row without a reason = silent drop"


def _add_column(csv_text, header_name, values):
    """Return csv_text with one extra column appended (header + per-row)."""
    lines = csv_text.split("\n")
    out = [lines[0] + "," + header_name]
    data = [ln for ln in lines[1:] if ln]
    assert len(data) == len(values)
    for line, val in zip(data, values):
        out.append(line + "," + val)
    return "\n".join(out) + "\n"


def test_schema_drift_unknown_column_alerts_but_good_rows_flow(seeded):
    conn = seeded
    drifted = _add_column(NORTH_CSV, "discount_pct", ["5", "5", "5", "5"])
    stats = kp.ingest_csv(conn, "north", PERIOD, drifted, actor="tester")
    assert stats["staged"] == 3          # good rows still flow
    assert stats["quarantined"] == 1     # the bad data row (column drift is
                                        # a column-level quarantine entry)
    assert stats["alerts"] == 1
    col_entries = [q for q in kp.list_quarantine(conn, period=PERIOD)
                   if q["source_row"] is None]
    assert len(col_entries) == 1
    assert col_entries[0]["reason"] == "unknown_column:discount_pct"
    alerts = kp.list_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "schema_drift"


def test_schema_drift_missing_mapped_column_quarantines_all_rows(seeded):
    conn = seeded
    # drop the cost_usd column (index 3) entirely
    lines = [ln for ln in NORTH_CSV.split("\n") if ln]
    no_cost = "\n".join(
        ",".join(p for i, p in enumerate(ln.split(",")) if i != 3)
        for ln in lines) + "\n"
    stats = kp.ingest_csv(conn, "north", PERIOD, no_cost, actor="tester")
    assert stats["staged"] == 0
    assert stats["quarantined"] == 4
    assert stats["alerts"] == 1
    for q in kp.list_quarantine(conn, period=PERIOD):
        assert q["reason"] == "missing_mapped_column:cost_usd"


def test_ingest_rejects_bad_period(seeded):
    with pytest.raises(kp.KpiPipelineError, match="YYYY-MM"):
        kp.ingest_csv(seeded, "north", "2026-9", NORTH_CSV)


def test_ingest_unknown_location(seeded):
    with pytest.raises(kp.KpiPipelineError, match="Unknown or inactive"):
        kp.ingest_csv(seeded, "east", PERIOD, NORTH_CSV)


# ---------------------------------------------------------------------------
# KPI hand-computation checks
# ---------------------------------------------------------------------------

def test_kpi_values_match_hand_computation_north(ingested):
    values = kp.compute_location_kpis(ingested, "north", PERIOD, actor="tester")
    expected = _hand(NORTH)
    assert values == {k: str(v) for k, v in expected.items()}


def test_kpi_values_match_hand_computation_south(ingested):
    values = kp.compute_location_kpis(ingested, "south", PERIOD, actor="tester")
    expected = _hand(SOUTH)
    assert values == {k: str(v) for k, v in expected.items()}


def test_kpi_values_match_hand_computation_west(ingested):
    values = kp.compute_location_kpis(ingested, "west", PERIOD, actor="tester")
    expected = _hand(WEST)
    assert values == {k: str(v) for k, v in expected.items()}


def test_rollup_matches_hand_computation(ingested):
    values = kp.compute_rollup(ingested, "2026-09", actor="tester")
    expected = _hand(ROLLUP)
    assert values == {k: str(v) for k, v in expected.items()}


def test_rollup_equals_sum_of_location_inputs(ingested):
    conn = ingested
    locs = {c: kp.compute_location_kpis(conn, c, PERIOD, actor="tester")
            for c in ("north", "south", "west")}
    rollup = kp.compute_rollup(conn, PERIOD, actor="tester")
    for name in kpi_defs.KPI_NAMES:
        if name == "revenue":
            total = sum(Decimal(locs[c][name]) for c in locs)
            assert Decimal(rollup[name]) == total
    # spot-check average_ticket is NOT the mean of averages (it is weighted)
    avg_of_avgs = sum(Decimal(locs[c]["average_ticket"]) for c in locs) / 3
    assert Decimal(rollup["average_ticket"]) != avg_of_avgs


def test_kpi_undefined_when_denominator_zero(ingested):
    conn = ingested
    kp.register_location(conn, "empty", "Empty Shop", NORTH_MAP, actor="tester")
    only_bad = ("ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days\n"
                "X-1,2026-09-01,zzz,10.00,N,1.0\n")
    kp.ingest_csv(conn, "empty", PERIOD, only_bad, actor="tester")
    values = kp.compute_location_kpis(conn, "empty", PERIOD, actor="tester")
    assert values["revenue"] == "0.00"
    assert values["gross_margin"] is None
    assert values["callback_rate"] is None
    assert values["average_ticket"] is None
    assert values["bookings_per_tech_day"] is None


# ---------------------------------------------------------------------------
# Drill-down lineage
# ---------------------------------------------------------------------------

def _recompute_from_rows(rows):
    agg_rows = [{"revenue": Decimal(r["revenue"]), "costs": Decimal(r["costs"]),
                 "is_callback": bool(r["is_callback"]),
                 "tech_days": Decimal(r["tech_days"])} for r in rows]
    defs = {"revenue": kpi_defs.KpiDefinition(0, "revenue", "v1", "", "", "", "current"),
            "gross_margin": kpi_defs.KpiDefinition(0, "gross_margin", "v1", "", "", "", "current"),
            "callback_rate": kpi_defs.KpiDefinition(0, "callback_rate", "v1", "", "", "", "current"),
            "average_ticket": kpi_defs.KpiDefinition(0, "average_ticket", "v1", "", "", "", "current"),
            "bookings_per_tech_day": kpi_defs.KpiDefinition(0, "bookings_per_tech_day", "v1", "", "", "", "current")}
    return kpi_defs.compute_all(agg_rows, defs)


def test_rollup_lineage_covers_every_source_row(ingested):
    conn = ingested
    kp.compute_rollup(conn, PERIOD, actor="tester")
    n_staged = conn.execute(
        "SELECT COUNT(*) AS c FROM kpi_staging WHERE period = ?",
        (PERIOD,)).fetchone()["c"]
    assert n_staged == 7
    rollups = conn.execute(
        "SELECT id, kpi_name, value FROM kpi_values "
        "WHERE period = ? AND location_id IS NULL AND status = 'current'",
        (PERIOD,)).fetchall()
    assert len(rollups) == 5
    for v in rollups:
        dd = kp.get_drilldown(conn, v["id"])
        assert len(dd["rows"]) == n_staged, v["kpi_name"]
        recomputed = _recompute_from_rows(dd["rows"])[v["kpi_name"]]
        stored = None if v["value"] is None else Decimal(v["value"])
        assert recomputed == stored, v["kpi_name"]


def test_location_lineage_traces_to_that_location_only(ingested):
    conn = ingested
    kp.compute_location_kpis(conn, "north", PERIOD, actor="tester")
    row = conn.execute(
        "SELECT id FROM kpi_values WHERE period = ? AND kpi_name = 'revenue' "
        "AND location_id = (SELECT id FROM kpi_locations WHERE code='north') "
        "AND status='current'",
        (PERIOD,)).fetchone()
    dd = kp.get_drilldown(conn, row["id"])
    assert len(dd["rows"]) == 3
    assert {r["location_code"] for r in dd["rows"]} == {"north"}
    assert {r["job_id"] for r in dd["rows"]} == {"T-100", "T-101", "T-102"}


def test_get_drilldown_unknown_value_raises(ingested):
    with pytest.raises(kp.KpiPipelineError, match="not found"):
        kp.get_drilldown(ingested, 999999)


# ---------------------------------------------------------------------------
# Double-counting prevention
# ---------------------------------------------------------------------------

def test_reingest_same_csv_is_idempotent(ingested):
    conn = ingested
    before = conn.execute(
        "SELECT COUNT(*) AS c FROM kpi_staging WHERE period = ?",
        (PERIOD,)).fetchone()["c"]
    q_before = conn.execute(
        "SELECT COUNT(*) AS c FROM kpi_quarantine WHERE period = ?",
        (PERIOD,)).fetchone()["c"]
    stats = kp.ingest_csv(conn, "north", PERIOD, NORTH_CSV, actor="tester")
    assert stats["deduped"] is True
    assert stats["staged"] == 0
    assert stats["quarantined"] == 0
    # no new staging rows AND no duplicate quarantine rows either
    after = conn.execute(
        "SELECT COUNT(*) AS c FROM kpi_staging WHERE period = ?",
        (PERIOD,)).fetchone()["c"]
    q_after = conn.execute(
        "SELECT COUNT(*) AS c FROM kpi_quarantine WHERE period = ?",
        (PERIOD,)).fetchone()["c"]
    assert after == before
    assert q_after == q_before
    v1 = kp.compute_rollup(conn, PERIOD, actor="tester")
    v2 = kp.compute_rollup(conn, PERIOD, actor="tester")
    assert v1 == v2
    n_values = conn.execute(
        "SELECT COUNT(*) AS c FROM kpi_values WHERE period = ? "
        "AND location_id IS NULL AND status='current'",
        (PERIOD,)).fetchone()["c"]
    assert n_values == 5


def test_location_scoped_ids_no_cross_location_merge(ingested):
    conn = ingested
    dup_job = ("ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days\n"
               "9001,2026-09-12,100.00,40.00,N,0.5\n")  # same id as south's 9001
    stats = kp.ingest_csv(conn, "north", PERIOD, dup_job, actor="tester")
    assert stats["staged"] == 1  # kept: job ids are location-scoped
    values = kp.compute_location_kpis(conn, "north", PERIOD, actor="tester")
    expected_rev = (NORTH["revenue"] + Decimal("100.00")).quantize(Decimal("0.01"))
    assert Decimal(values["revenue"]) == expected_rev


# ---------------------------------------------------------------------------
# Definition versioning + restatement
# ---------------------------------------------------------------------------

def test_definition_update_supersedes_never_edits(ingested):
    conn = ingested
    old = kpi_defs.get_definition(conn, "gross_margin", "v1")
    new = kpi_defs.update_definition(
        conn, "gross_margin", "v2", kpi_defs.V2_GROSS_MARGIN_DOC[0],
        kpi_defs.V2_GROSS_MARGIN_DOC[1], kpi_defs.V2_GROSS_MARGIN_DOC[2],
        actor="tester")
    assert new.version == "v2"
    assert new.id != old.id
    assert conn.execute(
        "SELECT status FROM kpi_definitions WHERE id = ?",
        (old.id,)).fetchone()["status"] == "superseded"
    # old formula text is intact
    assert conn.execute(
        "SELECT formula_json FROM kpi_definitions WHERE id = ?",
        (old.id,)).fetchone()["formula_json"]


def test_restatement_preserves_old_values_and_recomputes_new(ingested):
    conn = ingested
    for code in ("north", "south", "west"):
        kp.compute_location_kpis(conn, code, PERIOD, actor="tester")
    kp.compute_rollup(conn, PERIOD, actor="tester")
    old_north_margin = conn.execute(
        "SELECT id, value, definition_id FROM kpi_values "
        "WHERE period = ? AND kpi_name = 'gross_margin' AND status='current' "
        "AND location_id = (SELECT id FROM kpi_locations WHERE code='north')",
        (PERIOD,)).fetchone()
    kpi_defs.update_definition(
        conn, "gross_margin", "v2", kpi_defs.V2_GROSS_MARGIN_DOC[0],
        kpi_defs.V2_GROSS_MARGIN_DOC[1], kpi_defs.V2_GROSS_MARGIN_DOC[2],
        actor="tester")
    result = kp.restate_period(conn, PERIOD,
                               reason="Deduct flat $50 callback rework cost",
                               actor="tester")
    assert result["restatements"] == 4  # north, south, west, rollup
    # old value preserved, superseded, pointing at the restatement
    old = conn.execute(
        "SELECT status, restatement_id, value FROM kpi_values WHERE id = ?",
        (old_north_margin["id"],)).fetchone()
    assert old["status"] == "superseded"
    assert old["restatement_id"] is not None
    assert old["value"] == old_north_margin["value"]
    # restatement log entry
    log = kp.list_restatements(conn)
    assert len(log) == 4
    assert {r["kpi_name"] for r in log} == {"gross_margin"}
    assert all(r["reason"] == "Deduct flat $50 callback rework cost" for r in log)
    # new v2 value, hand-checked for north:
    # (1345.50 - 500.00 - 50.00*1) / 1345.50
    expected = ((Decimal("795.50")) / Decimal("1345.50")).quantize(Q)
    new_row = conn.execute(
        "SELECT value FROM kpi_values WHERE period = ? AND kpi_name='gross_margin' "
        "AND status='current' AND location_id = "
        "(SELECT id FROM kpi_locations WHERE code='north')",
        (PERIOD,)).fetchone()
    assert Decimal(new_row["value"]) == expected
    # unchanged KPIs keep their values
    rev = conn.execute(
        "SELECT value FROM kpi_values WHERE period = ? AND kpi_name='revenue' "
        "AND status='current' AND location_id IS NULL",
        (PERIOD,)).fetchone()
    assert Decimal(rev["value"]) == Decimal("3170.74")
    # new v2 value still has full lineage
    dd = kp.get_drilldown(conn, conn.execute(
        "SELECT id FROM kpi_values WHERE period=? AND kpi_name='gross_margin' "
        "AND status='current' AND location_id IS NULL",
        (PERIOD,)).fetchone()["id"])
    assert len(dd["rows"]) == 7


def test_restatement_requires_reason(ingested):
    with pytest.raises(kp.KpiPipelineError, match="reason is required"):
        kp.restate_period(ingested, PERIOD, reason="  ", actor="tester")


def test_update_definition_unknown_kpi(conn):
    with pytest.raises(kpi_defs.KpiError, match="Unknown KPI"):
        kpi_defs.update_definition(conn, "bogus", "v2", "f", "i", "e")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def test_resolve_alert(seeded):
    conn = seeded
    drifted = _add_column(NORTH_CSV, "extra_col", ["x", "x", "x", "x"])
    kp.ingest_csv(conn, "north", PERIOD, drifted, actor="tester")
    alerts = kp.list_alerts(conn)
    assert len(alerts) == 1
    kp.resolve_alert(conn, alerts[0]["id"], actor="tester")
    assert kp.list_alerts(conn) == []
    with pytest.raises(kp.KpiPipelineError, match="already resolved"):
        kp.resolve_alert(conn, alerts[0]["id"], actor="tester")


# ---------------------------------------------------------------------------
# Migration rollback (real down-step)
# ---------------------------------------------------------------------------

def test_migration_010_down_step_rolls_back_for_real(tmp_path):
    from mavenu.db import get_connection
    db_path = str(tmp_path / "rollback.db")
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
        assert "010_kpi_rollup.sql" in {
            r["name"] for r in
            conn.execute("SELECT name FROM schema_migrations").fetchall()}
        kp.register_location(conn, "north", "North Shop", NORTH_MAP,
                             actor="tester")
        kpi_defs.seed_default_definitions(conn, actor="tester")
        kp.ingest_csv(conn, "north", PERIOD, NORTH_CSV, actor="tester")
        kp.compute_location_kpis(conn, "north", PERIOD, actor="tester")
        # roll back for real
        assert rollback_migration(conn, "010_kpi_rollup.sql") is True
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert not any(t.startswith("kpi_") for t in tables)
        assert "010_kpi_rollup.sql" not in {
            r["name"] for r in
            conn.execute("SELECT name FROM schema_migrations").fetchall()}
        # other projects' tables survive
        assert "leads" in tables
        assert "er_contacts" in tables
        # re-apply works cleanly
        applied = run_migrations(conn)
        assert "010_kpi_rollup.sql" in applied
        kp.register_location(conn, "north", "North Shop", NORTH_MAP,
                             actor="tester")
        assert kp.list_locations(conn)[0]["code"] == "north"
    finally:
        conn.close()
