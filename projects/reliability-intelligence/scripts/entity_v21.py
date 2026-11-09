"""V21 candidate canonical entity schema, synthetic-only in-memory proof.

Architecture V4 Appendix V21: "Design canonical entities and relationships";
proof "Reviewed entity schema". The DDL and candidate diagram are for human
review and are NOT approved, migrated, durable or production data storage.

Never connect to a database outside SQLite ':memory:'; no customer inputs,
live users, operational identity rules, site access control or industrial IO.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from typing import Any

import lineage_v16

PROJECT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT / "docs/data/ENTITY_MODEL_V21.json"
DDL_PATH = PROJECT / "docs/data/SCHEMA_DESIGN_V21.sql"
TENANT = "SYN-TENANT-001"
SITE = "SYN-SITE-001"
SOURCE_IDS = {
    "fixtures/cases.json": "SYN-DOC-001",
    "fixtures/demo_review_script.json": "SYN-DOC-002",
    "fixtures/reference_labels.json": "SYN-DOC-003",
}
EXPECTED_COUNTS = {
    "tenant": 1,
    "site": 1,
    "asset": 6,
    "maintenance_case": 12,
    "evidence_reference": 11,
    "scripted_review": 4,
    "reference_label": 12,
    "source_document": 3,
    "record_origin": 34,
    "transform_step": 36,
}
EXPECTED_PKS = {
    "tenant": ("tenant_id",),
    "site": ("tenant_id", "site_id"),
    "asset": ("tenant_id", "site_id", "asset_id"),
    "maintenance_case": ("tenant_id", "site_id", "case_id"),
    "evidence_reference": ("tenant_id", "site_id", "case_id", "evidence_ref"),
    "scripted_review": ("tenant_id", "site_id", "case_id", "reviewer_id"),
    "reference_label": ("tenant_id", "site_id", "case_id"),
    "source_document": ("tenant_id", "site_id", "source_document_id"),
    "record_origin": ("tenant_id", "site_id", "trace_id"),
    "transform_step": ("tenant_id", "site_id", "trace_id", "step_ordinal"),
}
EXPECTED_FKS = {
    "tenant": [],
    "site": [(("tenant_id",), "tenant", ("tenant_id",))],
    "asset": [(("tenant_id", "site_id"), "site", ("tenant_id", "site_id"))],
    "maintenance_case": [(("tenant_id", "site_id", "asset_id"), "asset",
                          ("tenant_id", "site_id", "asset_id"))],
    "evidence_reference": [(("tenant_id", "site_id", "case_id"), "maintenance_case",
                            ("tenant_id", "site_id", "case_id"))],
    "scripted_review": [(("tenant_id", "site_id", "case_id"), "maintenance_case",
                         ("tenant_id", "site_id", "case_id"))],
    "reference_label": [(("tenant_id", "site_id", "case_id"), "maintenance_case",
                         ("tenant_id", "site_id", "case_id"))],
    "source_document": [(("tenant_id", "site_id"), "site",
                         ("tenant_id", "site_id"))],
    "record_origin": [(("tenant_id", "site_id", "source_document_id"),
                       "source_document",
                       ("tenant_id", "site_id", "source_document_id"))],
    "transform_step": [(("tenant_id", "site_id", "trace_id"), "record_origin",
                        ("tenant_id", "site_id", "trace_id"))],
}


class EntitySchemaRejected(ValueError):
    """Fixed non-sensitive diagnostic for schema-model review failures."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise EntitySchemaRejected(code)


def load_model(path: Path = MODEL_PATH) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise EntitySchemaRejected("candidate_entity_model_unavailable") from None
    require(type(obj) is dict, "candidate_entity_model_not_object")
    return obj


def validate_model(model: dict[str, Any]) -> None:
    require(type(model) is dict and model.get("schema_version") == "1.0.0",
            "entity_model_version_drift")
    require(model.get("increment") == "V21" and
            model.get("objective") ==
            "Design canonical entities and relationships" and
            model.get("required_proof") == "Reviewed entity schema",
            "entity_model_objective_drift")
    require(model.get("review_status") ==
            "CANDIDATE_TECHNICALLY_CHECKABLE_HUMAN_REVIEW_PENDING",
            "entity_schema_false_approval")
    require(model.get("source_fixture_set_id") ==
            "SYN-RI-V5-20261107-A" and
            model.get("v9_frozen_source_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5",
            "entity_model_frozen_source_drift")
    require(model.get("ddl_path") == "docs/data/SCHEMA_DESIGN_V21.sql" and
            model.get("fixture_source_paths") == list(SOURCE_IDS),
            "entity_model_unapproved_source")
    require(model.get("expected_entity_count") == 10 and
            model.get("expected_relationship_count") == 9 and
            model.get("expected_total_synthetic_rows") == 120,
            "entity_inventory_contract_drift")
    ns = model.get("synthetic_namespace")
    require(type(ns) is dict and ns.get("tenant_id") == TENANT and
            ns.get("site_id") == SITE and
            ns.get("site_label") == "Fictional Research Site" and
            ns.get("allow_multiple_tenants_in_schema") is True and
            ns.get("tenant_authorization_implemented") is False,
            "model_tenant_auth_overclaim")
    rules = model.get("design_rules")
    require(type(rules) is dict and
            rules.get("engine") == "SQLite in-memory for schema-review test only" and
            rules.get("schema_dialect") ==
            "SQLite DDL draft; no production migration" and
            rules.get("foreign_keys_enforced_in_test") is True and
            rules.get("composite_fk_tenant_fencing") is True and
            rules.get("source_of_truth") == "committed fabricated fixtures only",
            "model_design_rule_drift")
    for key in ("storage_persistence_enabled", "fixture_data_written_to_disk",
                "customer_data_authorized", "real_record_origin_observed",
                "reviewer_signoff_obtained", "automatic_v22_or_v23_promotion"):
        require(rules.get(key) is False, "model_false_implementation_" + key)
    actual = model.get("entities")
    require(type(actual) is list and len(actual) == len(EXPECTED_COUNTS),
            "model_entity_count_mismatch")
    for row, (name, count) in zip(actual, EXPECTED_COUNTS.items()):
        require(type(row) is dict and row.get("name") == name and
                row.get("expected_fixture_rows") == count and
                row.get("primary_key") == list(EXPECTED_PKS[name]) and
                type(row.get("semantic")) is str and len(row["semantic"]) > 8,
                "entity_definition_drift")
        expected = [
            {"from": list(frm), "table": target, "to": list(to)}
            for frm, target, to in EXPECTED_FKS[name]
        ]
        require(row.get("foreign_keys") == expected,
                "entity_relationship_contract_drift")
    require(sum(row["expected_fixture_rows"] for row in actual) == 120,
            "entity_total_rows_invalid")
    approval = model.get("approval")
    require(type(approval) is dict, "model_approval_missing")
    for key in (
        "v10_formal_phase_promotion", "v20_data_quality_signoff",
        "v21_schema_human_review", "customer_data_authorized",
        "production_database_approved", "tenant_access_control_approved",
        "v22_authorized", "ot_or_cmms_write_permitted",
    ):
        require(approval.get(key) is False, "model_false_authorization_" + key)
    for key in ("named_product_owner", "named_data_architect",
                "named_domain_steward", "named_security_reviewer",
                "approval_signature", "approval_date_utc"):
        require(approval.get(key) is None, "model_fabricated_signature_" + key)
    decisions = model.get("unresolved_design_decisions")
    require(type(decisions) is list and len(decisions) >= 6,
            "model_missing_design_risks")


def create_memory_schema(path: Path = DDL_PATH) -> sqlite3.Connection:
    """Never opens a file-backed DB. DDL is reviewed as design only."""
    try:
        ddl = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise EntitySchemaRejected("candidate_sql_missing") from None
    require(ddl.count("CREATE TABLE ") == 10 and
            ddl.upper().count("WITHOUT ROWID") == 10 and
            "ATTACH " not in ddl.upper() and
            "CREATE TRIGGER " not in ddl.upper() and
            "CREATE VIRTUAL " not in ddl.upper(),
            "unapproved_sql_operations")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(ddl)
        require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
                "foreign_keys_not_enabled")
        locations = db.execute("PRAGMA database_list").fetchall()
        require(all(not location[2] for location in locations),
                "unexpected_file_backed_database")
        return db
    except Exception:
        db.close()
        raise


def _catalog_foreign_keys(db: sqlite3.Connection, name: str) -> list[
    tuple[tuple[str, ...], str, tuple[str, ...]]
]:
    grouped: dict[int, list[tuple[int, str, str, str]]] = {}
    for row in db.execute('PRAGMA foreign_key_list("' + name + '")'):
        fk_id, seq, table, source, target = row[:5]
        grouped.setdefault(fk_id, []).append((seq, table, source, target))
    found = []
    for group in grouped.values():
        ordered = sorted(group)
        found.append((tuple(x[2] for x in ordered),
                      ordered[0][1],
                      tuple(x[3] for x in ordered)))
    return sorted(found)


def validate_catalog(db: sqlite3.Connection, model: dict[str, Any]) -> dict[str, Any]:
    validate_model(model)
    table_records = db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    require({x[0] for x in table_records} == set(EXPECTED_COUNTS),
            "physical_table_inventory_drift")
    for name, ddl in table_records:
        require("WITHOUT ROWID" in ddl.upper(), "unapproved_rowid_table")
        columns = db.execute('PRAGMA table_info("' + name + '")').fetchall()
        pk = tuple(x[1] for x in sorted(
            (c for c in columns if c[5] > 0), key=lambda c: c[5]))
        require(pk == EXPECTED_PKS[name], "canonical_primary_key_drift")
        actual_fk = _catalog_foreign_keys(db, name)
        expected_fk = sorted(EXPECTED_FKS[name])
        require(actual_fk == expected_fk, "tenant_scoped_relation_drift")
        if name not in ("tenant", "site"):
            require("tenant_id" in {c[1] for c in columns} and
                    "site_id" in {c[1] for c in columns},
                    "missing_tenant_site_scope")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "foreign_key_checks_disabled")
    require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
            "foreign_key_violation")
    require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok",
            "sqlite_integrity_failure")
    return {
        "entities_verified": len(table_records),
        "relationships_verified": sum(map(len, EXPECTED_FKS.values())),
        "composite_tenant_scoped_foreign_keys": 8,
        "primary_keys_verified": len(EXPECTED_PKS),
        "without_rowid_tables": len(table_records),
        "in_memory_only": True,
    }


def _integral(value: Any, scale: int, code: str) -> int:
    require(type(value) in (int, float), code)
    try:
        x = Decimal(str(value)) * Decimal(scale)
    except (ValueError, InvalidOperation):
        raise EntitySchemaRejected(code) from None
    require(x.is_finite() and x == x.to_integral_value(),
            code)
    return int(x)


def load_synthetic_preview(db: sqlite3.Connection,
                           model: dict[str, Any]) -> dict[str, Any]:
    """Populate a disposable in-memory *review preview*, not a V24 store."""
    validate_model(model)
    original, hashes = lineage_v16.load_source_documents()
    lineage_policy = lineage_v16.load_policy()
    lineage_v16.validate_policy(lineage_policy)
    full_trace = lineage_v16.reconstruct_trace(lineage_policy, original, hashes)
    lineage_v16.validate_trace(full_trace, lineage_policy, original, hashes)
    cases = original["fixtures/cases.json"]
    reviews = original["fixtures/demo_review_script.json"]
    labels = original["fixtures/reference_labels.json"]
    assert_cases = cases["records"]
    assert_assets = cases["assets"]
    require(len(assert_cases) == 12 and len(assert_assets) == 6 and
            len(reviews["entries"]) == 4 and len(labels["records"]) == 12,
            "synthetic_preview_fixture_inventory_drift")
    try:
        with db:
            db.execute("INSERT INTO tenant VALUES (?,?,?)",
                       (TENANT, "Invented Test Tenant", "synthetic_only"))
            db.execute("INSERT INTO site VALUES (?,?,?,?)",
                       (TENANT, SITE, model["synthetic_namespace"]["site_label"], 1))
            for row in assert_assets:
                require(row["synthetic"] is True, "non_synthetic_asset")
                db.execute("INSERT INTO asset VALUES (?,?,?,?,?,?)", (
                    TENANT, SITE, row["asset_id"], row["asset_class"],
                    row["cohort"], 1,
                ))
            for row in assert_cases:
                require(row["synthetic"] is True and
                        row["review_state"] == "fixture_only",
                        "non_synthetic_maintenance_case")
                seconds = _integral(row["downtime_hours"], 3600,
                                    "duration_not_integral_seconds")
                cents = _integral(row["repair_cost_usd"], 100,
                                  "money_not_integral_cents")
                db.execute(
                    "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (TENANT, SITE, row["case_id"], row["asset_id"],
                     row["work_order_ref"], row["occurred_at_utc"],
                     row["failure_code"], seconds, cents, "fixture_only", 1)
                )
                for ref in row["evidence_refs"]:
                    db.execute(
                        "INSERT INTO evidence_reference VALUES (?,?,?,?,?)",
                        (TENANT, SITE, row["case_id"], ref, 0))
            for row in reviews["entries"]:
                db.execute(
                    "INSERT INTO scripted_review VALUES (?,?,?,?,?,?,?)",
                    (TENANT, SITE, row["case_id"], row["reviewer_id"],
                     row["disposition"], row["reason_code"], 0))
            for row in labels["records"]:
                require(row["synthetic"] is True,
                        "non_synthetic_reference_label")
                db.execute(
                    "INSERT INTO reference_label VALUES (?,?,?,?,?)",
                    (TENANT, SITE, row["case_id"], row["expected_review_label"], 0))
            for path, document_id in SOURCE_IDS.items():
                db.execute(
                    "INSERT INTO source_document VALUES (?,?,?,?,?,?,?,?)",
                    (TENANT, SITE, document_id, path, hashes[path],
                     "SYN-RI-V5-20261107-A",
                     "committed_synthetic_fixture_reconstruction", None))
            for trace in full_trace["record_traces"]:
                origin = trace["origin"]
                source_id = SOURCE_IDS[origin["source_file"]]
                db.execute(
                    "INSERT INTO record_origin VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (TENANT, SITE, trace["trace_id"], source_id,
                     origin["source_dataset"], origin["source_record_id"],
                     origin["json_pointer"], trace["source_record_sha256"],
                     trace["normalized_record_sha256"], None, 0))
                for step in trace["transformations"]:
                    db.execute(
                        "INSERT INTO transform_step VALUES (?,?,?,?,?,?,?,?,?)",
                        (TENANT, SITE, trace["trace_id"], step["ordinal"],
                         step["rule_id"], step["source_field"],
                         step["target_field"], step["source_value_sha256"],
                         step["canonical_value_sha256"]))
    except sqlite3.IntegrityError:
        raise EntitySchemaRejected("preview_constraint_or_relation_failure") from None
    result = preview_counts(db)
    require(result["counts"] == EXPECTED_COUNTS,
            "preview_count_or_fk_mismatch")
    return {
        **result,
        "source_files": len(hashes),
        "v16_reconstructed_origin_count": len(full_trace["record_traces"]),
        "v16_conversion_steps": sum(
            len(row["transformations"]) for row in full_trace["record_traces"]),
        "no_real_ingestion_event": True,
        "customer_source_observed": False,
        "preview_database_persisted": False,
    }


def preview_counts(db: sqlite3.Connection) -> dict[str, Any]:
    counts = {
        name: db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
        for name in EXPECTED_COUNTS
    }
    duration, cost = db.execute(
        "SELECT SUM(downtime_seconds), SUM(repair_cost_cents)"
        " FROM maintenance_case"
    ).fetchone()
    return {
        "counts": counts,
        "total_rows": sum(counts.values()),
        "synthetic_duration_seconds": duration,
        "synthetic_cost_cents": cost,
        "foreign_key_violations": len(
            db.execute("PRAGMA foreign_key_check").fetchall()),
    }
