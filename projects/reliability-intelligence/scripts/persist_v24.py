"""V24 synthetic transactional record/event persistence, temporary-file only.

Mavenu architecture V4 p43: Persist validated records and events.
Proof: Transactional integrity tests.

V24.1 uses V23 reversible migrations to initialize a NEW TEMPORARY
SQLite schema (or resume an empty V1 partial initialization). The 120-row
V21 synthetic snapshot is loaded and validated
in :memory: before it is copied with 12 fabricated case events to a file DB
inside one transaction. No customer data, network, production database,
runtime change, CMMS/ERP/OT write or real tenant authentication.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import entity_v21
import identity_v22
import lineage_v16
import migrate_v23

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/data/PERSISTENCE_CONTRACT_V24.json"
NAME = "v24_synthetic.sqlite3"
BATCH = "SYN-V24-BATCH-001"
TENANT = entity_v21.TENANT
SITE = entity_v21.SITE
ZERO = "0" * 64
EXPECTED = dict(entity_v21.EXPECTED_COUNTS)
EVENT_COUNT = 12
LEDGER = (
    "v24_import_batch", "v24_case_event", "v24_commit_receipt"
)

DDL = """
CREATE TABLE v24_import_batch (
  tenant_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  batch_id TEXT NOT NULL CHECK(batch_id='SYN-V24-BATCH-001'),
  source_manifest_sha256 TEXT NOT NULL CHECK(length(source_manifest_sha256)=64),
  declared_record_rows INTEGER NOT NULL CHECK(declared_record_rows=120),
  declared_event_rows INTEGER NOT NULL CHECK(declared_event_rows=12),
  kind TEXT NOT NULL CHECK(kind='synthetic_research_only'),
  PRIMARY KEY(tenant_id,site_id,batch_id),
  FOREIGN KEY(tenant_id,site_id) REFERENCES site(tenant_id,site_id)
) WITHOUT ROWID;
CREATE TABLE v24_case_event (
  tenant_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  event_id TEXT NOT NULL CHECK(event_id LIKE 'SYN-V24-EVENT-%'),
  batch_id TEXT NOT NULL,
  sequence_no INTEGER NOT NULL CHECK(sequence_no BETWEEN 1 AND 100000),
  case_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  event_kind TEXT NOT NULL CHECK(event_kind='synthetic_case_persisted'),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  previous_sha256 TEXT NOT NULL CHECK(length(previous_sha256)=64),
  chain_sha256 TEXT NOT NULL CHECK(length(chain_sha256)=64),
  PRIMARY KEY(tenant_id,site_id,event_id),
  UNIQUE(tenant_id,site_id,batch_id,sequence_no),
  UNIQUE(tenant_id,site_id,batch_id,case_id),
  FOREIGN KEY(tenant_id,site_id,batch_id)
    REFERENCES v24_import_batch(tenant_id,site_id,batch_id),
  FOREIGN KEY(tenant_id,site_id,case_id)
    REFERENCES maintenance_case(tenant_id,site_id,case_id),
  FOREIGN KEY(tenant_id,site_id,asset_id)
    REFERENCES asset(tenant_id,site_id,asset_id)
) WITHOUT ROWID;
CREATE TABLE v24_commit_receipt (
  tenant_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  source_manifest_sha256 TEXT NOT NULL CHECK(length(source_manifest_sha256)=64),
  records_sha256 TEXT NOT NULL CHECK(length(records_sha256)=64),
  final_event_sha256 TEXT NOT NULL CHECK(length(final_event_sha256)=64),
  record_rows INTEGER NOT NULL CHECK(record_rows=120),
  event_rows INTEGER NOT NULL CHECK(event_rows=12),
  receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256)=64),
  PRIMARY KEY(tenant_id,site_id,batch_id),
  FOREIGN KEY(tenant_id,site_id,batch_id)
    REFERENCES v24_import_batch(tenant_id,site_id,batch_id)
) WITHOUT ROWID;
CREATE TRIGGER v24_event_block_update BEFORE UPDATE ON v24_case_event
BEGIN SELECT RAISE(ABORT, 'v24_immutable_event'); END;
CREATE TRIGGER v24_event_block_delete BEFORE DELETE ON v24_case_event
BEGIN SELECT RAISE(ABORT, 'v24_immutable_event'); END;
CREATE TRIGGER v24_batch_block_update BEFORE UPDATE ON v24_import_batch
BEGIN SELECT RAISE(ABORT, 'v24_immutable_batch'); END;
CREATE TRIGGER v24_batch_block_delete BEFORE DELETE ON v24_import_batch
BEGIN SELECT RAISE(ABORT, 'v24_immutable_batch'); END;
CREATE TRIGGER v24_receipt_block_update BEFORE UPDATE ON v24_commit_receipt
BEGIN SELECT RAISE(ABORT, 'v24_immutable_receipt'); END;
CREATE TRIGGER v24_receipt_block_delete BEFORE DELETE ON v24_commit_receipt
BEGIN SELECT RAISE(ABORT, 'v24_immutable_receipt'); END;
"""


class PersistenceRejected(ValueError):
    """Fixed diagnostic only; never echo source or database contents."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise PersistenceRejected(code)


def digest(value: Any) -> str:
    try:
        b = json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError):
        raise PersistenceRejected("invalid_canonical_digest_input") from None
    return hashlib.sha256(b).hexdigest()


def policy() -> dict[str, Any]:
    try:
        obj = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PersistenceRejected("v24_contract_missing") from None
    require(type(obj) is dict, "v24_contract_not_object")
    return obj


def validate_policy(p: dict[str, Any]) -> None:
    require(type(p) is dict and p.get("schema_version") == "1.0.0" and
            p.get("increment") == "V24" and
            p.get("objective") == "Persist validated records and events" and
            p.get("required_proof") == "Transactional integrity tests" and
            p.get("status") ==
            "SYNTHETIC_FILE_BACKED_TEST_CANDIDATE_HUMAN_REVIEW_PENDING" and
            p.get("branch_base") == "feature/reliability-intelligence-v22",
            "v24_contract_objective_or_scope_drift")
    prerequisites = p.get("prerequisites")
    require(type(prerequisites) is dict and
            set(prerequisites) == {
                "v10_formal_promotion", "v20_data_quality_signoff",
                "v21_entity_review", "v22_identity_review",
                "v23_migration_implemented", "v23_up_down_evidence_present",
                "v24_storage_signoff"
            } and all(v is False for v in prerequisites.values()),
            "missing_or_fabricated_v23_or_phase_approval")
    options = p.get("design")
    require(type(options) is dict and options.get("engine") == "SQLite" and
            options.get("mode") ==
            "temporary_file_in_automatic_test_cleanup" and
            options.get("schema_creation") ==
            "new empty temporary database bootstrap ONLY; not a migration" and
            options.get("foreign_keys") is True and
            options.get("journal_mode") == "delete" and
            options.get("synchronous") == "FULL" and
            options.get("sources") == list(entity_v21.SOURCE_IDS) and
            options.get("snapshot_tables") == 10 and
            options.get("snapshot_rows") == 120 and
            options.get("events") == 12 and
            options.get("batches") == 1 and
            options.get("receipts") == 1 and
            options.get("total_rows_in_test_store") == 134 and
            options.get("batch_id") == BATCH and
            options.get("event_prefix") == "SYN-V24-EVENT-" and
            options.get("event_kind") == "synthetic_case_persisted" and
            options.get("delete_on_complete") is True and
            options.get("customer_data_allowed") is False and
            options.get("ot_or_cmms_writes") is False and
            options.get("external_network") is False,
            "v24_storage_controls_drift")
    require(p.get("expected") == {
        "source_files": 3, "snapshot_tables": 10, "snapshot_rows": 120,
        "batch_rows": 1, "event_rows": 12, "receipt_rows": 1,
        "total_rows": 134, "duration_seconds": 163800,
        "repair_cost_cents": 1273500,
        "duplicate_replay_additional_rows": 0,
        "dirty_storage_files_left_after_test": 0,
        "v10_frozen_paths": 18,
    }, "v24_evidence_counts_drift")
    approvals = p.get("approvals")
    require(type(approvals) is dict and
            all(approvals.get(k) is False for k in (
                "v10_formal_phase_promotion", "v20_data_quality_signoff",
                "v21_entity_review", "v22_identity_review",
                "v23_migration_accepted", "v24_persistence_review",
                "production_database_authorized", "customer_data_authorized",
                "ot_cmms_write_authorized"
            )) and
            all(approvals.get(k) is None for k in (
                "named_data_architect", "named_security_reviewer",
                "named_product_owner", "decision_date_utc", "signature"
            )), "v24_false_human_approval")
    require(type(p.get("acceptance")) is list and
            len(p["acceptance"]) >= 7 and
            type(p.get("limitations")) is list and
            len(p["limitations"]) >= 5,
            "v24_review_criteria_missing")


def _controlled_path(path: Path) -> Path:
    require(isinstance(path, Path) and path.name == NAME and not path.is_symlink(),
            "unapproved_test_database_path")
    parent = path.parent.resolve()
    require(parent.parent == Path(tempfile.gettempdir()).resolve() and
            parent.name.startswith("mavenu-v24-") and
            parent.is_dir(),
            "unapproved_non_temp_database_path")
    return parent / NAME


def connect(path: Path) -> sqlite3.Connection:
    """Open only disposable V24 file under a specifically named temp dir."""
    dest = _controlled_path(path)
    db = sqlite3.connect(str(dest), isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=1000")
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1 and
            db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete" and
            db.execute("PRAGMA synchronous").fetchone()[0] == 2,
            "sqlite_transaction_pragmas_not_enforced")
    return db


def bootstrap(db: sqlite3.Connection) -> None:
    """V24.1: initialize via V23 up-migrations, never raw executescript.

    This accepts an empty V0 database or an EMPTY V1 schema left by a failed
    1→2 upgrade. Any existing data, V2 schema, unexpected schema, outside-temp
    database, or unknown version fails closed. The 0→1 and 1→2 steps commit
    separately (V23 design); this does NOT establish all-or-nothing V0→V2.
    """
    before = migrate_v23.validate_version(db)
    require(before["version"] in (0, 1),
            "existing_schema_bootstrap_denied")
    if before["version"] == 1:
        require(all(
            db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0] == 0
            for table in entity_v21.EXPECTED_COUNTS
        ), "nonempty_v1_bootstrap_denied")
    migrated = migrate_v23.migrate_to(db, 2)
    require(migrated["applied_steps"] == 2 - before["version"] and
            migrated["final_state"]["version"] == 2 and
            migrated["final_state"]["tables"] == 13 and
            migrated["final_state"]["triggers"] == 6,
            "v23_migration_initialization_incomplete")
    check_structure(db)


def check_structure(db: sqlite3.Connection) -> dict[str, Any]:
    # V24.1 refuses legacy ad-hoc DDL with no committed V23 schema version.
    require(db.execute("PRAGMA user_version").fetchone()[0] == 2,
            "v23_schema_version_required")
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    require(tables == set(EXPECTED) | set(LEDGER),
            "v24_table_inventory_invalid")
    triggers = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    )}
    require(triggers == {
        "v24_event_block_update", "v24_event_block_delete",
        "v24_batch_block_update", "v24_batch_block_delete",
        "v24_receipt_block_update", "v24_receipt_block_delete"
    }, "append_only_trigger_inventory_drift")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "foreign_keys_disabled")
    require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
            "sqlite_integrity_check_failed")
    return {"schema_tables": len(tables), "append_only_triggers": len(triggers),
            "foreign_keys_enforced": True, "integrity_check": "ok"}


def _canonical_rows(db: sqlite3.Connection) -> list[list[Any]]:
    out = []
    for table, pk in entity_v21.EXPECTED_PKS.items():
        order = ", ".join('"' + field + '"' for field in pk)
        rows = db.execute('SELECT * FROM "' + table +
                          '" ORDER BY ' + order).fetchall()
        out.append([table, [list(row) for row in rows]])
    return out


def records_sha(db: sqlite3.Connection) -> str:
    return digest(_canonical_rows(db))


def _case_rows(db: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT case_id,asset_id,work_order_ref,occurred_at_utc,"
        "downtime_seconds,repair_cost_cents FROM maintenance_case "
        "WHERE tenant_id=? AND site_id=? ORDER BY case_id",
        (TENANT, SITE)
    ).fetchall()


def _event_hash(seq: int, event_id: str, case_id: str,
                asset_id: str, payload: str, previous: str) -> str:
    return digest({
        "sequence": seq, "event_id": event_id, "case_id": case_id,
        "asset_id": asset_id, "payload_sha256": payload,
        "previous_sha256": previous, "event_kind": "synthetic_case_persisted",
        "tenant_id": TENANT, "site_id": SITE, "batch_id": BATCH
    })


def _receipt_hash(manifest: str, snapshot: str, tip: str) -> str:
    return digest({
        "batch_id": BATCH, "tenant_id": TENANT, "site_id": SITE,
        "source_manifest_sha256": manifest, "records_sha256": snapshot,
        "final_event_sha256": tip, "record_rows": 120, "event_rows": 12
    })


def staging() -> tuple[sqlite3.Connection, str]:
    """Validate V21/V22 fixed synthetic sources before disk transaction."""
    docs, source_hashes = lineage_v16.load_source_documents()
    identity_v22.validate_policy(identity_v22.policy())
    ids = identity_v22.validate_sources(docs)
    require(ids["cases"] == EVENT_COUNT and ids["assets"] == 6,
            "v22_source_validation_incomplete")
    memory = entity_v21.create_memory_schema()
    try:
        model = entity_v21.load_model()
        preview = entity_v21.load_synthetic_preview(memory, model)
        entity_v21.validate_catalog(memory, model)
        v22 = identity_v22.validate_sql_keys(memory)
        require(preview["total_rows"] == 120 and
                v22["unresolved_links"] == 0 and
                v22["uniqueness_violations"] == 0,
                "v21_staging_invalid")
        return memory, digest(source_hashes)
    except Exception:
        memory.close()
        raise


def _copy_stage(memory: sqlite3.Connection, db: sqlite3.Connection) -> None:
    for table in EXPECTED:
        columns = memory.execute(
            'PRAGMA table_info("' + table + '")').fetchall()
        require(columns and len(columns) <= 16,
                "unapproved_staging_table_structure")
        rows = memory.execute('SELECT * FROM "' + table + '"').fetchall()
        db.executemany(
            'INSERT INTO "' + table + '" VALUES (' +
            ",".join("?" for _ in columns) + ')', rows
        )


def counts(db: sqlite3.Connection) -> dict[str, int]:
    return {
        table: db.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
        for table in list(EXPECTED) + list(LEDGER)
    }


def verify_integrity(db: sqlite3.Connection,
                     expected_manifest: str | None = None) -> dict[str, Any]:
    check_structure(db)
    actual = counts(db)
    require(all(actual[x] == size for x, size in EXPECTED.items()) and
            actual["v24_import_batch"] == 1 and
            actual["v24_case_event"] == EVENT_COUNT and
            actual["v24_commit_receipt"] == 1,
            "persistent_record_inventory_mismatch")
    require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
            "stored_foreign_key_violation")
    for table in EXPECTED:
        columns = db.execute('PRAGMA table_info("' + table + '")').fetchall()
        pk = tuple(x[1] for x in sorted(
            (c for c in columns if c[5] > 0), key=lambda c: c[5]
        ))
        require(pk == entity_v21.EXPECTED_PKS[table],
                "stored_primary_key_drift")
        require(entity_v21._catalog_foreign_keys(db, table) ==
                sorted(entity_v21.EXPECTED_FKS[table]),
                "stored_foreign_key_definition_drift")
    links = identity_v22.validate_sql_keys(db)
    require(links["unresolved_links"] == 0 and
            links["uniqueness_violations"] == 0,
            "persistent_identity_link_mismatch")
    batch = db.execute("SELECT source_manifest_sha256,declared_record_rows,"
                       "declared_event_rows FROM v24_import_batch WHERE "
                       "tenant_id=? AND site_id=? AND batch_id=?",
                       (TENANT,SITE,BATCH)).fetchone()
    require(batch is not None and batch[1:] == (120,12),
            "stored_batch_invalid")
    if expected_manifest is not None:
        require(batch[0] == expected_manifest, "batch_source_digest_conflict")
    receipt = db.execute(
        "SELECT source_manifest_sha256,records_sha256,final_event_sha256,"
        "record_rows,event_rows,receipt_sha256 FROM v24_commit_receipt "
        "WHERE tenant_id=? AND site_id=? AND batch_id=?",
        (TENANT,SITE,BATCH)
    ).fetchone()
    require(receipt is not None and receipt[0] == batch[0] and
            receipt[3:5] == (120,12),
            "stored_commit_receipt_invalid")
    current_digest = records_sha(db)
    require(current_digest == receipt[1],
            "persistent_snapshot_digest_mismatch")
    case_map = {case[0]: case for case in _case_rows(db)}
    event_rows = db.execute(
        "SELECT sequence_no,event_id,case_id,asset_id,payload_sha256,"
        "previous_sha256,chain_sha256 FROM v24_case_event "
        "WHERE tenant_id=? AND site_id=? ORDER BY sequence_no",
        (TENANT,SITE)
    ).fetchall()
    prev = ZERO
    for sequence,(seq,event_id,case_id,asset_id,payload,before,chain) in enumerate(
        event_rows, start=1
    ):
        require(seq == sequence and
                event_id == "SYN-V24-EVENT-" + str(seq).zfill(3) and
                case_id in case_map and
                case_map[case_id][1] == asset_id and
                before == prev and
                payload == digest(list(case_map[case_id])),
                "persistent_event_sequence_or_payload_invalid")
        computed = _event_hash(
            sequence, event_id, case_id, asset_id, payload, prev
        )
        require(computed == chain,
                "persistent_event_hash_chain_mismatch")
        prev = chain
    require(prev == receipt[2] and
            receipt[5] == _receipt_hash(batch[0],current_digest,prev),
            "stored_receipt_digest_mismatch")
    summary = db.execute(
        "SELECT SUM(downtime_seconds),SUM(repair_cost_cents)"
        " FROM maintenance_case"
    ).fetchone()
    require(summary == (163800,1273500),
            "persisted_synthetic_sum_mismatch")
    return {
        "committed": True, "records": sum(actual[x] for x in EXPECTED),
        "events": actual["v24_case_event"], "batches": 1, "receipts": 1,
        "total_rows": sum(actual.values()),
        "source_manifest_sha256": batch[0],
        "records_sha256": current_digest,
        "event_chain_tip_sha256": prev,
        "receipt_sha256": receipt[5],
        "duration_seconds": summary[0],
        "repair_cost_cents": summary[1],
        "sqlite_integrity": "ok", "foreign_key_violations": 0,
        "identity_uniqueness_violations": 0,
        "customer_data_used": False,
        "actual_production_durability_verified": False,
    }


def commit_snapshot(db: sqlite3.Connection, *,
                    inject_failure: str | None = None,
                    manifest_override: str | None = None) -> dict[str, Any]:
    """Either commit all 134 invented rows, or roll back all of them.

    Idempotent replay checks exact existing data and checksum receipt before
    returning. Injected failures represent process exceptions, not power loss.
    """
    require(inject_failure in (None,"after_records","after_event_4"),
            "unsupported_failure_injection")
    memory, manifest = staging()
    if manifest_override is not None:
        require(type(manifest_override) is str and
                re.fullmatch(r"[0-9a-f]{64}", manifest_override),
                "invalid_manifest_override")
        manifest = manifest_override
    try:
        check_structure(db)
        existing = db.execute(
            "SELECT COUNT(*) FROM v24_import_batch").fetchone()[0]
        if manifest_override is not None:
            require(existing > 0, "source_manifest_override_not_allowed_on_create")
        if existing:
            report = verify_integrity(db, expected_manifest=manifest)
            return {"write_result":"ALREADY_COMMITTED","added_rows":0,
                    "integrity":report}
        require(all(n == 0 for n in counts(db).values()),
                "uncommitted_or_partial_store_present")
        db.execute("BEGIN IMMEDIATE")
        try:
            _copy_stage(memory,db)
            require(all(counts(db)[name] == val for name,val in EXPECTED.items()),
                    "staged_record_count_invalid")
            if inject_failure == "after_records":
                raise PersistenceRejected("injected_failure_after_records")
            db.execute(
                "INSERT INTO v24_import_batch VALUES (?,?,?,?,?,?,?)",
                (TENANT,SITE,BATCH,manifest,120,12,"synthetic_research_only")
            )
            prev = ZERO
            for seq, row in enumerate(_case_rows(db),start=1):
                case_id, asset_id = row[:2]
                event_id = "SYN-V24-EVENT-" + str(seq).zfill(3)
                payload = digest(list(row))
                chain = _event_hash(
                    seq,event_id,case_id,asset_id,payload,prev
                )
                db.execute(
                    "INSERT INTO v24_case_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (TENANT,SITE,event_id,BATCH,seq,case_id,asset_id,
                     "synthetic_case_persisted",payload,prev,chain)
                )
                prev = chain
                if inject_failure == "after_event_4" and seq == 4:
                    raise PersistenceRejected("injected_failure_after_event_4")
            require(seq == EVENT_COUNT, "event_count_invalid")
            snapshot = records_sha(db)
            receipt = _receipt_hash(manifest,snapshot,prev)
            db.execute(
                "INSERT INTO v24_commit_receipt VALUES (?,?,?,?,?,?,?,?,?)",
                (TENANT,SITE,BATCH,manifest,snapshot,prev,120,12,receipt)
            )
            result = verify_integrity(db, expected_manifest=manifest)
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        return {"write_result":"COMMITTED","added_rows":134,
                "integrity":result}
    finally:
        memory.close()


def inspect_reopen(path: Path, manifest: str) -> dict[str, Any]:
    db = connect(path)
    try:
        return verify_integrity(db, expected_manifest=manifest)
    finally:
        db.close()


def run_scenario(*, inject_failure: str | None = None) -> dict[str, Any]:
    """Reopen evidence and dispose of temporary file on context exit."""
    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
        path = Path(dirname) / NAME
        db = connect(path)
        try:
            bootstrap(db)
            try:
                first = commit_snapshot(db,inject_failure=inject_failure)
            except PersistenceRejected:
                if inject_failure is None:
                    raise
                require(all(v == 0 for v in counts(db).values()),
                        "injected_failure_not_atomically_rolled_back")
                db.close()
                reopened = connect(path)
                try:
                    require(all(v == 0 for v in counts(reopened).values()),
                            "rollback_not_durable_after_reopen")
                    first = commit_snapshot(reopened)
                finally:
                    reopened.close()
                db = connect(path)
            report = verify_integrity(db)
            db.close()
            after = inspect_reopen(path,report["source_manifest_sha256"])
            retry = connect(path)
            try:
                replay = commit_snapshot(retry)
            finally:
                retry.close()
            require(replay["write_result"] == "ALREADY_COMMITTED" and
                    replay["added_rows"] == 0 and
                    after["receipt_sha256"] == report["receipt_sha256"],
                    "replay_or_reopen_not_idempotent")
            return {
                "first_write":first["write_result"],
                "fault_injection":inject_failure or "none",
                "reopen_integrity":after,
                "second_write":replay["write_result"],
                "duplicate_rows_added":replay["added_rows"],
                "used_temporary_file":True,
                "file_deleted_after_context":True,
            }
        finally:
            db.close()
