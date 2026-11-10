"""V27 disposable synthetic backup schedule, copy verification and telemetry.

Controlled architecture: Schedule backups and integrity checks.
Required proof: Backup success telemetry.

All source/backup files are isolated SQLite TEMPORARY files (mavenu-v24-*
directories), containing fabricated V24 rows. The daily schedule is only
evaluated against explicit UTC test instants. No unattended scheduler or
retained backup exists. No production restore/RPO/RTO, customer data rights,
authenticated tenant, encryption or offsite storage is implemented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any

import migrate_v23
import persist_v24

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/data/BACKUP_SCHEDULE_V27.json"
UTC = timezone.utc
ANCHOR = datetime(2026, 11, 8, 2, 15, tzinfo=UTC)
GRACE = timedelta(minutes=30)
STATES = ("NOT_STARTED", "CURRENT", "DUE", "MISSED")
INJECTIONS = ("before_copy", "tamper_after_copy", "source_digest_invalid")
FIXED_MANIFEST = "SYN-BACKUP-POLICY-V27"
GOOD_RUNS = (
    ("2026-11-09T02:20:00Z", "2026-11-08T02:20:00Z"),
    ("2026-11-10T02:20:00Z", "2026-11-09T02:20:00Z"),
)
NEGATIVE_RUNS = tuple(
    ("2026-11-09T02:20:00Z", "2026-11-08T02:20:00Z", kind)
    for kind in INJECTIONS
)


class BackupRejected(ValueError):
    """Stable failure code without copying source contents to the log."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise BackupRejected(code)


def policy() -> dict[str, Any]:
    try:
        record = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BackupRejected("v27_contract_unavailable") from None
    require(type(record) is dict, "v27_contract_not_object")
    return record


def validate_policy(record: dict[str, Any]) -> None:
    require(type(record) is dict and
            record.get("schema_version") == "1.0.0" and
            record.get("increment") == "V27" and
            record.get("objective") == "Schedule backups and integrity checks" and
            record.get("required_proof") == "Backup success telemetry" and
            record.get("state") ==
            "SYNTHETIC_BACKUP_PROTOTYPE_OWNER_REVIEW_PENDING" and
            record.get("branch_base") ==
            "feature/reliability-intelligence-v22" and
            record.get("baseline") == "V26 merged",
            "v27_contract_or_objective_drift")
    d = record.get("design")
    require(type(d) is dict and
            d.get("engine") == "SQLite" and
            d.get("backup_primitive") == "sqlite3.Connection.backup" and
            d.get("source") ==
            "V23/V24.1 version-2 schema + V24 134-row synthetic commit" and
            d.get("allowed_storage") ==
            "two automatically deleted temp directories with mavenu-v24- prefix and v24_synthetic.sqlite3 filename" and
            d.get("schedule") == "15 2 * * *" and
            d.get("timezone") == "UTC" and
            d.get("anchor_date") == "2026-11-08" and
            d.get("cadence") == "DAILY" and
            d.get("grace_minutes") == 30 and
            d.get("mode") == "SIMULATED_TIME_NO_BACKGROUND_JOB" and
            d.get("due_states") == list(STATES) and
            d.get("real_scheduler_configured") is False and
            d.get("host_schedule_activated") is False and
            d.get("source_database_tables") == 13 and
            d.get("expected_source_rows") == 134 and
            d.get("expected_source_events") == 12 and
            d.get("backup_retained_after_test") is False and
            d.get("backup_uploaded_to_github") is False and
            d.get("encryption_at_rest_proven") is False and
            d.get("production_backup_or_restore_proven") is False and
            d.get("inject_errors") == list(INJECTIONS) and
            d.get("error_telemetry") ==
            "stable non-sensitive error code; status FAILED, never SUCCESS" and
            d.get("no_customer_data") is True and
            d.get("no_external_network") is True and
            d.get("no_cmms_ot_writes") is True and
            d.get("no_production_backup_schedule") is True,
            "v27_schedule_or_storage_controls_drift")
    require(d.get("integrity_checks") == [
        "SQLite PRAGMA integrity_check",
        "SQLite PRAGMA foreign_key_check",
        "V24 source/backup event chain",
        "V24 commit receipt SHA-256",
        "source/backup receipt equality",
        "reopened backup verification",
        "physical file SHA-256 after closed handle",
    ], "v27_integrity_check_inventory_drift")
    require(d.get("operational_events") == [
        "SCHEDULE_DUE", "BACKUP_SUCCEEDED",
        "BACKUP_FAILED", "SCHEDULE_MISSED",
    ], "v27_event_state_inventory_drift")
    require(record.get("expected") == {
        "case_rows":12,"entity_rows":120,"events":12,
        "batches":1,"receipts":1,"total_rows":134,
        "good_copy_scenarios":2,"negative_copy_scenarios":3,
        "schedule_state_scenarios":6,
        "schedule_cron_expression":"15 2 * * *",
        "successful_telemetry_count":2,"failed_telemetry_count":3,
        "source_frozen_files":18,"source_hashes_unchanged":True,
        "restored_customer_data":0,"raw_customer_records":0,
    }, "v27_expected_evidence_changed")
    g = record.get("governance")
    require(type(g) is dict, "v27_governance_missing")
    false_keys = (
        "v10_formal_phase_approval", "v20_data_quality_signoff",
        "v21_entity_schema_review", "v22_identity_review",
        "v23_migration_review", "v24_storage_review",
        "v24_1_integration_review", "v25_index_review",
        "v26_isolation_design_review", "v27_backup_recovery_review",
        "production_access", "customer_data_license",
        "approved_backup_retention", "approved_schedule",
        "offsite_copy_enabled", "production_restore_drill_passed",
    )
    require(all(g.get(x) is False for x in false_keys),
            "v27_false_production_approval")
    require(all(g.get(x) is None for x in (
        "named_data_owner", "named_security_owner", "named_backup_operator",
        "review_date_utc", "signature",
    )), "v27_fabricated_signature")
    require(type(record.get("limitations")) is list and
            len(record["limitations"]) >= 5 and
            type(record.get("operator_gates")) is list and
            len(record["operator_gates"]) >= 5,
            "v27_operator_gates_missing")


def timestamp(text: str) -> datetime:
    if (type(text) is not str or
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}Z", text,
            flags=re.ASCII
        ) is None):
        raise BackupRejected("invalid_utc_timestamp")
    try:
        value = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC)
    except ValueError:
        raise BackupRejected("invalid_utc_timestamp") from None
    return value


def iso(value: datetime) -> str:
    require(type(value) is datetime and value.tzinfo is UTC,
            "non_utc_schedule_instant")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule_state(now_utc: datetime,
                   last_success_utc: datetime | None
                   ) -> dict[str, Any]:
    """Evaluate proposed due/late conditions; does NOT schedule a real job."""
    require(type(now_utc) is datetime and now_utc.tzinfo is UTC,
            "schedule_instant_must_be_utc")
    require(last_success_utc is None or
            (type(last_success_utc) is datetime and
             last_success_utc.tzinfo is UTC and
             last_success_utc <= now_utc),
            "invalid_previous_backup_success")
    if now_utc < ANCHOR:
        require(last_success_utc is None or last_success_utc < ANCHOR,
                "success_claimed_before_schedule_start")
        return {
            "state":"NOT_STARTED",
            "latest_due_at_utc":None,
            "next_due_at_utc":iso(ANCHOR),
            "last_success_at_utc":
                iso(last_success_utc) if last_success_utc else None,
            "unattended_schedule_activated":False,
        }
    days = (now_utc.date() - ANCHOR.date()).days
    latest = ANCHOR + timedelta(days=days)
    if now_utc < latest:
        latest -= timedelta(days=1)
    nxt = latest + timedelta(days=1)
    if last_success_utc is not None and last_success_utc >= latest:
        state = "CURRENT"
    elif now_utc <= latest + GRACE:
        state = "DUE"
    else:
        state = "MISSED"
    return {
        "state":state,
        "latest_due_at_utc":iso(latest),
        "next_due_at_utc":iso(nxt),
        "last_success_at_utc":
            iso(last_success_utc) if last_success_utc else None,
        "unattended_schedule_activated":False,
    }


def verify_backup_copy(
    source: sqlite3.Connection, copy: sqlite3.Connection,
    expected_manifest: str
) -> dict[str, Any]:
    """Verify copied V24 receipt/records/chain and equality to source."""
    require(source is not copy, "backup_is_source_connection")
    src_state = migrate_v23.validate_version(source, 2)
    dst_state = migrate_v23.validate_version(copy, 2)
    require(src_state["schema_sha256"] == dst_state["schema_sha256"],
            "backup_schema_fingerprint_differs")
    orig = persist_v24.verify_integrity(
        source, expected_manifest=expected_manifest)
    restored = persist_v24.verify_integrity(
        copy, expected_manifest=expected_manifest)
    for key in (
        "records", "events", "total_rows", "source_manifest_sha256",
        "records_sha256", "event_chain_tip_sha256", "receipt_sha256",
        "duration_seconds", "repair_cost_cents",
    ):
        require(orig[key] == restored[key],
                "backup_source_integrity_mismatch")
    require(orig["total_rows"] == 134 and orig["events"] == 12 and
            restored["foreign_key_violations"] == 0 and
            restored["sqlite_integrity"] == "ok",
            "backup_row_or_fk_check_failed")
    return {
        "source_receipt_sha256":orig["receipt_sha256"],
        "backup_receipt_sha256":restored["receipt_sha256"],
        "records_sha256":restored["records_sha256"],
        "event_chain_sha256":restored["event_chain_tip_sha256"],
        "source_manifest_sha256":orig["source_manifest_sha256"],
        "source_rows":orig["total_rows"],
        "backup_rows":restored["total_rows"],
        "backup_events":restored["events"],
        "sqlite_integrity":"ok",
        "foreign_key_violations":0,
        "receipt_matches_source":True,
        "schema_version":2,
        "customer_data":False,
        "production_restore_certified":False,
    }


def _copy_files(scenario: str, at: datetime,
                previous_success: datetime) -> dict[str, Any]:
    """One simulated due-slot backup attempt, always delete test copies."""
    require(scenario in ("normal",)+INJECTIONS, "unknown_backup_scenario")
    when = schedule_state(at, previous_success)
    require(when["state"] == "DUE", "backup_attempt_outside_due_slot")

    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as srcdir:
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dstdir:
            srcpath = Path(srcdir) / persist_v24.NAME
            dstpath = Path(dstdir) / persist_v24.NAME
            src = persist_v24.connect(srcpath)
            dst = None
            started = time.perf_counter_ns()
            telemetry = {
                "increment":"V27",
                "run_kind":"SIMULATED_DUE_SLOT",
                "test_case":scenario,
                "schedule":"15 2 * * *",
                "scheduled_due_at_utc":when["latest_due_at_utc"],
                "attempted_at_utc":iso(at),
                "status":"FAILED",
                "success":False,
                "error_code":"backup_not_completed",
                "integrity_verified":False,
                "source_rows":134,
                "copy_rows_verified":0,
                "copy_bytes":0,
                "copy_file_sha256":None,
                "source_receipt_sha256":None,
                "backup_receipt_sha256":None,
                "customer_data_used":False,
                "retained_backup_after_test":False,
                "production_backup_job_enabled":False,
                "real_backup_recovery_verified":False,
            }
            try:
                persist_v24.bootstrap(src)
                created = persist_v24.commit_snapshot(src)
                require(created["write_result"] == "COMMITTED",
                        "source_synthetic_commit_failed")
                expected_manifest = created["integrity"][
                    "source_manifest_sha256"]
                if scenario == "source_digest_invalid":
                    src.execute(
                        "UPDATE maintenance_case SET repair_cost_cents = "
                        "repair_cost_cents + 1 WHERE case_id='SYN-CASE-001'"
                    )
                # Validate source BEFORE declaring a copy possible.
                persist_v24.verify_integrity(
                    src, expected_manifest=expected_manifest)
                if scenario == "before_copy":
                    raise BackupRejected("injected_failure_before_copy")
                dst = persist_v24.connect(dstpath)
                require(dstpath.exists(), "backup_file_not_created")
                src.backup(dst, pages=8, sleep=0.0)
                if scenario == "tamper_after_copy":
                    dst.execute(
                        "UPDATE maintenance_case SET repair_cost_cents = "
                        "repair_cost_cents + 1 WHERE case_id='SYN-CASE-001'"
                    )
                result = verify_backup_copy(src, dst, expected_manifest)
                dst.close()
                dst = None
                # Use a fresh, separate SQLite connection, not only the
                # connection that received the copied pages.
                again = persist_v24.inspect_reopen(
                    dstpath, expected_manifest)
                require(again["receipt_sha256"] ==
                        result["backup_receipt_sha256"] and
                        again["total_rows"] == 134,
                        "backup_reopen_verification_failed")
                size = dstpath.stat().st_size
                require(size > 0, "backup_file_empty")
                physical_hash = hashlib.sha256(dstpath.read_bytes()).hexdigest()
                telemetry.update({
                    "status":"SUCCESS",
                    "success":True,
                    "error_code":None,
                    "integrity_verified":True,
                    "source_rows":result["source_rows"],
                    "copy_rows_verified":result["backup_rows"],
                    "copy_bytes":size,
                    "copy_file_sha256":physical_hash,
                    "source_receipt_sha256":result["source_receipt_sha256"],
                    "backup_receipt_sha256":result["backup_receipt_sha256"],
                    "copy_schema_version":2,
                    "foreign_key_violations":0,
                    "reopened_copy_verified":True,
                    "copy_receipt_matches_source":True,
                })
            except (BackupRejected,
                    persist_v24.PersistenceRejected,
                    migrate_v23.MigrationRejected,
                    sqlite3.Error) as exc:
                # Fixed, non-sensitive error code; never misreport partial
                # SQLite copy, before-copy error or corrupted source as success.
                if scenario == "normal":
                    raise
                if scenario == "before_copy":
                    require(isinstance(exc, BackupRejected) and
                            str(exc) == "injected_failure_before_copy",
                            "unexpected_injected_failure")
                    telemetry["error_code"] = "injected_before_copy"
                elif scenario == "source_digest_invalid":
                    require(isinstance(exc,persist_v24.PersistenceRejected),
                            "source_corruption_not_detected")
                    telemetry["error_code"] = "source_integrity_failed"
                else:
                    require(isinstance(exc,persist_v24.PersistenceRejected) or
                            isinstance(exc,BackupRejected),
                            "backup_tamper_not_detected")
                    telemetry["error_code"] = "copied_integrity_failed"
                require(not telemetry["success"] and
                        telemetry["copy_rows_verified"] == 0,
                        "failed_backup_reported_success")
            finally:
                if dst is not None:
                    dst.close()
                src.close()
                telemetry["duration_ms"] = round(
                    (time.perf_counter_ns() - started) / 1_000_000, 4)
                telemetry["source_file_was_created"] = srcpath.exists()
                telemetry["copy_file_was_created"] = dstpath.exists()
        require(not dstpath.exists(),
                "backup_test_copy_survived_context")
    require(not srcpath.exists(),
            "backup_test_source_survived_context")
    telemetry["source_file_deleted"] = True
    telemetry["copy_file_deleted"] = True
    return telemetry


def backup_run(now: str, previous_success: str,
               scenario: str = "normal") -> dict[str, Any]:
    at = timestamp(now)
    previous = timestamp(previous_success)
    return _copy_files(scenario, at, previous)


def run_evidence() -> dict[str, Any]:
    cfg = policy()
    validate_policy(cfg)
    good = [backup_run(now, previous)
            for now,previous in GOOD_RUNS]
    failed = [backup_run(now, previous,scenario)
              for now,previous,scenario in NEGATIVE_RUNS]
    schedule_examples = (
        ("2026-11-07T02:15:00Z", None, "NOT_STARTED"),
        ("2026-11-09T02:10:00Z",
         "2026-11-08T02:20:00Z","CURRENT"),
        ("2026-11-09T02:20:00Z",
         "2026-11-08T02:20:00Z","DUE"),
        ("2026-11-09T03:00:00Z",
         "2026-11-08T02:20:00Z","MISSED"),
        ("2026-11-09T03:00:00Z",
         "2026-11-09T02:20:00Z","CURRENT"),
        ("2026-11-10T03:00:00Z",
         "2026-11-09T02:20:00Z","MISSED"),
    )
    statuses = [
        schedule_state(
            timestamp(now),
            timestamp(prev) if prev is not None else None
        ) for now,prev,_ in schedule_examples
    ]
    require([x["state"] for x in statuses] ==
            [state for _,_,state in schedule_examples],
            "v27_schedule_state_matrix_drift")
    require(len(good) == 2 and len(failed) == 3 and
            all(x["status"]=="SUCCESS" and x["success"] and
                x["integrity_verified"] and
                x["source_receipt_sha256"]==
                x["backup_receipt_sha256"] and
                x["copy_rows_verified"]==134 and
                x["source_file_deleted"] and x["copy_file_deleted"]
                for x in good) and
            all(x["status"]=="FAILED" and not x["success"] and
                not x["integrity_verified"] and
                x["copy_rows_verified"]==0 and
                x["copy_file_deleted"] for x in failed) and
            {x["error_code"] for x in failed} ==
            {"injected_before_copy","copied_integrity_failed",
             "source_integrity_failed"},
            "v27_backup_success_or_failure_telemetry_invalid")
    require(good[0]["source_receipt_sha256"] ==
            good[1]["source_receipt_sha256"],
            "synthetic_backup_receipt_not_reproducible")
    return {
        "increment":"V27",
        "objective":"Schedule backups and integrity checks",
        "required_proof":"Backup success telemetry",
        "technical_evidence":"PASS",
        "simulation_successful_backups":len(good),
        "simulation_failed_backups":len(failed),
        "schedule_cases_checked":len(statuses),
        "schema_version":2,
        "last_test_source_rows":134,
        "backups":[*good,*failed],
        "schedule_matrix":statuses,
        "true_background_schedule_active":False,
        "retained_recoverable_copy":False,
        "external_restore_verified":False,
        "customer_data_used":False,
        "formal_backup_review_signed":False,
    }
