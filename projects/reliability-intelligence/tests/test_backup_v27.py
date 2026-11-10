"""V27 backup schedule and integrity telemetry, synthetic-only regression.

No real recurring task, customer backup, retained file, encryption guarantee,
actual power-loss scenario or disaster recovery certification.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backup_v27 as backup
import migrate_v23
import persist_v24
import verify_v27


class V27BackupTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = backup.policy()
        cls.report = backup.run_evidence()
        cls.good = [x for x in cls.report["backups"]
                    if x["status"] == "SUCCESS"]
        cls.bad = [x for x in cls.report["backups"]
                   if x["status"] == "FAILED"]

    def reject_contract(self, key, value):
        policy = copy.deepcopy(self.cfg)
        pointer = policy
        parts = key.split(".")
        for part in parts[:-1]:
            pointer = pointer[part]
        pointer[parts[-1]] = value
        with self.assertRaises(backup.BackupRejected):
            backup.validate_policy(policy)

    def test_01_exact_architecture_objective(self):
        self.assertEqual(self.cfg["objective"],
                         "Schedule backups and integrity checks")
        self.assertEqual(self.cfg["required_proof"],
                         "Backup success telemetry")

    def test_02_contract_is_synthetic_and_unsigned(self):
        backup.validate_policy(self.cfg)
        self.assertEqual(self.cfg["state"],
                         "SYNTHETIC_BACKUP_PROTOTYPE_OWNER_REVIEW_PENDING")

    def test_03_policy_timezone_utc(self):
        self.assertEqual(self.cfg["design"]["timezone"], "UTC")

    def test_04_policy_exact_daily_cron(self):
        self.assertEqual(self.cfg["design"]["schedule"], "15 2 * * *")

    def test_05_policy_30_minute_grace(self):
        self.assertEqual(self.cfg["design"]["grace_minutes"], 30)

    def test_06_no_scheduled_job_activated(self):
        self.assertFalse(self.cfg["design"]["real_scheduler_configured"])
        self.assertFalse(self.cfg["design"]["host_schedule_activated"])
        self.assertFalse(self.report["true_background_schedule_active"])

    def test_07_no_retained_recoverable_backup(self):
        self.assertFalse(self.report["retained_recoverable_copy"])
        self.assertFalse(self.cfg["design"]["backup_retained_after_test"])

    def test_08_no_external_copy_or_cloud_upload(self):
        self.assertFalse(self.cfg["design"]["backup_uploaded_to_github"])
        self.assertTrue(self.cfg["design"]["no_external_network"])

    def test_09_no_production_backup_retention(self):
        self.assertFalse(self.cfg["governance"]["approved_backup_retention"])
        self.assertFalse(self.cfg["governance"]["approved_schedule"])

    def test_10_no_production_restore_certification(self):
        self.assertFalse(self.cfg["design"]["production_backup_or_restore_proven"])
        self.assertFalse(self.report["external_restore_verified"])

    def test_11_no_customer_data_used(self):
        self.assertFalse(self.report["customer_data_used"])
        self.assertTrue(self.cfg["design"]["no_customer_data"])

    def test_12_no_scada_or_cmms_writes(self):
        self.assertTrue(self.cfg["design"]["no_cmms_ot_writes"])

    def test_13_two_successful_synthetic_copies(self):
        self.assertEqual(self.report["simulation_successful_backups"], 2)
        self.assertEqual(len(self.good), 2)

    def test_14_three_detected_failure_scenarios(self):
        self.assertEqual(self.report["simulation_failed_backups"], 3)
        self.assertEqual(len(self.bad), 3)

    def test_15_six_schedule_states_verified(self):
        self.assertEqual(self.report["schedule_cases_checked"], 6)
        self.assertEqual(
            [x["state"] for x in self.report["schedule_matrix"]],
            ["NOT_STARTED", "CURRENT", "DUE", "MISSED",
             "CURRENT", "MISSED"]
        )

    def test_16_success_telemetry_has_no_error(self):
        for entry in self.good:
            with self.subTest(case=entry["test_case"]):
                self.assertIsNone(entry["error_code"])
                self.assertTrue(entry["success"])
                self.assertEqual(entry["status"], "SUCCESS")

    def test_17_failed_telemetry_never_reports_success(self):
        for entry in self.bad:
            with self.subTest(case=entry["test_case"]):
                self.assertFalse(entry["success"])
                self.assertEqual(entry["status"], "FAILED")
                self.assertFalse(entry["integrity_verified"])

    def test_18_failed_copies_have_zero_accepted_rows(self):
        self.assertTrue(all(x["copy_rows_verified"] == 0 for x in self.bad))

    def test_19_both_copies_have_134_verified_rows(self):
        for entry in self.good:
            self.assertEqual(entry["copy_rows_verified"], 134)
            self.assertEqual(entry["source_rows"], 134)

    def test_20_copy_receipt_sha256_matches_source(self):
        for entry in self.good:
            self.assertEqual(entry["backup_receipt_sha256"],
                             entry["source_receipt_sha256"])
            self.assertTrue(entry["copy_receipt_matches_source"])

    def test_21_synthetic_receipt_reproducible(self):
        self.assertEqual(
            self.good[0]["backup_receipt_sha256"],
            self.good[1]["backup_receipt_sha256"]
        )

    def test_22_success_copy_physically_exists_during_run(self):
        self.assertTrue(all(x["copy_file_was_created"] for x in self.good))

    def test_23_success_files_removed_after_verification(self):
        self.assertTrue(all(x["copy_file_deleted"] and
                            x["source_file_deleted"] for x in self.good))

    def test_24_failed_files_also_removed(self):
        self.assertTrue(all(x["copy_file_deleted"] and
                            x["source_file_deleted"] for x in self.bad))

    def test_25_source_digest_failure_is_diagnosed(self):
        entry = next(x for x in self.bad
                     if x["test_case"] == "source_digest_invalid")
        self.assertEqual(entry["error_code"], "source_integrity_failed")
        self.assertFalse(entry["success"])

    def test_26_tampered_backup_is_diagnosed(self):
        entry = next(x for x in self.bad
                     if x["test_case"] == "tamper_after_copy")
        self.assertEqual(entry["error_code"], "copied_integrity_failed")
        self.assertFalse(entry["success"])

    def test_27_before_copy_failure_is_diagnosed(self):
        entry = next(x for x in self.bad
                     if x["test_case"] == "before_copy")
        self.assertEqual(entry["error_code"], "injected_before_copy")
        self.assertFalse(entry["copy_file_was_created"])

    def test_28_success_copy_file_sha256_is_64_hex_chars(self):
        for entry in self.good:
            self.assertEqual(len(entry["copy_file_sha256"]), 64)
            self.assertTrue(all(ch in "0123456789abcdef"
                                for ch in entry["copy_file_sha256"]))

    def test_29_success_copy_file_has_positive_bytes(self):
        self.assertTrue(all(x["copy_bytes"] > 0 for x in self.good))

    def test_30_failure_does_not_claim_physical_hash(self):
        self.assertTrue(all(x["copy_file_sha256"] is None for x in self.bad))

    def test_31_database_user_version_two(self):
        self.assertEqual(self.report["schema_version"], 2)
        self.assertTrue(all(x["copy_schema_version"] == 2 for x in self.good))

    def test_32_success_reopens_backup_independently(self):
        self.assertTrue(all(x["reopened_copy_verified"] for x in self.good))

    def test_33_foreign_key_checks_pass(self):
        self.assertTrue(all(x["foreign_key_violations"] == 0
                            for x in self.good))

    def test_34_real_disaster_recovery_not_claimed(self):
        self.assertTrue(all(not x["real_backup_recovery_verified"]
                            for x in self.report["backups"]))

    def test_35_success_does_not_approve_production(self):
        self.assertTrue(all(not x["production_backup_job_enabled"]
                            for x in self.report["backups"]))

    def test_36_telemetry_exposes_duration_and_due_slot(self):
        self.assertTrue(all(x["duration_ms"] >= 0 and
                            x["scheduled_due_at_utc"].endswith("Z")
                            for x in self.report["backups"]))

    def test_37_copy_and_source_are_two_distinct_connections(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as tmp:
            db = persist_v24.connect(Path(tmp)/persist_v24.NAME)
            try:
                persist_v24.bootstrap(db)
                first = persist_v24.commit_snapshot(db)
                with self.assertRaisesRegex(
                        backup.BackupRejected,"backup_is_source_connection"):
                    backup.verify_backup_copy(
                        db, db,
                        first["integrity"]["source_manifest_sha256"]
                    )
            finally:
                db.close()

    def test_38_source_copy_is_not_untrusted_inmemory(self):
        self.assertEqual(self.cfg["design"]["allowed_storage"],
                         "two automatically deleted temp directories with mavenu-v24- prefix and v24_synthetic.sqlite3 filename")

    def test_39_no_approved_backup_encryption(self):
        self.assertFalse(self.cfg["design"]["encryption_at_rest_proven"])

    def test_40_no_production_access_approval(self):
        self.assertFalse(self.cfg["governance"]["production_access"])
        self.assertFalse(self.cfg["governance"]["customer_data_license"])

    def test_41_signed_owner_fields_are_null(self):
        g = self.cfg["governance"]
        for field in ("named_data_owner","named_security_owner",
                      "named_backup_operator","review_date_utc","signature"):
            self.assertIsNone(g[field])

    def test_42_all_previous_phase_reviews_remain_pending(self):
        g = self.cfg["governance"]
        for field in ("v10_formal_phase_approval",
                      "v20_data_quality_signoff",
                      "v21_entity_schema_review","v22_identity_review",
                      "v23_migration_review","v24_storage_review",
                      "v24_1_integration_review","v25_index_review",
                      "v26_isolation_design_review",
                      "v27_backup_recovery_review"):
            self.assertFalse(g[field])

    def test_43_contract_cannot_enable_cron(self):
        self.reject_contract("design.host_schedule_activated", True)

    def test_44_contract_cannot_forge_backup_approval(self):
        self.reject_contract("governance.v27_backup_recovery_review", True)

    def test_45_contract_cannot_forge_signature(self):
        self.reject_contract("governance.signature", "fake")

    def test_46_contract_cannot_claim_customer_data_rights(self):
        self.reject_contract("governance.customer_data_license", True)

    def test_47_contract_cannot_claim_offsite_copy(self):
        self.reject_contract("governance.offsite_copy_enabled", True)

    def test_48_contract_cannot_disable_integrity_check(self):
        changed = copy.deepcopy(self.cfg)
        changed["design"]["integrity_checks"].pop()
        with self.assertRaises(backup.BackupRejected):
            backup.validate_policy(changed)

    def test_49_contract_cannot_reduce_failure_probes(self):
        self.reject_contract("design.inject_errors", [])

    def test_50_contract_cannot_remove_time_zone(self):
        self.reject_contract("design.timezone", "America/Chicago")

    def test_51_schedule_before_anchor_is_not_started(self):
        status = backup.schedule_state(
            backup.timestamp("2026-11-07T02:15:00Z"), None)
        self.assertEqual(status["state"],"NOT_STARTED")
        self.assertFalse(status["unattended_schedule_activated"])

    def test_52_due_window_is_inclusive(self):
        state = backup.schedule_state(
            backup.timestamp("2026-11-09T02:45:00Z"),
            backup.timestamp("2026-11-08T02:20:00Z"))
        self.assertEqual(state["state"],"DUE")

    def test_53_missed_after_grace(self):
        state = backup.schedule_state(
            backup.timestamp("2026-11-09T02:45:01Z"),
            backup.timestamp("2026-11-08T02:20:00Z"))
        self.assertEqual(state["state"],"MISSED")

    def test_54_current_after_success(self):
        state = backup.schedule_state(
            backup.timestamp("2026-11-09T03:00:00Z"),
            backup.timestamp("2026-11-09T02:20:00Z"))
        self.assertEqual(state["state"],"CURRENT")

    def test_55_invalid_future_last_success_rejected(self):
        with self.assertRaises(backup.BackupRejected):
            backup.schedule_state(
                backup.timestamp("2026-11-09T02:20:00Z"),
                backup.timestamp("2026-11-09T02:21:00Z"))

    def test_56_non_utc_timezone_rejected(self):
        with self.assertRaises(backup.BackupRejected):
            backup.schedule_state(
                datetime(2026,11,9,2,20), None)

    def test_57_timezone_offset_not_accepted_as_z(self):
        with self.assertRaises(backup.BackupRejected):
            backup.timestamp("2026-11-09T02:20:00+00:00")

    def test_58_invalid_calendar_date_rejected(self):
        with self.assertRaises(backup.BackupRejected):
            backup.timestamp("2026-02-30T02:15:00Z")

    def test_59_unrecognized_failure_injection_rejected(self):
        with self.assertRaisesRegex(
                backup.BackupRejected,"unknown_backup_scenario"):
            backup.backup_run(
                "2026-11-09T02:20:00Z",
                "2026-11-08T02:20:00Z",
                scenario="actual_power_loss_certified"
            )

    def test_60_attempt_outside_due_slot_rejected(self):
        with self.assertRaisesRegex(
                backup.BackupRejected,"backup_attempt_outside_due_slot"):
            backup.backup_run(
                "2026-11-09T03:00:00Z",
                "2026-11-08T02:20:00Z",
            )

    def test_61_fixed_diagnostics_never_report_uncontrolled_contents(self):
        self.assertEqual(
            {x["error_code"] for x in self.bad},
            {"injected_before_copy","copied_integrity_failed",
             "source_integrity_failed"})

    def test_62_verifier_is_unsigned(self):
        x = verify_v27.generate(require_prior_reports=False)
        self.assertEqual(x["technical_evidence"],"PASS")
        self.assertEqual(x["v27_backup_review"],"PENDING")
        self.assertFalse(x["production_backup_enabled"])
        self.assertFalse(x["copy_retained_after_test"])

    def test_63_no_backup_rows_missing_from_success(self):
        self.assertTrue(all(x["copy_rows_verified"]==x["source_rows"]
                            for x in self.good))

    def test_64_governance_requires_operator_readiness(self):
        self.assertGreaterEqual(len(self.cfg["operator_gates"]),5)

    def test_65_no_archived_copy_is_left_by_verifier(self):
        self.assertTrue(all(x["copy_file_deleted"] for x in
                            self.report["backups"]))

    def test_66_daily_due_rollover_correct(self):
        a=backup.schedule_state(
            backup.timestamp("2026-11-09T23:00:00Z"),
            backup.timestamp("2026-11-09T02:20:00Z"))
        b=backup.schedule_state(
            backup.timestamp("2026-11-10T02:20:00Z"),
            backup.timestamp("2026-11-09T02:20:00Z"))
        self.assertEqual(a["state"],"CURRENT")
        self.assertEqual(b["state"],"DUE")

    def test_67_true_source_snapshot_is_not_modified_by_backup(self):
        self.assertEqual(self.good[0]["source_receipt_sha256"],
                         self.good[1]["source_receipt_sha256"])

    def test_68_exact_backup_primitive(self):
        self.assertEqual(self.cfg["design"]["backup_primitive"],
                         "sqlite3.Connection.backup")

    def test_69_no_retained_backup_telemetry(self):
        self.assertTrue(all(not x["retained_backup_after_test"]
                            for x in self.report["backups"]))

    def test_70_false_slas_are_not_claimed(self):
        self.assertFalse(self.cfg["design"]["production_backup_or_restore_proven"])
        self.assertFalse(self.cfg["governance"]["production_restore_drill_passed"])


def make_status_test(now,prev,expected):
    def run(self):
        result=backup.schedule_state(
            backup.timestamp(now),
            backup.timestamp(prev) if prev is not None else None
        )
        self.assertEqual(result["state"],expected)
        self.assertFalse(result["unattended_schedule_activated"])
    return run


def make_error_test(name):
    def run(self):
        entry=next(x for x in self.bad if x["test_case"]==name)
        self.assertEqual(entry["status"],"FAILED")
        self.assertFalse(entry["integrity_verified"])
        self.assertTrue(entry["source_file_deleted"])
        self.assertTrue(entry["copy_file_deleted"])
    return run


for n,(at,previous,status) in enumerate([
    ("2026-11-07T02:00:00Z",None,"NOT_STARTED"),
    ("2026-11-08T02:15:00Z",None,"DUE"),
    ("2026-11-08T02:45:00Z",None,"DUE"),
    ("2026-11-08T02:45:01Z",None,"MISSED"),
    ("2026-11-09T02:10:00Z","2026-11-08T02:20:00Z","CURRENT"),
    ("2026-11-09T02:15:00Z","2026-11-08T02:20:00Z","DUE"),
    ("2026-11-09T02:45:00Z","2026-11-08T02:20:00Z","DUE"),
    ("2026-11-09T02:45:01Z","2026-11-08T02:20:00Z","MISSED"),
],start=1):
    setattr(V27BackupTelemetryTests,"test_schedule_bound_%02d"%n,
            make_status_test(at,previous,status))

for case in backup.INJECTIONS:
    setattr(V27BackupTelemetryTests,"test_failure_telemetry_"+case,
            make_error_test(case))


if __name__ == "__main__":
    unittest.main()
