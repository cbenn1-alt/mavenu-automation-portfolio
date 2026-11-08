"""Project P04 — SQL Operations Intelligence: service tests.

All data is synthetic. Amounts are invented; names are fictional
stand-ins. The fixture oracle below is hand-computed from
``sqlops.seed_demo_data`` — the tests cannot pass by construction,
only by correct behaviour.
"""
from datetime import datetime
from decimal import Decimal

import pytest

from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.sqlops import (
    MAX_DRILLDOWN_ROWS,
    SqlOpsError,
    compare_periods,
    compile_query,
    create_query,
    drill_down,
    export_run,
    get_query,
    get_run,
    get_snapshot,
    list_queries,
    list_runs,
    run_query,
    seed_demo_data,
    snapshot_run,
    snapshot_status,
    supersede_query,
    validate_spec,
)

FULL = ("2026-10-01", "2026-11-08")
OCT = ("2026-10-01", "2026-10-31")
NOV = ("2026-11-01", "2026-11-08")
EMPTY = ("2026-12-01", "2026-12-31")

LEADS_SPEC = {"table": "leads", "dimensions": ["service"],
              "metrics": [{"kind": "count"}], "filters": [], "grain": "none"}
EST_SPEC = {"table": "estimates", "dimensions": ["service_type"],
            "metrics": [{"kind": "count"},
                        {"kind": "sum", "column": "amount_cents"},
                        {"kind": "avg", "column": "amount_cents"},
                        {"kind": "rate", "name": "acceptance_rate",
                         "numerator": {"column": "state", "value": "accepted"}}],
            "filters": [], "grain": "none"}


@pytest.fixture
def seeded(conn):
    seed_demo_data(conn)
    return conn


def _by_dim(results, dim):
    return {r["dimensions"][dim]: r["metrics"] for r in results}


def _by_period(results):
    return {r["dimensions"]["period"]: r["metrics"] for r in results}


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------

def test_validate_spec_happy_path():
    assert validate_spec(LEADS_SPEC) == LEADS_SPEC


def test_validate_spec_rejects_unknown_table():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "table": "customers"})


def test_validate_spec_rejects_unknown_column():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "dimensions": ["nickname"]})


def test_validate_spec_rejects_metric_only_dimension():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "dimensions": ["amount_cents"],
                       "table": "estimates"})


def test_validate_spec_rejects_unknown_grain():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "grain": "year"})


def test_validate_spec_rejects_three_dimensions():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "dimensions": ["service", "state", "zip"]})


def test_validate_spec_rejects_duplicate_dimensions():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "dimensions": ["service", "service"]})


def test_validate_spec_rejects_zero_metrics():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "metrics": []})


def test_validate_spec_rejects_six_metrics():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC,
                       "metrics": [{"kind": "count"}] * 6})


def test_validate_spec_rejects_duplicate_metric_names():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "table": "estimates",
                       "metrics": [{"kind": "sum", "column": "amount_cents"},
                                   {"kind": "sum", "column": "amount_cents"}]})


def test_validate_spec_rejects_sum_on_text_column():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC,
                       "metrics": [{"kind": "sum", "column": "service"}]})


def test_validate_spec_rejects_bad_filter_op():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC,
                       "filters": [{"column": "state", "op": "like", "value": "book%"}]})


def test_validate_spec_rejects_filter_value_outside_enum():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC,
                       "filters": [{"column": "state", "op": "=", "value": "won"}]})


def test_validate_spec_rejects_filter_on_metric_column():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "table": "estimates",
                       "filters": [{"column": "amount_cents", "op": "=", "value": 5}]})


def test_validate_spec_rejects_bad_rate_name():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "table": "estimates",
                       "metrics": [{"kind": "rate", "name": "Bad Name!",
                                    "numerator": {"column": "state", "value": "accepted"}}]})


def test_validate_spec_rejects_unknown_spec_keys():
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "having": "count > 1"})


def test_compile_rejects_bad_period():
    with pytest.raises(SqlOpsError):
        compile_query(LEADS_SPEC, "2026-13-01", "2026-11-08")
    with pytest.raises(SqlOpsError):
        compile_query(LEADS_SPEC, "2026-11-08", "2026-10-01")
    with pytest.raises(SqlOpsError):
        compile_query(LEADS_SPEC, "October 1", "2026-11-08")


# ---------------------------------------------------------------------------
# Injection resistance — nothing outside the registry reaches SQL text
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("evil", [
    "estimates; DROP TABLE leads; --",
    "estimates\" OR 1=1 --",
    "leads UNION SELECT * FROM leads",
    "estimates\x00",
])
def test_injection_in_table_name_rejected(seeded, evil):
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "table": evil})
    # The tables are still there afterwards.
    assert seeded.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"] == 8


@pytest.mark.parametrize("evil", [
    "state) OR 1=1 --",
    "service\"; DROP TABLE estimates; --",
    "state, (SELECT 1)",
])
def test_injection_in_dimension_rejected(seeded, evil):
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "dimensions": [evil]})


def test_injection_in_filter_value_rejected_and_tables_intact(seeded):
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC,
                       "filters": [{"column": "state", "op": "=",
                                    "value": "booked' OR '1'='1"}]})
    assert seeded.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"] == 8
    assert seeded.execute("SELECT COUNT(*) AS c FROM estimates").fetchone()["c"] == 6


def test_injection_in_metric_column_rejected(seeded):
    with pytest.raises(SqlOpsError):
        validate_spec({**LEADS_SPEC, "table": "estimates",
                       "metrics": [{"kind": "sum", "column": "amount_cents) --"}]})


def test_compiled_sql_binds_values_as_parameters(seeded):
    # A filter value containing SQL syntax is rejected at validation
    # (enum), so prove the parameter path instead: a free-text filter
    # value with a quote runs safely and matches nothing.
    spec = {**LEADS_SPEC, "table": "estimates",
            "dimensions": ["estimator"],
            "filters": [{"column": "estimator", "op": "=", "value": "Da'na; DROP TABLE estimates; --"}]}
    q = create_query(seeded, "quote filter", spec)
    run = run_query(seeded, q["id"], *FULL)
    # No group matches: a grouped query returns zero rows, not a zero row.
    assert run["results"] == []
    assert seeded.execute("SELECT COUNT(*) AS c FROM estimates").fetchone()["c"] == 6


# ---------------------------------------------------------------------------
# Query lifecycle
# ---------------------------------------------------------------------------

def test_create_and_get_query(seeded):
    q = create_query(seeded, "Leads by service", LEADS_SPEC, "demo", actor="ana")
    assert q["version"] == 1 and q["status"] == "current"
    assert q["spec"] == LEADS_SPEC
    assert get_query(seeded, "Leads by service")["id"] == q["id"]


def test_create_duplicate_name_rejected(seeded):
    create_query(seeded, "Dup", LEADS_SPEC)
    with pytest.raises(SqlOpsError):
        create_query(seeded, "Dup", LEADS_SPEC)


def test_create_bad_name_rejected(seeded):
    with pytest.raises(SqlOpsError):
        create_query(seeded, "1bad", LEADS_SPEC)
    with pytest.raises(SqlOpsError):
        create_query(seeded, "bad; DROP", LEADS_SPEC)


def test_create_bad_spec_rejected(seeded):
    with pytest.raises(SqlOpsError):
        create_query(seeded, "Bad", {**LEADS_SPEC, "table": "nope"})


def test_supersede_preserves_old_version(seeded):
    q1 = create_query(seeded, "Versioned", LEADS_SPEC)
    spec2 = {**LEADS_SPEC, "dimensions": ["state"]}
    q2 = supersede_query(seeded, "Versioned", spec2)
    assert q2["version"] == 2 and q2["status"] == "current"
    old = get_query(seeded, "Versioned", version=1)
    assert old["status"] == "superseded" and old["spec"] == LEADS_SPEC
    assert get_query(seeded, "Versioned")["id"] == q2["id"]
    assert q1["id"] != q2["id"]


def test_supersede_unknown_query_rejected(seeded):
    with pytest.raises(SqlOpsError):
        supersede_query(seeded, "Nope", LEADS_SPEC)


def test_list_queries_only_current_by_default(seeded):
    create_query(seeded, "A", LEADS_SPEC)
    create_query(seeded, "B", EST_SPEC)
    supersede_query(seeded, "A", {**LEADS_SPEC, "dimensions": ["state"]})
    assert [q["name"] for q in list_queries(seeded)] == ["A", "B"]
    assert len(list_queries(seeded, include_superseded=True)) == 3


# ---------------------------------------------------------------------------
# Fixture oracle — hand-computed aggregates over the seed data
# ---------------------------------------------------------------------------

def test_oracle_leads_by_service(seeded):
    q = create_query(seeded, "L1", LEADS_SPEC)
    run = run_query(seeded, q["id"], *FULL)
    by = _by_dim(run["results"], "service")
    assert by == {"electrical": {"count": 2}, "hvac": {"count": 3},
                  "plumbing": {"count": 2}, "roofing": {"count": 1}}


def test_oracle_leads_by_state(seeded):
    q = create_query(seeded, "L2", {**LEADS_SPEC, "dimensions": ["state"]})
    run = run_query(seeded, q["id"], *FULL)
    by = _by_dim(run["results"], "state")
    assert by == {"qualified": {"count": 3}, "received": {"count": 2},
                  "booked": {"count": 2}, "rejected": {"count": 1}}


def test_oracle_leads_october_vs_november(seeded):
    q = create_query(seeded, "L3", {**LEADS_SPEC, "dimensions": []})
    assert run_query(seeded, q["id"], *OCT)["results"][0]["metrics"] == {"count": 6}
    assert run_query(seeded, q["id"], *NOV)["results"][0]["metrics"] == {"count": 2}


def test_oracle_missed_calls_aggregates(seeded):
    spec = {"table": "missed_calls", "dimensions": ["state"],
            "metrics": [{"kind": "count"},
                        {"kind": "sum", "column": "duration_seconds"},
                        {"kind": "avg", "column": "duration_seconds"},
                        {"kind": "avg", "column": "urgency_score"},
                        {"kind": "rate", "name": "booked_rate",
                         "numerator": {"column": "state", "value": "booked"}}],
            "filters": [], "grain": "none"}
    q = create_query(seeded, "MC1", spec)
    run = run_query(seeded, q["id"], *FULL)
    assert len(run["results"]) == 4  # pending, booked, lost, connected
    by = _by_dim(run["results"], "state")
    assert by["pending"]["count"] == 2 and by["booked"]["count"] == 2
    assert by["lost"]["count"] == 1 and by["connected"]["count"] == 1
    # Overall: sum 495, avg 82.50, urgency avg 0.658333, min 30, max 150.
    spec_all = {**spec, "dimensions": []}
    q2 = create_query(seeded, "MC2", spec_all)
    run2 = run_query(seeded, q2["id"], *FULL)
    m = run2["results"][0]["metrics"]
    assert m["count"] == 6
    assert m["sum_duration_seconds"] == 495
    assert m["avg_duration_seconds"] == "82.50"
    assert m["avg_urgency_score"] == "0.658333"
    assert m["booked_rate"] == "0.333333"
    # min/max live in a second query (max 5 metrics per spec).
    spec_mm = {"table": "missed_calls", "dimensions": [],
               "metrics": [{"kind": "min", "column": "duration_seconds"},
                           {"kind": "max", "column": "duration_seconds"}],
               "filters": [], "grain": "none"}
    q3 = create_query(seeded, "MC3", spec_mm)
    m3 = run_query(seeded, q3["id"], *FULL)["results"][0]["metrics"]
    assert m3 == {"min_duration_seconds": 30, "max_duration_seconds": 150}


def test_oracle_estimates_money(seeded):
    q = create_query(seeded, "E1", EST_SPEC)
    run = run_query(seeded, q["id"], *FULL)
    by = _by_dim(run["results"], "service_type")
    assert by["hvac"] == {"count": 3, "sum_amount_cents": 350000,
                          "avg_amount_cents": "116666.67",
                          "acceptance_rate": "0.333333"}
    assert by["plumbing"] == {"count": 2, "sum_amount_cents": 315000,
                              "avg_amount_cents": "157500.00",
                              "acceptance_rate": "0.500000"}
    assert by["electrical"] == {"count": 1, "sum_amount_cents": 310000,
                                "avg_amount_cents": "310000.00",
                                "acceptance_rate": "1.000000"}


def test_oracle_estimates_total(seeded):
    q = create_query(seeded, "E2", {**EST_SPEC, "dimensions": []})
    run = run_query(seeded, q["id"], *FULL)
    assert run["results"][0]["metrics"] == {
        "count": 6, "sum_amount_cents": 975000,
        "avg_amount_cents": "162500.00", "acceptance_rate": "0.500000"}


def test_oracle_invoices_and_payments(seeded):
    spec = {"table": "recon_invoices", "dimensions": ["customer"],
            "metrics": [{"kind": "count"}, {"kind": "sum", "column": "amount_cents"}],
            "filters": [], "grain": "none"}
    q = create_query(seeded, "I1", spec)
    by = _by_dim(run_query(seeded, q["id"], *FULL)["results"], "customer")
    assert by == {"Acme Test Co": {"count": 3, "sum_amount_cents": 215000},
                  "Beta Fixtures LLC": {"count": 2, "sum_amount_cents": 150000}}
    q2 = create_query(seeded, "P1", {**spec, "table": "recon_payments"})
    by2 = _by_dim(run_query(seeded, q2["id"], *FULL)["results"], "customer")
    assert by2 == {"Acme Test Co": {"count": 2, "sum_amount_cents": 125000},
                   "Beta Fixtures LLC": {"count": 2, "sum_amount_cents": 150000}}


def test_oracle_docintel_counts(seeded):
    q = create_query(seeded, "D1", {"table": "docintel_documents",
                                     "dimensions": ["doc_type"],
                                     "metrics": [{"kind": "count"}],
                                     "filters": [], "grain": "none"})
    by = _by_dim(run_query(seeded, q["id"], *FULL)["results"], "doc_type")
    assert by == {"invoice": {"count": 2}, "receipt": {"count": 1},
                  "contract": {"count": 1}}
    q2 = create_query(seeded, "D2", {"table": "docintel_documents",
                                      "dimensions": ["state"],
                                      "metrics": [{"kind": "count"}],
                                      "filters": [], "grain": "none"})
    by2 = _by_dim(run_query(seeded, q2["id"], *FULL)["results"], "state")
    assert by2 == {"accepted": {"count": 2}, "needs_review": {"count": 2}}


def test_oracle_distinct_emails(seeded):
    q = create_query(seeded, "L4", {"table": "leads", "dimensions": [],
                                     "metrics": [{"kind": "distinct", "column": "email"}],
                                     "filters": [], "grain": "none"})
    run = run_query(seeded, q["id"], *FULL)
    assert run["results"][0]["metrics"] == {"distinct_email": 8}


# ---------------------------------------------------------------------------
# Grain, filters, empty periods
# ---------------------------------------------------------------------------

def test_grain_month_buckets(seeded):
    q = create_query(seeded, "G1", {"table": "estimates", "dimensions": [],
                                     "metrics": [{"kind": "count"},
                                                 {"kind": "sum", "column": "amount_cents"}],
                                     "filters": [], "grain": "month"})
    by = _by_period(run_query(seeded, q["id"], *FULL)["results"])
    assert by == {"2026-10": {"count": 5, "sum_amount_cents": 855000},
                  "2026-11": {"count": 1, "sum_amount_cents": 120000}}


def test_grain_day_buckets(seeded):
    q = create_query(seeded, "G2", {"table": "estimates", "dimensions": [],
                                     "metrics": [{"kind": "count"}],
                                     "filters": [], "grain": "day"})
    by = _by_period(run_query(seeded, q["id"], *FULL)["results"])
    assert by == {"2026-10-08": {"count": 1}, "2026-10-09": {"count": 1},
                  "2026-10-15": {"count": 1}, "2026-10-16": {"count": 1},
                  "2026-10-28": {"count": 1}, "2026-11-04": {"count": 1}}


def test_grain_week_groups_adjacent_days(seeded):
    q = create_query(seeded, "G3", {"table": "estimates", "dimensions": [],
                                     "metrics": [{"kind": "count"},
                                                 {"kind": "sum", "column": "amount_cents"}],
                                     "filters": [], "grain": "week"})
    results = run_query(seeded, q["id"], *FULL)["results"]
    assert len(results) == 4  # Oct 8-9, Oct 15-16, Oct 28, Nov 4
    assert sorted(r["metrics"]["count"] for r in results) == [1, 1, 2, 2]
    assert sorted(r["metrics"]["sum_amount_cents"] for r in results) == [120000, 230000, 310000, 315000]
    # The two 2-row weeks are Oct 8-9 (230,000) and Oct 15-16 (315,000).
    two_row = {r["dimensions"]["period"]: r["metrics"]["sum_amount_cents"]
               for r in results if r["metrics"]["count"] == 2}
    week_8_9 = datetime(2026, 10, 8).strftime("%Y-W%W")
    week_15_16 = datetime(2026, 10, 15).strftime("%Y-W%W")
    assert two_row == {week_8_9: 230000, week_15_16: 315000}


def test_filter_equals_and_in(seeded):
    spec = {**EST_SPEC, "filters": [{"column": "state", "op": "=", "value": "accepted"}]}
    q = create_query(seeded, "F1", spec)
    run = run_query(seeded, q["id"], *FULL)
    assert sum(r["metrics"]["count"] for r in run["results"]) == 3
    assert sum(r["metrics"]["sum_amount_cents"] for r in run["results"]) == 680000
    spec2 = {**EST_SPEC, "filters": [{"column": "state", "op": "in",
                                       "value": ["accepted", "sent"]}]}
    q2 = create_query(seeded, "F2", spec2)
    run2 = run_query(seeded, q2["id"], *FULL)
    assert sum(r["metrics"]["count"] for r in run2["results"]) == 5


def test_empty_period_returns_one_zero_row(seeded):
    q = create_query(seeded, "E0", {**EST_SPEC, "dimensions": []})
    run = run_query(seeded, q["id"], *EMPTY)
    assert run["results"] == [{"dimensions": {}, "metrics": {
        "count": 0, "sum_amount_cents": None, "avg_amount_cents": None,
        "acceptance_rate": None}}]


def test_rate_null_when_denominator_zero(seeded):
    q = create_query(seeded, "R0", {"table": "missed_calls", "dimensions": [],
                                     "metrics": [{"kind": "rate", "name": "booked_rate",
                                                  "numerator": {"column": "state", "value": "booked"}}],
                                     "filters": [], "grain": "none"})
    run = run_query(seeded, q["id"], *EMPTY)
    assert run["results"][0]["metrics"] == {"booked_rate": None}


def test_run_records_error_and_history(seeded):
    q = create_query(seeded, "ERR", LEADS_SPEC)
    with pytest.raises(SqlOpsError):
        run_query(seeded, q["id"], "2026-11-08", "2026-10-01")
    runs = list_runs(seeded, q["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "period_start" in (runs[0]["error_text"] or "")


def test_result_row_cap_is_enforced(seeded):
    q = create_query(seeded, "CAP", LEADS_SPEC)
    with pytest.raises(SqlOpsError):
        run_query(seeded, q["id"], *FULL, max_rows=2)
    assert list_runs(seeded, q["id"])[0]["status"] == "error"


def test_run_is_deterministic(seeded):
    q = create_query(seeded, "DET", EST_SPEC)
    r1 = run_query(seeded, q["id"], *FULL)
    r2 = run_query(seeded, q["id"], *FULL)
    assert r1["results"] == r2["results"]
    assert r1["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Drill-down lineage
# ---------------------------------------------------------------------------

def test_drill_down_returns_source_rows(seeded):
    q = create_query(seeded, "DD1", EST_SPEC)
    run = run_query(seeded, q["id"], *FULL)
    dd = drill_down(seeded, run["id"], "service_type", "hvac")
    assert dd["row_count"] == 3 and not dd["truncated"]
    assert [r["public_id"] for r in dd["rows"]] == [
        "EST-SQL-001", "EST-SQL-002", "EST-SQL-006"]
    assert all("amount_cents" in r for r in dd["rows"])


def test_drill_down_respects_run_filters(seeded):
    spec = {**EST_SPEC, "filters": [{"column": "state", "op": "=", "value": "accepted"}]}
    q = create_query(seeded, "DD2", spec)
    run = run_query(seeded, q["id"], *FULL)
    dd = drill_down(seeded, run["id"], "service_type", "hvac")
    assert [r["public_id"] for r in dd["rows"]] == ["EST-SQL-001"]


def test_drill_down_on_period_bucket(seeded):
    q = create_query(seeded, "DD3", {"table": "estimates", "dimensions": [],
                                      "metrics": [{"kind": "count"}],
                                      "filters": [], "grain": "month"})
    run = run_query(seeded, q["id"], *FULL)
    dd = drill_down(seeded, run["id"], "period", "2026-10")
    assert dd["row_count"] == 5
    dd2 = drill_down(seeded, run["id"], "period", "2026-11")
    assert [r["public_id"] for r in dd2["rows"]] == ["EST-SQL-006"]


def test_drill_down_rejects_unknown_dimension(seeded):
    q = create_query(seeded, "DD4", EST_SPEC)
    run = run_query(seeded, q["id"], *FULL)
    with pytest.raises(SqlOpsError):
        drill_down(seeded, run["id"], "estimator", "Dana")
    with pytest.raises(SqlOpsError):
        drill_down(seeded, run["id"], "service_type", "nuclear")


def test_drill_down_never_returns_caller_hash(seeded):
    q = create_query(seeded, "DD5", {"table": "missed_calls", "dimensions": ["state"],
                                      "metrics": [{"kind": "count"}],
                                      "filters": [], "grain": "none"})
    run = run_query(seeded, q["id"], *FULL)
    dd = drill_down(seeded, run["id"], "state", "booked")
    assert dd["row_count"] == 2
    assert all("caller_id_hash" not in r for r in dd["rows"])
    assert all("caller_id_masked" not in r for r in dd["rows"])


def test_drill_down_limit_truncates(seeded):
    q2 = create_query(seeded, "DD7", EST_SPEC)
    run2 = run_query(seeded, q2["id"], *FULL)
    dd2 = drill_down(seeded, run2["id"], "service_type", "hvac", limit=2)
    assert dd2["row_count"] == 2 and dd2["truncated"] is True


# ---------------------------------------------------------------------------
# Period-over-period comparison
# ---------------------------------------------------------------------------

def test_compare_periods_deltas(seeded):
    q = create_query(seeded, "C1", EST_SPEC)
    cmp = compare_periods(seeded, q["id"], OCT, NOV)
    by = {r["dimensions"]["service_type"]: r["metrics"] for r in cmp["rows"]}
    hvac = by["hvac"]
    assert hvac["count"] == {"a": 2, "b": 1, "delta": -1, "pct": Decimal("-50.000000")}
    assert hvac["sum_amount_cents"] == {"a": 230000, "b": 120000,
                                         "delta": -110000,
                                         "pct": Decimal("-47.826087")}
    assert hvac["acceptance_rate"]["a"] == "0.500000"
    assert hvac["acceptance_rate"]["b"] == "0.000000"
    # electrical exists only in October: b is None, delta/pct are None.
    assert by["electrical"]["count"] == {"a": 1, "b": None, "delta": None, "pct": None}
    assert cmp["period_a"]["run_id"] != cmp["period_b"]["run_id"]
    assert len(list_runs(seeded, q["id"])) == 2


def test_compare_pct_null_when_a_is_zero(seeded):
    q = create_query(seeded, "C2", {**EST_SPEC, "dimensions": []})
    cmp = compare_periods(seeded, q["id"], EMPTY, NOV)
    m = cmp["rows"][0]["metrics"]["count"]
    assert m == {"a": 0, "b": 1, "delta": 1, "pct": None}


# ---------------------------------------------------------------------------
# Snapshots + export + seed + migration
# ---------------------------------------------------------------------------

def test_snapshot_current_then_stale_after_change(seeded):
    q = create_query(seeded, "S1", EST_SPEC)
    run = run_query(seeded, q["id"], *FULL)
    snap = snapshot_run(seeded, run["id"])
    assert snapshot_status(seeded, snap["id"])["status"] == "current"
    seeded.execute(
        """INSERT INTO estimates
           (public_id, customer_name, service_type, estimator, amount_cents,
            state, sent_at, created_at, updated_at)
           VALUES ('EST-SQL-099', 'Acme Test Co', 'hvac', 'Dana', 1000,
                   'sent', '2026-11-05T12:00:00+00:00',
                   '2026-11-05T12:00:00+00:00', '2026-11-05T12:00:00+00:00')""")
    seeded.commit()
    assert snapshot_status(seeded, snap["id"])["status"] == "stale"


def test_snapshot_of_failed_run_rejected(seeded):
    q = create_query(seeded, "S2", LEADS_SPEC)
    with pytest.raises(SqlOpsError):
        run_query(seeded, q["id"], "2026-11-08", "2026-10-01")
    run = list_runs(seeded, q["id"])[0]
    with pytest.raises(SqlOpsError):
        snapshot_run(seeded, run["id"])


def test_export_csv_and_json(seeded):
    q = create_query(seeded, "X1", EST_SPEC)
    run = run_query(seeded, q["id"], *FULL)
    csv_text = export_run(seeded, run["id"], "csv")
    lines = csv_text.strip().splitlines()
    # Stored results sort keys alphabetically (json sort_keys=True), so
    # the CSV header follows that order, not spec order.
    assert lines[0] == "service_type,acceptance_rate,avg_amount_cents,count,sum_amount_cents"
    assert len(lines) == 4  # header + 3 groups
    assert "hvac,0.333333,116666.67,3,350000" in lines
    data = __import__("json").loads(export_run(seeded, run["id"], "json"))
    assert data == run["results"]
    with pytest.raises(SqlOpsError):
        export_run(seeded, run["id"], "xml")


def test_seed_is_idempotent(seeded):
    first = seed_demo_data(seeded)
    assert first == {"already_seeded": True, "inserted": {}}
    assert seeded.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"] == 8


def test_migration_022_down_step_rolls_back_for_real(conn):
    assert "022_sqlops.sql" in applied_migrations(conn)
    for t in ("sqlops_queries", "sqlops_runs", "sqlops_snapshots", "sqlops_events"):
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?",
            (t,)).fetchone()["c"] == 1
    assert rollback_migration(conn, "022_sqlops.sql") is True
    for t in ("sqlops_queries", "sqlops_runs", "sqlops_snapshots", "sqlops_events"):
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?",
            (t,)).fetchone()["c"] == 0
    assert "022_sqlops.sql" not in applied_migrations(conn)
    # Re-apply so later tests in this process still see the tables.
    run_migrations(conn)
    assert "022_sqlops.sql" in applied_migrations(conn)
