"""V25 candidate indexes and measured query plans on synthetic SQLite data.

Mavenu AI SaaS Development Architecture V4 p43:
  V25 Add indexes and performance profiling.
  Proof: Query-plan and threshold report.

The four candidate indexes are installed ONLY in disposable SQLite version-2
performance copies; V23 versioning and V24.1 persistence source are unchanged.
This is not a production migration or a customer-latency SLA. No customer,
CMMS/ERP/OT data or actual plant events are used.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics
import tempfile
import time
from typing import Any

import entity_v21
import identity_v22
import migrate_v23
import persist_v24

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/data/INDEX_PROFILE_CONTRACT_V25.json"
INDEX_DDL_PATH = ROOT / "docs/data/INDEX_DESIGN_V25.sql"
TENANT = "SYN-TENANT-001"
SITES = 300
ASSETS_PER_SITE = 6
CASES_PER_SITE = 12
EXPECTED_TOTAL = 9301
QUERY_SPECS = {
    "site_recent": (
        "idx_v25_case_site_recent",
        "SELECT case_id, occurred_at_utc FROM maintenance_case "
        "WHERE tenant_id=? AND site_id=? "
        "ORDER BY occurred_at_utc DESC, case_id ASC LIMIT 10",
        (TENANT, "SYN-SITE-220"),
    ),
    "asset_recent": (
        "idx_v25_case_asset_recent",
        "SELECT case_id, occurred_at_utc FROM maintenance_case "
        "WHERE tenant_id=? AND site_id=? AND asset_id=? "
        "ORDER BY occurred_at_utc DESC, case_id ASC LIMIT 10",
        (TENANT, "SYN-SITE-220", "SYN-ASSET-001"),
    ),
    "failure_recent": (
        "idx_v25_case_failure_recent",
        "SELECT case_id, occurred_at_utc FROM maintenance_case "
        "WHERE tenant_id=? AND site_id=? AND failure_code=? "
        "ORDER BY occurred_at_utc DESC, case_id ASC LIMIT 10",
        (TENANT, "SYN-SITE-220", "bearing_wear"),
    ),
    "evidence_reverse": (
        "idx_v25_evidence_reverse",
        "SELECT case_id FROM evidence_reference "
        "WHERE tenant_id=? AND site_id=? AND evidence_ref=? "
        "ORDER BY case_id ASC",
        (TENANT, "SYN-SITE-220", "SYN-EV-101"),
    ),
}
INDEX_COLUMNS = {
    "idx_v25_case_site_recent": (
        "maintenance_case",
        (("tenant_id", "ASC"), ("site_id", "ASC"),
         ("occurred_at_utc", "DESC"), ("case_id", "ASC")),
    ),
    "idx_v25_case_asset_recent": (
        "maintenance_case",
        (("tenant_id", "ASC"), ("site_id", "ASC"),
         ("asset_id", "ASC"), ("occurred_at_utc", "DESC"),
         ("case_id", "ASC")),
    ),
    "idx_v25_case_failure_recent": (
        "maintenance_case",
        (("tenant_id", "ASC"), ("site_id", "ASC"),
         ("failure_code", "ASC"), ("occurred_at_utc", "DESC"),
         ("case_id", "ASC")),
    ),
    "idx_v25_evidence_reverse": (
        "evidence_reference",
        (("tenant_id", "ASC"), ("site_id", "ASC"),
         ("evidence_ref", "ASC"), ("case_id", "ASC")),
    ),
}
INDEX_PREFIX = "idx_v25_"
BASELINE_RUNS = 37
WARMUPS = 5
MEDIAN_MS_MAX = 80
P95_MS_MAX = 200


class IndexProfileRejected(ValueError):
    """Fixed diagnostic; no uncontrolled query text is printed."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise IndexProfileRejected(code)


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("ascii")
    ).hexdigest()


def load_contract() -> dict[str, Any]:
    try:
        obj = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IndexProfileRejected("v25_contract_unavailable") from None
    require(type(obj) is dict, "v25_contract_not_object")
    return obj


def _expected_sql(name: str, table: str,
                  cols: tuple[tuple[str, str], ...]) -> str:
    return ("CREATE INDEX " + name + " ON " + table + " (" +
            ", ".join(column + " " + order for column, order in cols) + ");")


def _allowed_ddl() -> list[str]:
    expected = [
        _expected_sql(name, table, cols)
        for name, (table, cols) in INDEX_COLUMNS.items()
    ]
    try:
        ddl = INDEX_DDL_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise IndexProfileRejected("candidate_index_sql_missing") from None
    actual = [
        line.strip() for line in ddl.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    require(actual == expected, "candidate_index_ddl_drift")
    return expected


def validate_contract(obj: dict[str, Any]) -> None:
    require(type(obj) is dict and
            obj.get("schema_version") == "1.0.0" and
            obj.get("increment") == "V25" and
            obj.get("objective") == "Add indexes and performance profiling" and
            obj.get("required_proof") == "Query-plan and threshold report" and
            obj.get("status") ==
            "SYNTHETIC_INDEX_CANDIDATE_HUMAN_REVIEW_PENDING" and
            obj.get("branch_base") ==
            "feature/reliability-intelligence-v22" and
            obj.get("v24_1_migration_integrated") is True and
            obj.get("sqlite_schema_version") == 2,
            "v25_scope_or_objective_drift")
    require(type(obj.get("approach")) is str and
            "NOT an approved V23 production migration" in obj["approach"],
            "v25_deployment_overclaim")
    rules = obj.get("policy")
    require(type(rules) is dict and
            rules.get("base_ddl") ==
            "docs/data/SCHEMA_DESIGN_V21.sql" and
            rules.get("indexed_tables") ==
            ["maintenance_case", "evidence_reference"] and
            rules.get("temporary_db_prefix") == "mavenu-v24-" and
            rules.get("temporary_filename") == "v24_synthetic.sqlite3" and
            rules.get("tenant") == TENANT and
            rules.get("sites") == SITES and
            rules.get("assets_per_site") == ASSETS_PER_SITE and
            rules.get("cases_per_site") == CASES_PER_SITE and
            rules.get("evidence_refs_per_case") == 1 and
            rules.get("expected_cases") == 3600 and
            rules.get("expected_assets") == 1800 and
            rules.get("expected_evidence_rows") == 3600 and
            rules.get("expected_total_benchmark_rows") == EXPECTED_TOTAL and
            rules.get("index_count") == 4 and
            rules.get("query_count") == 4 and
            rules.get("schema_version_unchanged") is True and
            rules.get("fixture_sources_unmodified") is True and
            rules.get("baseline_runs") == BASELINE_RUNS and
            rules.get("indexed_runs") == BASELINE_RUNS and
            rules.get("warmups") == WARMUPS and
            rules.get("no_speedup_threshold") is True and
            rules.get("no_customer_data") is True and
            rules.get("no_real_tenant_authorization") is True and
            rules.get("no_production_index_deployment") is True,
            "v25_workload_or_benchmark_drift")
    thresholds = rules.get("thresholds")
    require(thresholds == {
        "median_ms_max": MEDIAN_MS_MAX,
        "p95_ms_max": P95_MS_MAX,
        "index_plan_required": True,
        "no_temp_sort_required": True,
        "baseline_result_equal_indexed": True,
        "index_install_rollback_required": True,
    }, "v25_threshold_policy_drift")
    indexes = obj.get("indexes")
    require(type(indexes) is list and len(indexes) == 4 and
            [row.get("name") for row in indexes if type(row) is dict] ==
            list(INDEX_COLUMNS), "v25_index_definition_inventory_drift")
    for row, (name, (table, columns)) in zip(indexes, INDEX_COLUMNS.items()):
        require(row.get("table") == table and
                row.get("columns") == [list(x) for x in columns] and
                type(row.get("use_case")) is str and
                len(row["use_case"]) > 15,
                "v25_index_definition_drift")
    queries = obj.get("queries")
    require(type(queries) is list and len(queries) == 4 and
            [row.get("name") for row in queries if type(row) is dict] ==
            list(QUERY_SPECS), "v25_query_inventory_drift")
    for row, (name, (idx, sql, params)) in zip(queries, QUERY_SPECS.items()):
        require(row.get("index") == idx and
                row.get("sql") == sql and
                row.get("parameters") == list(params) and
                row.get("rows_min") == 1,
                "v25_query_contract_drift")
    approvals = obj.get("approval")
    require(type(approvals) is dict, "v25_missing_approval_ledger")
    for name in (
        "v10_formal_promotion", "v20_data_correctness_signoff",
        "v21_entity_schema_review", "v22_identity_review",
        "v23_migration_review", "v24_storage_review",
        "v24_1_integration_review", "v25_index_plan_review",
        "production_index_migration_authorized",
        "customer_data_authorized", "tenant_access_control_approved"
    ):
        require(approvals.get(name) is False,
                "v25_false_approval_" + name)
    for name in ("reviewer_id", "review_date_utc", "signature"):
        require(approvals.get(name) is None, "v25_fake_reviewer")
    require(type(obj.get("open_decisions")) is list and
            len(obj["open_decisions"]) >= 4,
            "v25_unreviewed_risks_missing")
    _allowed_ddl()


def _candidate_index_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name LIKE 'idx_v25_%'"
        )
    }


def _index_catalog(db: sqlite3.Connection,
                   *, require_installed: bool) -> dict[str, Any]:
    found = _candidate_index_names(db)
    require(found == (set(INDEX_COLUMNS) if require_installed else set()),
            "unexpected_v25_index_inventory")
    details = {}
    if require_installed:
        for name, (table, columns) in INDEX_COLUMNS.items():
            origin = db.execute(
                "SELECT tbl_name FROM sqlite_master "
                "WHERE type='index' AND name=?", (name,)
            ).fetchone()
            require(origin is not None and origin[0] == table,
                    "candidate_index_target_drift")
            keys = [
                (row[2], "DESC" if row[3] else "ASC")
                for row in db.execute(
                    'PRAGMA index_xinfo("' + name + '")'
                ) if row[5] == 1
            ]
            require(keys == list(columns),
                    "candidate_index_column_or_order_drift")
            details[name] = {
                "table": table, "key_columns": [list(k) for k in keys],
                "matches_spec": True
            }
    return {"installed": require_installed, "index_count": len(found),
            "index_details": details}


def install_indexes(db: sqlite3.Connection,
                    *, inject_failure_after: int | None = None
                    ) -> dict[str, Any]:
    """V25-index trial: one DDL transaction, no user_version increment.

    This does not insert the indexes into a V23 migration or production
    V24 bootstrap, and is only supported on empty-ledger benchmark copies.
    """
    require(inject_failure_after in (None, 2),
            "invalid_index_failure_injection")
    state = migrate_v23.validate_version(db, 2)
    require(state["tables"] == 13 and state["triggers"] == 6,
            "candidate_index_schema_mismatch")
    require(all(
        db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0] == 0
        for table in persist_v24.LEDGER
    ), "production_like_ledger_index_trial_denied")
    _index_catalog(db, require_installed=False)
    require(not db.in_transaction, "nested_index_transaction_denied")
    ddl = _allowed_ddl()
    db.execute("BEGIN IMMEDIATE")
    try:
        for count, statement in enumerate(ddl, 1):
            db.execute(statement)
            if inject_failure_after == count:
                raise IndexProfileRejected(
                    "injected_candidate_index_rollback")
        actual = _index_catalog(db, require_installed=True)
        require(db.execute("PRAGMA user_version").fetchone()[0] == 2,
                "candidate_index_modified_schema_version")
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        _index_catalog(db, require_installed=False)
        raise
    return actual


def seed_benchmark(db: sqlite3.Connection) -> dict[str, Any]:
    """Create a larger explicitly *fabricated*, non-customer workload.

    This is NOT a replay of the frozen 12-case original dataset; synthetic
    replication is used solely to exercise SQLite planner selectivity.
    """
    state = migrate_v23.validate_version(db, 2)
    require(state["tables"] == 13 and state["triggers"] == 6,
            "benchmark_requires_v23_v24_schema")
    _index_catalog(db, require_installed=False)
    require(all(
        db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0] == 0
        for table in list(entity_v21.EXPECTED_COUNTS) +
                     list(persist_v24.LEDGER)
    ), "benchmark_source_database_not_empty")
    assert TENANT == entity_v21.TENANT
    failure_codes = ("bearing_wear", "belt_slip",
                     "sensor_fault", "motor_trip")
    asset_classes = ("bearing_drive", "belt_conveyor",
                     "control_valve", "electric_motor",
                     "sensor_module", "transfer_pump")
    cohorts = ("Assembly Test Line", "Mock Workshop",
               "Utility Test Zone")
    sites, assets, cases, evidence = [], [], [], []
    for site_number in range(1, SITES+1):
        site_id = "SYN-SITE-" + str(site_number).zfill(3)
        sites.append((TENANT, site_id,
                      "Fictional Benchmark Site " +
                      str(site_number).zfill(3), 1))
        for a in range(1, ASSETS_PER_SITE+1):
            assets.append((TENANT, site_id,
                           "SYN-ASSET-" + str(a).zfill(3),
                           asset_classes[a-1], cohorts[(a-1)%3], 1))
        for c in range(1, CASES_PER_SITE+1):
            case_id = "SYN-CASE-" + str(c).zfill(3)
            asset_id = "SYN-ASSET-" + str((c-1)%6+1).zfill(3)
            cases.append((
                TENANT, site_id, case_id, asset_id,
                "SYN-WO-" + str(c).zfill(3),
                "2026-02-" + str(c+1).zfill(2) + "T12:00:00Z",
                failure_codes[(c-1)%4], 3600*c, 2500*c,
                "fixture_only", 1
            ))
            evidence.append((
                TENANT, site_id, case_id,
                "SYN-EV-" + str(101+(c-1)%4).zfill(3), 0
            ))
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("INSERT INTO tenant VALUES (?,?,?)",
                   (TENANT,"Invented Performance Benchmark Tenant",
                    "synthetic_only"))
        db.executemany("INSERT INTO site VALUES (?,?,?,?)", sites)
        db.executemany("INSERT INTO asset VALUES (?,?,?,?,?,?)", assets)
        db.executemany(
            "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            cases
        )
        db.executemany(
            "INSERT INTO evidence_reference VALUES (?,?,?,?,?)",
            evidence
        )
        require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                "fabricated_benchmark_foreign_key_violation")
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    counts = {
        "tenant": 1, "site": len(sites),
        "asset": len(assets), "maintenance_case": len(cases),
        "evidence_reference": len(evidence)
    }
    require(counts == {
        "tenant": 1, "site": 300, "asset": 1800,
        "maintenance_case": 3600, "evidence_reference": 3600
    } and sum(counts.values()) == EXPECTED_TOTAL,
            "synthetic_benchmark_row_inventory_drift")
    require(all(
        db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0] == n
        for table, n in counts.items()
    ), "synthetic_benchmark_persistence_mismatch")
    require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
            "benchmark_integrity_check_failed")
    return {
        "synthetic_only": True,
        "source": "deterministic_generated_benchmark_not_frozen_v5_fixtures",
        "generated_row_counts": counts,
        "total_generated_rows": EXPECTED_TOTAL,
        "customer_records": 0,
        "foreign_key_violations": 0,
        "sqlite_schema_version": 2
    }


def _sql_plan(db: sqlite3.Connection, sql: str,
              args: tuple[str, ...]) -> list[str]:
    return [
        str(row[3]) for row in db.execute(
            "EXPLAIN QUERY PLAN " + sql, args
        ).fetchall()
    ]


def _measure(db: sqlite3.Connection, sql: str,
             args: tuple[str, ...]) -> dict[str, Any]:
    for _ in range(WARMUPS):
        tuple(db.execute(sql, args).fetchall())
    samples = []
    for _ in range(BASELINE_RUNS):
        start = time.perf_counter_ns()
        tuple(db.execute(sql,args).fetchall())
        samples.append((time.perf_counter_ns()-start)/1_000_000)
    ordered = sorted(samples)
    return {
        "runs":len(samples),"warmups":WARMUPS,
        "median_ms":round(statistics.median(samples),6),
        "p95_ms":round(ordered[math.ceil(0.95*len(ordered))-1],6),
        "max_ms":round(max(samples),6),
        "timer":"time.perf_counter_ns",
        "synthetic_warm_cache_only":True
    }


def _profile_queries(db: sqlite3.Connection) -> dict[str, Any]:
    report = {}
    for name, (index,sql,args) in QUERY_SPECS.items():
        rows = db.execute(sql,args).fetchall()
        require(len(rows) >= 1, "benchmark_query_empty_" + name)
        report[name] = {
            "expected_index":index,
            "sql":sql,
            "arguments":list(args),
            "result_rows":[list(r) for r in rows],
            "result_sha256":canonical_sha256(rows),
            "plan":_sql_plan(db,sql,args),
            "latency":_measure(db,sql,args)
        }
    return report


def compare_profiles(baseline: dict[str, Any],
                     candidate: dict[str, Any]) -> dict[str, Any]:
    require(set(baseline)==set(QUERY_SPECS) and
            set(candidate)==set(QUERY_SPECS),
            "query_profile_inventory_incomplete")
    comparisons = {}
    for name, (index,sql,args) in QUERY_SPECS.items():
        old, new = baseline[name],candidate[name]
        require(new["sql"]==old["sql"]==sql and
                new["arguments"]==old["arguments"]==list(args) and
                new["result_sha256"]==old["result_sha256"] and
                new["result_rows"]==old["result_rows"],
                "indexed_query_result_regression_"+name)
        plan = " | ".join(new["plan"])
        indexed = re.search(
            r"USING (?:COVERING )?INDEX " + re.escape(index) + r"\b",
            plan
        ) is not None
        no_sort = "USE TEMP B-TREE" not in plan.upper()
        require(indexed, "sqlite_planner_did_not_choose_"+name)
        require(no_sort, "sqlite_candidate_requires_temp_sort_"+name)
        latency = new["latency"]
        threshold_ok = (
            latency["median_ms"] <= MEDIAN_MS_MAX and
            latency["p95_ms"] <= P95_MS_MAX and
            latency["runs"]==BASELINE_RUNS and
            latency["warmups"]==WARMUPS
        )
        require(threshold_ok, "synthetic_latency_threshold_failed_"+name)
        comparisons[name] = {
            "index_chosen":True,
            "sort_avoided":True,
            "result_identical":True,
            "threshold_passed":True,
            "baseline_plan":old["plan"],
            "indexed_plan":new["plan"],
            "baseline_latency":old["latency"],
            "indexed_latency":latency,
            "synthetic_observed_median_ratio":round(
                old["latency"]["median_ms"] /
                max(new["latency"]["median_ms"],0.000001),4
            ),
            "ratio_is_not_gate_or_SLA":True,
            "result_sha256":new["result_sha256"],
            "result_count":len(new["result_rows"])
        }
    return {
        "comparisons": comparisons,
        "queries_verified": len(comparisons),
        "all_index_plans_selected": True,
        "all_results_identical": True,
        "thresholds_passed": True,
        "baseline_vs_index_speedup_not_required": True,
    }


def run_profile() -> dict[str, Any]:
    """Full performance experiment, file cleaned with TemporaryDirectory."""
    cfg = load_contract()
    validate_contract(cfg)
    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as directory:
        path=Path(directory)/persist_v24.NAME
        db=persist_v24.connect(path)
        try:
            persist_v24.bootstrap(db)
            benchmark=seed_benchmark(db)
            baseline=_profile_queries(db)
            failed=False
            try:
                install_indexes(db,inject_failure_after=2)
            except IndexProfileRejected as exc:
                require(str(exc)=="injected_candidate_index_rollback",
                        "unexpected_index_rollback_failure")
                failed=True
            require(failed and
                    _candidate_index_names(db)==set() and
                    migrate_v23.validate_version(db,2)["version"]==2,
                    "partial_candidate_index_rollback")
            installed=install_indexes(db)
            indexed=_profile_queries(db)
            compare=compare_profiles(baseline,indexed)
            require(db.execute("PRAGMA foreign_key_check").fetchall()==[] and
                    db.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
                    "profiled_db_integrity_failure")
            version=migrate_v23.validate_version(db,2)
            require(version["tables"]==13 and
                    version["triggers"]==6,
                    "profiling_changed_v23_v24_schema")
            record={
                "increment":"V25",
                "objective":"Add indexes and performance profiling",
                "required_proof":"Query-plan and threshold report",
                "synthetic_workload":benchmark,
                "candidate_indexes":installed,
                "query_thresholds_ms":{"median":MEDIAN_MS_MAX,"p95":P95_MS_MAX},
                "query_plan_and_threshold_report":compare,
                "injected_index_ddl_rollback_verified":True,
                "source_sql_sha256":hashlib.sha256(
                    INDEX_DDL_PATH.read_bytes()).hexdigest(),
                "contract_sha256":canonical_sha256(cfg),
                "sqlite_version":sqlite3.sqlite_version,
                "sqlite_schema_user_version":version["version"],
                "temp_schema_tables":version["tables"],
                "baseline_and_candidate_queries_warm_cache":True,
                "index_install_is_v23_migration":False,
                "customer_data_used":False,
                "production_latency_SLA_verified":False,
                "production_index_rollout_approved":False
            }
        finally:
            db.close()
    require(not path.exists(), "benchmark_temp_database_not_deleted")
    record["temporary_db_cleaned"]=True
    return record
