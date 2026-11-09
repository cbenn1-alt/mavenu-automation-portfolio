"""V23 reversible, transaction-safe schema migrations for synthetic SQLite.

Architecture V4, p43: Implement reversible schema migration path.
Proof: Up/down migration evidence.

V23 is a backfill after V24 had already been merged onto the V22 branch.
Only disposable temporary files are supported; no customer databases,
production upgrades, real data, persistent credentials, or automatic human
approval. Each *adjacent* migration is one BEGIN IMMEDIATE/COMMIT block.
Destructive downgrades fail closed if affected tables contain any rows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import entity_v21

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/data/MIGRATION_CONTRACT_V23.json"
FILE_NAME = "v23_synthetic.sqlite3"
VERSION_MIN = 0
VERSION_MAX = 2
V21_TABLES = tuple(entity_v21.EXPECTED_COUNTS)
V24_TABLES = ("v24_import_batch", "v24_case_event",
              "v24_commit_receipt")
V24_TRIGGERS = (
    "v24_event_block_update", "v24_event_block_delete",
    "v24_batch_block_update", "v24_batch_block_delete",
    "v24_receipt_block_update", "v24_receipt_block_delete",
)
V21_DROP_ORDER = (
    "transform_step", "record_origin", "source_document",
    "reference_label", "scripted_review", "evidence_reference",
    "maintenance_case", "asset", "site", "tenant",
)
V24_DROP_ORDER = (
    "v24_commit_receipt", "v24_case_event", "v24_import_batch",
)
FAULTS = (
    "up_v1_after_3_tables", "up_v2_after_1_ledger",
    "down_v2_after_1_drop", "down_v1_after_4_drops",
)


class MigrationRejected(ValueError):
    """Deterministic error category with no user data in the message."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise MigrationRejected(code)


def policy() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise MigrationRejected("migration_contract_unavailable") from None
    require(type(value) is dict, "migration_contract_not_object")
    return value


def validate_policy(record: dict[str, Any]) -> None:
    require(type(record) is dict and
            record.get("schema_version") == "1.0.0" and
            record.get("increment") == "V23" and
            record.get("objective") ==
            "Implement reversible schema migration path" and
            record.get("required_proof") == "Up/down migration evidence" and
            record.get("state") ==
            "SYNTHETIC_TECHNICAL_MIGRATION_CANDIDATE_UNREVIEWED" and
            record.get("baseline_branch") ==
            "feature/reliability-intelligence-v22",
            "migration_objective_or_state_drift")
    design = record.get("design")
    require(type(design) is dict and
            design.get("engine") == "SQLite" and
            design.get("allowed_storage") ==
            "disposable temporary SQLite files only" and
            design.get("file_prefixes") ==
            ["mavenu-v23-", "mavenu-v24-"] and
            design.get("allowed_filenames") ==
            ["v23_synthetic.sqlite3", "v24_synthetic.sqlite3"] and
            design.get("source_v21") ==
            "docs/data/SCHEMA_DESIGN_V21.sql" and
            design.get("source_v24") ==
            "scripts/persist_v24.py:DDL" and
            design.get("schema_versioning") ==
            "PRAGMA user_version; integer 0/1/2, committed within each DDL transaction" and
            design.get("upgrade_chain") == [[0,1],[1,2]] and
            design.get("downgrade_chain") == [[2,1],[1,0]] and
            design.get("foreign_keys_enabled") is True and
            design.get("transactional_ddl") is True and
            design.get("destructive_down_migrations_require_empty_affected_tables") is True and
            design.get("nonempty_v21_data_retained_across_v1_to_v2_to_v1") is True and
            design.get("failure_injection") == list(FAULTS) and
            design.get("fail_closed_on_unknown_versions") is True and
            design.get("fail_closed_on_unexpected_schema") is True and
            design.get("no_real_customer_data") is True and
            design.get("no_production_upgrade") is True and
            design.get("no_OT_or_CMMS_write") is True and
            design.get("manual_human_approval_pending") is True,
            "migration_policy_controls_drift")
    require(record.get("expected") == {
        "v0_tables":0,"v1_tables":10,"v2_tables":13,
        "v2_triggers":6,"up_steps":2,"down_steps":2,
        "injected_rollback_cases":4,"data_preserving_roundtrips":1,
        "rejected_destructive_downgrades":2,
        "source_fixture_rows":120,"source_documents":3,
        "retained_rows_after_v2_to_v1":120,"actual_customer_records":0,
    }, "migration_expected_controls_drift")
    stages = record.get("stages")
    require(type(stages) is list and
            len(stages) == 2 and
            [(x.get("from"),x.get("to"),x.get("expected_tables"),
              x.get("expected_triggers")) for x in stages
             if type(x) is dict] ==
            [(0,1,10,0),(1,2,13,6)],
            "migration_stage_inventory_drift")
    approvals = record.get("decision")
    require(type(approvals) is dict, "migration_signoff_missing")
    for k in ("v10_formal_promotion","v20_data_quality_signoff",
              "v21_entity_schema_human_review","v22_identity_human_review",
              "v23_migration_human_review","v24_persistence_human_review",
              "customer_data_access_authorized",
              "production_schema_change_authorized"):
        require(approvals.get(k) is False, "migration_false_approval")
    for k in ("named_data_architect","named_database_administrator",
              "named_security_reviewer","reviewed_at_utc",
              "approval_signature"):
        require(approvals.get(k) is None, "migration_fake_reviewer")
    require(type(record.get("limitations")) is list and
            len(record["limitations"]) >= 5,
            "migration_limitations_missing")


def _check_temporary_db(db: sqlite3.Connection) -> Path:
    require(isinstance(db, sqlite3.Connection), "invalid_db_connection")
    locations = db.execute("PRAGMA database_list").fetchall()
    main = [x for x in locations if x[1] == "main"]
    require(len(main) == 1 and type(main[0][2]) is str and
            main[0][2], "persistent_temporary_file_required")
    file = Path(main[0][2])
    require(file.name in (FILE_NAME,"v24_synthetic.sqlite3") and
            not file.is_symlink() and
            file.parent.is_dir(), "non_test_storage_denied")
    parent = file.parent.resolve()
    require(parent.parent == Path(tempfile.gettempdir()).resolve() and
            parent.name.startswith(("mavenu-v23-","mavenu-v24-")),
            "non_temporary_storage_denied")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "migration_requires_foreign_keys")
    return file


def connect(path: Path) -> sqlite3.Connection:
    """Open the V23 name only within a newly created test temp directory."""
    require(isinstance(path, Path) and path.name == FILE_NAME and
            not path.is_symlink() and path.parent.is_dir() and
            path.parent.resolve().parent ==
            Path(tempfile.gettempdir()).resolve() and
            path.parent.name.startswith("mavenu-v23-"),
            "unapproved_migration_database_path")
    db = sqlite3.connect(str(path.resolve()), isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1 and
            db.execute("PRAGMA synchronous").fetchone()[0] == 2,
            "migration_sqlite_pragmas_failed")
    return db


def _get_version(db: sqlite3.Connection) -> int:
    raw = db.execute("PRAGMA user_version").fetchone()[0]
    require(type(raw) is int and raw in (0,1,2),
            "unknown_schema_version")
    return raw


def _tables_triggers(db: sqlite3.Connection) -> tuple[set[str],set[str]]:
    tables = {x[0] for x in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    triggers = {x[0] for x in db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    )}
    return tables,triggers


def _schema_fingerprint(db: sqlite3.Connection) -> str:
    value = db.execute(
        "SELECT type,name,sql FROM sqlite_master "
        "WHERE type IN ('table','trigger') ORDER BY type,name"
    ).fetchall()
    body = json.dumps(value,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_version(db: sqlite3.Connection,
                     expect: int | None = None) -> dict[str, Any]:
    _check_temporary_db(db)
    version = _get_version(db)
    if expect is not None:
        require(version == expect, "unexpected_schema_version")
    tables,triggers = _tables_triggers(db)
    target_tables = (set() if version == 0 else
                     set(V21_TABLES) if version == 1 else
                     set(V21_TABLES)|set(V24_TABLES))
    target_triggers = set(V24_TRIGGERS) if version == 2 else set()
    require(tables == target_tables and triggers == target_triggers,
            "unexpected_physical_schema")
    if version >= 1:
        for name in V21_TABLES:
            cols = db.execute('PRAGMA table_info("' + name + '")').fetchall()
            primary = tuple(c[1] for c in sorted(
                (x for x in cols if x[5] > 0), key=lambda x: x[5]))
            require(primary == entity_v21.EXPECTED_PKS[name],
                    "schema_primary_key_drift")
            require(entity_v21._catalog_foreign_keys(db,name) ==
                    sorted(entity_v21.EXPECTED_FKS[name]),
                    "schema_foreign_key_drift")
    if version == 2:
        import persist_v24
        require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                "schema_foreign_key_violation")
        require(all(x in persist_v24.DDL for x in V24_TRIGGERS),
                "v24_trigger_specification_drift")
    require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and
            db.execute("PRAGMA foreign_key_check").fetchall() == [],
            "schema_integrity_check_failed")
    return {
        "version":version,"tables":len(tables),"triggers":len(triggers),
        "schema_sha256":_schema_fingerprint(db),
        "foreign_key_violations":0,"integrity":"ok",
        "temporary_file_only":True,
    }


def _statements(source: str, expected: str) -> list[str]:
    """Split SQLite statements respecting CREATE TRIGGER BEGIN/END blocks.

    PRAGMA foreign_keys=ON in historical V21 DDL is validated out-of-band,
    because changing FK mode inside a transaction would silently do nothing.
    """
    source = "\n".join(line for line in source.splitlines()
                       if not line.lstrip().startswith("--")) + "\n"
    collected,buf = [],""
    for line in source.splitlines(keepends=True):
        buf += line
        if not sqlite3.complete_statement(buf):
            continue
        item = buf.strip()
        buf = ""
        if re.fullmatch(r"PRAGMA\s+foreign_keys\s*=\s*ON\s*;",
                        item,re.I):
            continue
        require(item.upper().startswith("CREATE TABLE ") or
                item.upper().startswith("CREATE TRIGGER "),
                "disallowed_migration_ddl")
        collected.append(item)
    require(not buf.strip(), "incomplete_migration_ddl")
    table_count = sum(x.upper().startswith("CREATE TABLE ") for x in collected)
    trigger_count = sum(x.upper().startswith("CREATE TRIGGER ") for x in collected)
    require((table_count,trigger_count) ==
            ((10,0) if expected == "v21" else (3,6)),
            "migration_ddl_statement_count")
    return collected


def _source_statements(version: int) -> list[str]:
    if version == 1:
        try:
            raw=entity_v21.DDL_PATH.read_text(encoding="utf-8")
        except (OSError,UnicodeError):
            raise MigrationRejected("missing_v21_schema_source") from None
        return _statements(raw,"v21")
    import persist_v24
    return _statements(persist_v24.DDL,"v24")


def _no_rows(db: sqlite3.Connection, tables: tuple[str,...],
             code: str) -> None:
    for name in tables:
        count = db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
        require(count == 0,code)


def migrate_step(db: sqlite3.Connection, target: int,
                 *, inject_failure: str | None = None) -> dict[str, Any]:
    """One adjacent up/down migration with atomic DDL and rollback on error."""
    _check_temporary_db(db)
    require(type(target) is int and target in (0,1,2),
            "invalid_migration_target")
    require(inject_failure is None or inject_failure in FAULTS,
            "invalid_migration_failure_injection")
    before = validate_version(db)
    current = before["version"]
    require(abs(target-current)==1, "non_adjacent_migration_denied")
    require(not db.in_transaction, "nested_migration_transaction_denied")
    if target < current:
        _no_rows(db,
                 V24_DROP_ORDER if current == 2 else V21_DROP_ORDER,
                 "data_bearing_downgrade_denied")
    if current == 0 and target == 1:
        operations = _source_statements(1)
        relevant_fault = "up_v1_after_3_tables"
    elif current == 1 and target == 2:
        operations = _source_statements(2)
        relevant_fault = "up_v2_after_1_ledger"
    elif current == 2 and target == 1:
        operations = ['DROP TABLE "' + x + '"' for x in V24_DROP_ORDER]
        relevant_fault = "down_v2_after_1_drop"
    else:
        operations = ['DROP TABLE "' + x + '"' for x in V21_DROP_ORDER]
        relevant_fault = "down_v1_after_4_drops"
    require(inject_failure is None or inject_failure == relevant_fault,
            "failure_injection_step_mismatch")
    db.execute("BEGIN IMMEDIATE")
    try:
        for i,sql in enumerate(operations,start=1):
            db.execute(sql)
            if inject_failure and (
                (relevant_fault=="up_v1_after_3_tables" and i==3) or
                (relevant_fault=="up_v2_after_1_ledger" and i==1) or
                (relevant_fault=="down_v2_after_1_drop" and i==1) or
                (relevant_fault=="down_v1_after_4_drops" and i==4)
            ):
                raise MigrationRejected("injected_migration_rollback_" +
                                        relevant_fault)
        db.execute("PRAGMA user_version = " + str(target))
        after = validate_version(db,target)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        # Rollback restores previous schema version and table inventory.
        validate_version(db,current)
        raise
    return {
        "from":current,"to":target,"statements":len(operations),
        "before_schema_sha256":before["schema_sha256"],
        "after_schema_sha256":after["schema_sha256"],
        "result":"MIGRATED_SYNTHETIC_TEMP_DB",
        "data_loss_allowed":False,
    }


def migrate_to(db: sqlite3.Connection,target: int) -> dict[str, Any]:
    """Run adjacent migrations sequentially; each step commits on its own."""
    require(type(target) is int and target in (0,1,2),
            "invalid_migration_target")
    steps=[]
    state=validate_version(db)["version"]
    while state!=target:
        next_version=state+(1 if target>state else -1)
        steps.append(migrate_step(db,next_version))
        state=next_version
    return {
        "target_version":target,
        "steps":steps,
        "applied_steps":len(steps),
        "final_state":validate_version(db,target),
        "production_migration_authorized":False,
    }
