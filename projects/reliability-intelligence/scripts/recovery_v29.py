"""V29 synthetic SQLite restore and corruption-response drill.

Mavenu architecture V4 p43:
  V29 Execute restore and corruption response drill.
  Proof: Timed restore evidence.

Uses V23/V24.1 schema and V24 committed fabricated 134-row evidence.
Three disposable temporary databases are removed after each scenario.
No real power loss, customer records, V28 archive restore, production
disaster recovery, RTO/RPO service commitment or retained backup.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any
from urllib.parse import quote

import migrate_v23
import persist_v24

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/data/RESTORE_DRILL_CONTRACT_V29.json"
SUCCESS_CASES = (
    "intact_baseline_restore",
    "logical_active_corruption_restore",
    "physical_active_corruption_restore",
)
REFUSAL_CASES = (
    "missing_backup",
    "tampered_backup_record",
    "corrupt_backup_header",
    "injected_after_restore_copy",
)
MAX_RESTORE_MS = 10000
ROW_COUNT = 134
EVENT_COUNT = 12


class RecoveryRejected(ValueError):
    """Stable non-sensitive failure; never contains customer data."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise RecoveryRejected(code)


def policy() -> dict[str, Any]:
    try:
        value=json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError):
        raise RecoveryRejected("v29_contract_missing") from None
    require(type(value) is dict,"v29_contract_not_object")
    return value


def validate_policy(value:dict[str,Any]) -> None:
    require(type(value) is dict and
            value.get("schema_version")=="1.0.0" and
            value.get("increment")=="V29" and
            value.get("objective")==
            "Execute restore and corruption response drill" and
            value.get("required_proof")=="Timed restore evidence" and
            value.get("state")=="SYNTHETIC_RESTORE_DRILL_HUMAN_REVIEW_PENDING" and
            value.get("base_branch")=="feature/reliability-intelligence-v22",
            "v29_contract_identity_drift")
    d=value.get("recovery_design")
    require(type(d) is dict and
            d.get("method")==
            "SQLite online backup to a clean independent temporary target, followed by reopening and V24 receipt/event integrity checks" and
            d.get("source_backup_restore_dirs")==
            "three automatically deleted mavenu-v24-* folders" and
            d.get("source_filename")==persist_v24.NAME and
            d.get("synthetic_case_event_rows")==12 and
            d.get("synthetic_total_rows")==ROW_COUNT and
            d.get("version")==2 and
            d.get("scenarios_success")==list(SUCCESS_CASES) and
            d.get("scenarios_refused")==list(REFUSAL_CASES) and
            d.get("source_corruption_detection_required") is True and
            d.get("fail_closed_no_target_on_invalid_backup") is True and
            d.get("reject_restored_target_on_injected_failure") is True and
            d.get("expected_zero_added_rows_on_idempotent_replay") is True and
            d.get("clock")=="time.perf_counter_ns" and
            d.get("timing_fields_ms")==[
                "backup_preflight_ms","restore_copy_ms",
                "restore_verify_ms","restore_total_ms"] and
            d.get("max_synthetic_restore_total_ms")==MAX_RESTORE_MS and
            d.get("sample_count_per_scenario")==1 and
            d.get("retention_v28_sidecar_restore_included") is False and
            d.get("production_backup_retained") is False and
            d.get("real_power_loss_tested") is False and
            d.get("real_customer_data_used") is False and
            d.get("real_offsite_copy_used") is False and
            d.get("scheduler_activated") is False and
            d.get("restore_is_not_production_dr_test") is True,
            "v29_restore_scope_or_timing_changed")
    require(d.get("security_and_integrity")==[
        "verify backup before target creation",
        "validate receipt and source manifest",
        "check schema version 2",
        "validate FK and SQLite integrity",
        "reopen restored target",
        "reject compromised backup",
        "never overwrite source",
        "delete failed target",
    ],"v29_integrity_check_inventory_drift")
    require(value.get("expected")=={
        "successful_restores":3,"refused_restores":4,
        "backup_corruption_rejections":2,
        "missing_backup_rejections":1,
        "injected_restore_rollbacks":1,
        "restored_rows_per_success":134,
        "restored_events_per_success":12,
        "synthetic_data_loss_rows":0,
        "target_schema_version":2,
        "v10_frozen_source_paths":18,
        "fixture_hashes_unchanged":True
    },"v29_expected_outcome_drift")
    g=value.get("governance")
    require(type(g) is dict,"v29_governance_missing")
    for field in (
        "v10_phase_promotion_approved","v20_data_quality_signoff",
        "v21_to_v28_human_reviews_approved",
        "v26_production_isolation_approved",
        "v27_backup_schedule_approved","v28_retention_policy_approved",
        "v29_restore_drill_approved","production_rpo_approved",
        "production_rto_approved","production_disaster_recovery_approved",
        "actual_customer_data_access","backup_encryption_approved",
        "backup_retention_approved","actual_recovery_site_available"
    ):
        require(g.get(field) is False,"v29_false_human_or_dr_approval")
    for field in ("owner","dba_reviewer","security_reviewer",
                  "reviewed_at_utc","signature"):
        require(g.get(field) is None,"v29_fabricated_signoff")
    require(type(value.get("risks")) is list and
            len(value["risks"])>=7 and
            type(value.get("human_readiness_gates")) is list and
            len(value["human_readiness_gates"])>=6,
            "v29_missing_readiness_gates")


def safe_path(path:Path) -> None:
    require(isinstance(path,Path) and path.name==persist_v24.NAME and
            not path.is_symlink() and path.parent.is_dir() and
            not path.parent.is_symlink() and
            path.parent.resolve().parent==
            Path(tempfile.gettempdir()).resolve() and
            path.parent.name.startswith("mavenu-v24-"),
            "uncontrolled_restore_path")


def _read_only(path:Path)->sqlite3.Connection:
    safe_path(path)
    require(path.is_file() and path.stat().st_size>0,
            "backup_missing_or_empty")
    # Read-only preflight cannot silently manufacture an empty backup.
    uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
    try:
        db=sqlite3.connect(uri,uri=True,isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        return db
    except sqlite3.Error:
        try:
            db.close()
        except (UnboundLocalError,sqlite3.Error):
            pass
        raise RecoveryRejected("backup_unreadable_or_corrupt") from None


def integrity(db:sqlite3.Connection, manifest:str,
              receipt:str) -> dict[str,Any]:
    try:
        schema=migrate_v23.validate_version(db,2)
        data=persist_v24.verify_integrity(
            db,expected_manifest=manifest)
    except (sqlite3.Error,migrate_v23.MigrationRejected,
            persist_v24.PersistenceRejected):
        raise RecoveryRejected("backup_checksum_or_schema_failed") from None
    require(schema["tables"]==13 and schema["triggers"]==6 and
            data["receipt_sha256"]==receipt and
            data["total_rows"]==ROW_COUNT and
            data["events"]==EVENT_COUNT and
            data["sqlite_integrity"]=="ok" and
            data["foreign_key_violations"]==0,
            "backup_receipt_or_inventory_mismatch")
    return {
        "schema_version":schema["version"],
        "tables":schema["tables"],
        "receipt_sha256":data["receipt_sha256"],
        "source_manifest_sha256":data["source_manifest_sha256"],
        "rows":data["total_rows"],
        "events":data["events"],
        "foreign_keys":"PASS",
        "sqlite_integrity":"ok",
    }


def _elapsed(start:int)->float:
    return round((time.perf_counter_ns()-start)/1_000_000,4)


def restore(backup_path:Path,target_path:Path,
            expected_manifest:str,expected_receipt:str,
            *,inject_after_copy:bool=False)->dict[str,Any]:
    """Fail-closed restore into a NEW temporary target after preflight.

    The calling test owns the source/backup. Never overwrites a source,
    previously existing target or backup. On any failure deletes target.
    """
    safe_path(backup_path)
    safe_path(target_path)
    require(backup_path!=target_path and
            backup_path.parent!=target_path.parent,
            "restore_source_and_target_not_isolated")
    require(not target_path.exists(),"restore_target_must_be_absent")
    require(type(expected_manifest) is str and
            len(expected_manifest)==64 and
            type(expected_receipt) is str and
            len(expected_receipt)==64,
            "invalid_restore_receipt_or_manifest")
    start=time.perf_counter_ns()
    backup=None
    target=None
    good=False
    try:
        backup=_read_only(backup_path)
        preflight=integrity(backup,expected_manifest,expected_receipt)
        elapsed_preflight=_elapsed(start)
        target=persist_v24.connect(target_path)
        copy_start=time.perf_counter_ns()
        backup.backup(target,pages=8,sleep=0)
        copied_ms=_elapsed(copy_start)
        if inject_after_copy:
            raise RecoveryRejected("injected_restore_copy_abort")
        verify_start=time.perf_counter_ns()
        verified=integrity(target,expected_manifest,expected_receipt)
        target.close()
        target=None
        reopened=persist_v24.inspect_reopen(
            target_path,expected_manifest)
        require(reopened["receipt_sha256"]==expected_receipt and
                reopened["total_rows"]==ROW_COUNT and
                reopened["events"]==EVENT_COUNT,
                "restored_target_reopen_mismatch")
        verify_ms=_elapsed(verify_start)
        result={
            "status":"SUCCESS",
            "restore_copy_ms":copied_ms,
            "backup_preflight_ms":elapsed_preflight,
            "restore_verify_ms":verify_ms,
            "restore_total_ms":_elapsed(start),
            "schema_version":verified["schema_version"],
            "restored_rows":verified["rows"],
            "restored_events":verified["events"],
            "receipt_sha256":verified["receipt_sha256"],
            "source_manifest_sha256":verified["source_manifest_sha256"],
            "reopened_target":True,
            "synthetic_post_backup_writes":0,
            "synthetic_data_loss_rows":0,
            "production_rto_approved":False,
            "production_rpo_approved":False,
            "real_customer_data_restored":False,
        }
        require(result["restore_total_ms"]<=MAX_RESTORE_MS,
                "synthetic_restore_threshold_exceeded")
        good=True
        return result
    except RecoveryRejected:
        raise
    except (sqlite3.Error,persist_v24.PersistenceRejected,
            migrate_v23.MigrationRejected):
        raise RecoveryRejected("restore_failed_integrity_or_copy") from None
    finally:
        if target is not None:
            target.close()
        if backup is not None:
            backup.close()
        if not good and target_path.exists():
            target_path.unlink()
        if not good:
            require(not target_path.exists(),
                    "failed_restore_left_partial_target")


def _damage_active(db:sqlite3.Connection,kind:str,path:Path)->str:
    require(kind in (
        "logical_active_corruption_restore",
        "physical_active_corruption_restore"
    ),"unknown_active_corruption")
    if kind=="logical_active_corruption_restore":
        db.execute(
            "UPDATE maintenance_case SET repair_cost_cents="
            "repair_cost_cents+1 WHERE case_id='SYN-CASE-001'"
        )
        return "checksum_mismatch_detected"
    db.close()
    # This is synthetic physical corruption only, NEVER a customer DB.
    with path.open("r+b") as handle:
        handle.write(b"INVALID-SQLITE29!")
        handle.flush()
        os.fsync(handle.fileno())
    return "sqlite_header_corruption_detected"


def _detect_damaged_active(path:Path,kind:str,
                            manifest:str,receipt:str)->bool:
    try:
        db=_read_only(path)
        try:
            integrity(db,manifest,receipt)
        finally:
            db.close()
    except RecoveryRejected:
        return True
    return False


def _damage_backup(path:Path,kind:str)->None:
    require(kind in ("tampered_backup_record","corrupt_backup_header"),
            "unsupported_backup_corruption")
    if kind=="tampered_backup_record":
        db=persist_v24.connect(path)
        try:
            db.execute(
                "UPDATE maintenance_case SET repair_cost_cents="
                "repair_cost_cents+1 WHERE case_id='SYN-CASE-001'"
            )
        finally:
            db.close()
    else:
        with path.open("r+b") as handle:
            handle.write(b"INVALID-SQLITE29!")
            handle.flush()
            os.fsync(handle.fileno())


def run_scenario(name:str)->dict[str,Any]:
    require(name in SUCCESS_CASES+REFUSAL_CASES,
            "unknown_v29_drill_case")
    validate_policy(policy())
    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as srcdir:
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as backupdir:
            with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as restdir:
                srcpath=Path(srcdir)/persist_v24.NAME
                backuppath=Path(backupdir)/persist_v24.NAME
                targetpath=Path(restdir)/persist_v24.NAME
                source=persist_v24.connect(srcpath)
                backup=None
                try:
                    persist_v24.bootstrap(source)
                    receipt_data=persist_v24.commit_snapshot(source)
                    require(receipt_data["write_result"]=="COMMITTED",
                            "synthetic_source_commit_failed")
                    data=receipt_data["integrity"]
                    manifest=data["source_manifest_sha256"]
                    receipt=data["receipt_sha256"]
                    require(data["total_rows"]==ROW_COUNT and
                            data["events"]==EVENT_COUNT,
                            "source_snapshot_invalid")
                    backup=persist_v24.connect(backuppath)
                    source.backup(backup,pages=8,sleep=0)
                    copied=integrity(backup,manifest,receipt)
                    backup.close()
                    backup=None
                    source.close()
                    source=None
                    require(copied["rows"]==ROW_COUNT,
                            "backup_preparation_invalid")
                    corrupted_active=False
                    if name in (
                        "logical_active_corruption_restore",
                        "physical_active_corruption_restore"
                    ):
                        active=persist_v24.connect(srcpath)
                        try:
                            _damage_active(active,name,srcpath)
                        finally:
                            active.close()
                        corrupted_active=_detect_damaged_active(
                            srcpath,name,manifest,receipt)
                        require(corrupted_active,"corrupted_active_not_detected")
                    if name=="missing_backup":
                        backuppath.unlink()
                    if name in (
                        "tampered_backup_record","corrupt_backup_header"
                    ):
                        _damage_backup(backuppath,name)
                    started=time.perf_counter_ns()
                    if name in SUCCESS_CASES:
                        evidence=restore(
                            backuppath,targetpath,manifest,receipt)
                        require(targetpath.exists() and
                                evidence["status"]=="SUCCESS" and
                                evidence["synthetic_data_loss_rows"]==0,
                                "successful_restore_not_independent")
                        result={
                            "case":name,"status":"SUCCESS",
                            "source_corruption_detected":corrupted_active,
                            "source_not_overwritten":True,
                            "restore":evidence,
                            "expected_restore_rows":ROW_COUNT,
                            "backup_compromised":False,
                            "verified_target":True,
                            "duration_ms":_elapsed(started),
                        }
                    else:
                        try:
                            restore(backuppath,targetpath,manifest,receipt,
                                inject_after_copy=(
                                    name=="injected_after_restore_copy"))
                        except RecoveryRejected as error:
                            code=str(error)
                            require(code in (
                                "backup_missing_or_empty",
                                "backup_checksum_or_schema_failed",
                                "backup_unreadable_or_corrupt",
                                "injected_restore_copy_abort",
                            ),"unexpected_restore_refusal_category")
                        else:
                            raise RecoveryRejected(
                                "untrusted_backup_was_accepted")
                        require(not targetpath.exists(),
                                "refused_restore_left_target")
                        result={
                            "case":name,"status":"REFUSED",
                            "failure_code":code,
                            "target_created_after_failure":False,
                            "source_not_overwritten":True,
                            "accepted_rows":0,
                            "backup_compromised":name in (
                                "tampered_backup_record",
                                "corrupt_backup_header","missing_backup"),
                            "duration_ms":_elapsed(started),
                            "production_incident_inferred":False,
                        }
                finally:
                    if backup is not None:
                        backup.close()
                    if source is not None:
                        source.close()
            require(not targetpath.exists(),
                    "restore_temp_target_not_cleaned")
        require(not backuppath.exists(),
                "backup_temp_file_not_cleaned")
    require(not srcpath.exists(),"source_temp_file_not_cleaned")
    result["temporary_files_cleaned"]=True
    result["real_customer_data_used"]=False
    result["v28_retention_legal_holds_restored"]=False
    return result


def run_evidence()->dict[str,Any]:
    validate_policy(policy())
    successes=[run_scenario(n) for n in SUCCESS_CASES]
    refused=[run_scenario(n) for n in REFUSAL_CASES]
    require(len(successes)==3 and len(refused)==4 and
            all(x["status"]=="SUCCESS" and
                x["restore"]["reopened_target"] and
                x["restore"]["restored_rows"]==ROW_COUNT and
                x["restore"]["restored_events"]==EVENT_COUNT and
                x["restore"]["schema_version"]==2 and
                x["restore"]["restore_total_ms"]<=MAX_RESTORE_MS
                for x in successes) and
            all(x["status"]=="REFUSED" and
                x["accepted_rows"]==0 and
                not x["target_created_after_failure"]
                for x in refused) and
            all(x["temporary_files_cleaned"] for x in successes+refused) and
            successes[1]["source_corruption_detected"] and
            successes[2]["source_corruption_detected"] and
            len({x["restore"]["receipt_sha256"] for x in successes})==1,
            "v29_restore_evidence_matrix_mismatch")
    return {
        "increment":"V29",
        "objective":"Execute restore and corruption response drill",
        "required_proof":"Timed restore evidence",
        "technical_evidence":"PASS",
        "successful_restores":len(successes),
        "refused_restores":len(refused),
        "timed_recovery_scenarios":successes,
        "corruption_and_failure_scenarios":refused,
        "simulated_zero_post_snapshot_writes":True,
        "source_customer_data":False,
        "actual_production_rpo_validated":False,
        "actual_production_rto_validated":False,
        "v28_legal_hold_and_retention_restore":False,
        "retained_backup_after_test":False,
        "independent_production_recovery_environment":False,
        "human_dr_signoff":"PENDING",
    }
