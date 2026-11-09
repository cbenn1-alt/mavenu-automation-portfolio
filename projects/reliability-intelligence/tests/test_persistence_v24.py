"""V24 temporary-file SQLite atomic persistence and event replay tests.

V23 up/down migration evidence is absent. These tests bootstrap a NEW temp
database, never production data, and delete it after the run. CI green is not
a human-reviewed storage release.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import entity_v21
import persist_v24 as storage


class V24TransactionalPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="mavenu-v24-")
        cls.path = Path(cls.temp.name) / storage.NAME
        cls.db = storage.connect(cls.path)
        storage.bootstrap(cls.db)
        cls.first = storage.commit_snapshot(cls.db)
        cls.actual = storage.verify_integrity(cls.db)
        cls.policy = storage.policy()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.temp.cleanup()

    def sql_rejected(self, query, values):
        self.db.execute("SAVEPOINT v24_negative")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(query, values)
        finally:
            self.db.execute("ROLLBACK TO v24_negative")
            self.db.execute("RELEASE v24_negative")

    def test_01_exact_architecture_objective(self):
        self.assertEqual(self.policy["objective"],
                         "Persist validated records and events")
        self.assertEqual(self.policy["required_proof"],
                         "Transactional integrity tests")

    def test_02_candidate_status_without_human_signoff(self):
        storage.validate_policy(self.policy)
        self.assertEqual(self.policy["status"],
                         "SYNTHETIC_FILE_BACKED_TEST_CANDIDATE_HUMAN_REVIEW_PENDING")

    def test_03_v23_migration_missing_not_hidden(self):
        self.assertFalse(self.policy["prerequisites"]["v23_migration_implemented"])
        self.assertFalse(self.policy["prerequisites"]["v23_up_down_evidence_present"])
        self.assertIn("not a migration", self.policy["design"]["schema_creation"])

    def test_04_v10_and_v20_gates_remain_blocked(self):
        self.assertFalse(self.policy["prerequisites"]["v10_formal_promotion"])
        self.assertFalse(self.policy["prerequisites"]["v20_data_quality_signoff"])

    def test_05_v21_and_v22_human_review_absent(self):
        self.assertFalse(self.policy["prerequisites"]["v21_entity_review"])
        self.assertFalse(self.policy["prerequisites"]["v22_identity_review"])

    def test_06_production_storage_not_authorized(self):
        self.assertFalse(self.policy["approvals"]["production_database_authorized"])
        self.assertFalse(self.policy["approvals"]["customer_data_authorized"])

    def test_07_all_human_reviewer_fields_null(self):
        for name in ("named_data_architect", "named_security_reviewer",
                     "named_product_owner", "decision_date_utc", "signature"):
            self.assertIsNone(self.policy["approvals"][name])

    def test_08_test_db_is_really_file_backed_and_disposable(self):
        self.assertTrue(self.path.exists())
        location = self.db.execute("PRAGMA database_list").fetchall()[0][2]
        self.assertEqual(Path(location).resolve(), self.path.resolve())
        self.assertTrue(self.path.parent.name.startswith("mavenu-v24-"))

    def test_09_sqlite_full_sync_and_delete_journal(self):
        self.assertEqual(self.db.execute("PRAGMA journal_mode").fetchone()[0],
                         "delete")
        self.assertEqual(self.db.execute("PRAGMA synchronous").fetchone()[0], 2)

    def test_10_foreign_keys_are_on(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_11_first_transaction_committed(self):
        self.assertEqual(self.first["write_result"], "COMMITTED")
        self.assertEqual(self.first["added_rows"], 134)

    def test_12_ten_original_entity_tables_remain(self):
        self.assertEqual(len(entity_v21.EXPECTED_COUNTS), 10)
        self.assertEqual(sum(storage.counts(self.db)[x]
                             for x in entity_v21.EXPECTED_COUNTS), 120)

    def test_13_twelve_persistent_case_events(self):
        self.assertEqual(self.actual["events"], 12)
        self.assertEqual(self.actual["batches"], 1)
        self.assertEqual(self.actual["receipts"], 1)

    def test_14_total_temporary_storage_rows(self):
        self.assertEqual(self.actual["total_rows"], 134)

    def test_15_exact_synthetic_duration_seconds(self):
        self.assertEqual(self.actual["duration_seconds"], 163800)

    def test_16_exact_example_cost_cents(self):
        self.assertEqual(self.actual["repair_cost_cents"], 1273500)

    def test_17_all_foreign_keys_and_identity_scopes_valid(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.actual["identity_uniqueness_violations"], 0)
        self.assertEqual(self.actual["foreign_key_violations"], 0)

    def test_18_sqlite_integrity_is_ok(self):
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_19_reopening_file_verifies_receipt(self):
        reopened = storage.inspect_reopen(
            self.path, self.actual["source_manifest_sha256"])
        self.assertEqual(reopened["receipt_sha256"],
                         self.actual["receipt_sha256"])
        self.assertEqual(reopened["total_rows"], 134)

    def test_20_second_commit_is_idempotent(self):
        retry = storage.commit_snapshot(self.db)
        self.assertEqual(retry["write_result"], "ALREADY_COMMITTED")
        self.assertEqual(retry["added_rows"], 0)
        self.assertEqual(retry["integrity"]["receipt_sha256"],
                         self.actual["receipt_sha256"])

    def test_21_reopen_then_retry_is_idempotent(self):
        other = storage.connect(self.path)
        try:
            retry = storage.commit_snapshot(other)
            self.assertEqual(retry["write_result"], "ALREADY_COMMITTED")
            self.assertEqual(retry["added_rows"], 0)
        finally:
            other.close()

    def test_22_no_duplicate_events_or_case_ids(self):
        ids = self.db.execute(
            "SELECT COUNT(DISTINCT case_id) FROM v24_case_event"
        ).fetchone()[0]
        self.assertEqual(ids, 12)

    def test_23_event_chain_tip_nonzero_and_sha256(self):
        self.assertEqual(len(self.actual["event_chain_tip_sha256"]), 64)
        self.assertNotEqual(self.actual["event_chain_tip_sha256"], storage.ZERO)

    def test_24_event_chain_starts_with_zero_digest(self):
        start = self.db.execute(
            "SELECT previous_sha256 FROM v24_case_event WHERE sequence_no=1"
        ).fetchone()[0]
        self.assertEqual(start, storage.ZERO)

    def test_25_original_references_are_synthetic(self):
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM source_document WHERE origin_kind="
            "'committed_synthetic_fixture_reconstruction'"
        ).fetchone()[0], 3)

    def test_26_event_receipt_is_not_real_customer_data(self):
        self.assertFalse(self.actual["customer_data_used"])
        self.assertFalse(self.actual["actual_production_durability_verified"])

    def test_27_archive_is_not_production_storage(self):
        self.assertEqual(self.policy["design"]["mode"],
                         "temporary_file_in_automatic_test_cleanup")
        self.assertTrue(self.policy["design"]["delete_on_complete"])

    def test_28_receipt_has_reproducible_record_digest(self):
        self.assertEqual(self.actual["records_sha256"],
                         storage.records_sha(self.db))

    def test_29_all_six_immutability_triggers_exist(self):
        self.assertEqual(storage.check_structure(self.db)
                         ["append_only_triggers"], 6)

    def test_30_event_update_is_blocked(self):
        self.sql_rejected(
            "UPDATE v24_case_event SET payload_sha256=? WHERE sequence_no=1",
            ("0"*64,))

    def test_31_event_delete_is_blocked(self):
        self.sql_rejected(
            "DELETE FROM v24_case_event WHERE sequence_no=?", (1,))

    def test_32_receipt_update_is_blocked(self):
        self.sql_rejected(
            "UPDATE v24_commit_receipt SET records_sha256=?", ("1"*64,))

    def test_33_receipt_delete_is_blocked(self):
        self.sql_rejected("DELETE FROM v24_commit_receipt WHERE batch_id=?",
                          (storage.BATCH,))

    def test_34_batch_update_is_blocked(self):
        self.sql_rejected(
            "UPDATE v24_import_batch SET source_manifest_sha256=?", ("1"*64,))

    def test_35_batch_delete_is_blocked(self):
        self.sql_rejected("DELETE FROM v24_import_batch WHERE batch_id=?",
                          (storage.BATCH,))

    def test_36_duplicate_event_id_rejected(self):
        row = self.db.execute(
            "SELECT * FROM v24_case_event WHERE sequence_no=1"
        ).fetchone()
        self.sql_rejected(
            "INSERT INTO v24_case_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            row)

    def test_37_event_unknown_case_parent_rejected(self):
        self.sql_rejected(
            "INSERT INTO v24_case_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (storage.TENANT, storage.SITE, "SYN-V24-EVENT-900",
             storage.BATCH, 13, "SYN-CASE-999", "SYN-ASSET-001",
             "synthetic_case_persisted", "a"*64, "b"*64, "c"*64))

    def test_38_invalid_manifest_override_detected(self):
        with self.assertRaisesRegex(storage.PersistenceRejected,
                                    "batch_source_digest_conflict"):
            storage.commit_snapshot(self.db, manifest_override="f"*64)

    def test_39_bad_manifest_type_rejected(self):
        with self.assertRaisesRegex(storage.PersistenceRejected,
                                    "invalid_manifest_override"):
            storage.commit_snapshot(self.db, manifest_override="not-a-sha")

    def test_40_invalid_failure_injection_rejected(self):
        with self.assertRaisesRegex(storage.PersistenceRejected,
                                    "unsupported_failure_injection"):
            storage.commit_snapshot(self.db, inject_failure="power_loss_proven")

    def test_41_source_row_tamper_is_detected(self):
        self.db.execute("SAVEPOINT change_cost")
        try:
            self.db.execute("UPDATE maintenance_case SET repair_cost_cents="
                            "repair_cost_cents+1 WHERE case_id='SYN-CASE-001'")
            with self.assertRaisesRegex(storage.PersistenceRejected,
                                        "persistent_snapshot_digest_mismatch"):
                storage.verify_integrity(self.db)
        finally:
            self.db.execute("ROLLBACK TO change_cost")
            self.db.execute("RELEASE change_cost")

    def test_42_tamper_then_reopen_baseline_unmodified(self):
        self.assertEqual(storage.verify_integrity(self.db)
                         ["receipt_sha256"], self.actual["receipt_sha256"])

    def test_43_policy_prevents_fabricated_migration_approval(self):
        changed = copy.deepcopy(self.policy)
        changed["prerequisites"]["v23_migration_implemented"] = True
        with self.assertRaises(storage.PersistenceRejected):
            storage.validate_policy(changed)

    def test_44_policy_prevents_fabricated_v24_signature(self):
        changed = copy.deepcopy(self.policy)
        changed["approvals"]["signature"] = "made-up"
        with self.assertRaises(storage.PersistenceRejected):
            storage.validate_policy(changed)

    def test_45_policy_prevents_real_customer_access(self):
        changed = copy.deepcopy(self.policy)
        changed["approvals"]["customer_data_authorized"] = True
        with self.assertRaises(storage.PersistenceRejected):
            storage.validate_policy(changed)

    def test_46_policy_prevents_durable_production_claim(self):
        changed = copy.deepcopy(self.policy)
        changed["design"]["mode"] = "customer_production"
        with self.assertRaises(storage.PersistenceRejected):
            storage.validate_policy(changed)

    def test_47_policy_cannot_reduce_expected_rows(self):
        changed = copy.deepcopy(self.policy)
        changed["expected"]["total_rows"] = 133
        with self.assertRaises(storage.PersistenceRejected):
            storage.validate_policy(changed)

    def test_48_temp_database_filename_is_restricted(self):
        with self.assertRaises(storage.PersistenceRejected):
            storage.connect(self.path.with_name("production.sqlite3"))

    def test_49_source_provenance_unmodified(self):
        self.assertEqual(self.actual["records"], 120)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM source_document"
        ).fetchone()[0], 3)

    def test_50_checksum_chain_matches_case_events(self):
        self.assertEqual(storage.verify_integrity(self.db)
                         ["event_chain_tip_sha256"],
                         self.actual["event_chain_tip_sha256"])

    def test_51_transaction_rolls_back_after_records(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            path = Path(dirname) / storage.NAME
            db = storage.connect(path)
            try:
                storage.bootstrap(db)
                with self.assertRaisesRegex(storage.PersistenceRejected,
                                            "injected_failure_after_records"):
                    storage.commit_snapshot(db,inject_failure="after_records")
                self.assertTrue(all(v == 0 for v in storage.counts(db).values()))
            finally:
                db.close()
            db = storage.connect(path)
            try:
                self.assertTrue(all(v == 0 for v in storage.counts(db).values()))
                result = storage.commit_snapshot(db)
                self.assertEqual(result["added_rows"], 134)
                self.assertEqual(storage.verify_integrity(db)["events"], 12)
            finally:
                db.close()

    def test_52_transaction_rolls_back_after_four_events(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            path = Path(dirname) / storage.NAME
            db = storage.connect(path)
            try:
                storage.bootstrap(db)
                with self.assertRaisesRegex(storage.PersistenceRejected,
                                            "injected_failure_after_event_4"):
                    storage.commit_snapshot(db,inject_failure="after_event_4")
                self.assertTrue(all(v == 0 for v in storage.counts(db).values()))
            finally:
                db.close()
            db = storage.connect(path)
            try:
                self.assertTrue(all(v == 0 for v in storage.counts(db).values()))
                self.assertEqual(storage.commit_snapshot(db)
                                 ["write_result"], "COMMITTED")
            finally:
                db.close()

    def test_53_success_scenario_includes_reopen_and_idempotency(self):
        result = storage.run_scenario()
        self.assertEqual(result["first_write"], "COMMITTED")
        self.assertEqual(result["second_write"], "ALREADY_COMMITTED")
        self.assertEqual(result["duplicate_rows_added"], 0)

    def test_54_failure_after_records_replays_successfully(self):
        result = storage.run_scenario(inject_failure="after_records")
        self.assertEqual(result["second_write"], "ALREADY_COMMITTED")
        self.assertEqual(result["reopen_integrity"]["total_rows"], 134)

    def test_55_failure_after_events_replays_successfully(self):
        result = storage.run_scenario(inject_failure="after_event_4")
        self.assertEqual(result["second_write"], "ALREADY_COMMITTED")
        self.assertEqual(result["reopen_integrity"]["events"], 12)

    def test_56_temporary_directory_cleanup_removes_file(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            path = Path(dirname) / storage.NAME
            db = storage.connect(path)
            try:
                storage.bootstrap(db)
                storage.commit_snapshot(db)
                self.assertTrue(path.exists())
            finally:
                db.close()
        self.assertFalse(path.exists())

    def test_57_bootstrap_cannot_rerun_over_existing_db(self):
        with self.assertRaisesRegex(storage.PersistenceRejected,
                                    "existing_schema_bootstrap_denied"):
            storage.bootstrap(self.db)

    def test_58_state_after_failures_remains_consistent(self):
        self.assertEqual(self.actual["receipt_sha256"],
                         storage.verify_integrity(self.db)["receipt_sha256"])

    def test_59_legacy_schema_and_readonly_runtime_not_modified(self):
        self.assertFalse(self.policy["design"]["ot_or_cmms_writes"])
        self.assertFalse(self.policy["design"]["external_network"])

    def test_60_file_path_outside_temp_rejected(self):
        with self.assertRaises(storage.PersistenceRejected):
            storage.connect(Path("/tmp/not-mavenu-v24/v24_synthetic.sqlite3"))

    def test_table_tenant_row_count(self):
        self.assertEqual(storage.counts(self.db)["tenant"], storage.EXPECTED["tenant"])

    def test_table_site_row_count(self):
        self.assertEqual(storage.counts(self.db)["site"], storage.EXPECTED["site"])

    def test_table_asset_row_count(self):
        self.assertEqual(storage.counts(self.db)["asset"], storage.EXPECTED["asset"])

    def test_table_maintenance_case_row_count(self):
        self.assertEqual(storage.counts(self.db)["maintenance_case"], storage.EXPECTED["maintenance_case"])

    def test_table_evidence_reference_row_count(self):
        self.assertEqual(storage.counts(self.db)["evidence_reference"], storage.EXPECTED["evidence_reference"])

    def test_table_scripted_review_row_count(self):
        self.assertEqual(storage.counts(self.db)["scripted_review"], storage.EXPECTED["scripted_review"])

    def test_table_reference_label_row_count(self):
        self.assertEqual(storage.counts(self.db)["reference_label"], storage.EXPECTED["reference_label"])

    def test_table_source_document_row_count(self):
        self.assertEqual(storage.counts(self.db)["source_document"], storage.EXPECTED["source_document"])

    def test_table_record_origin_row_count(self):
        self.assertEqual(storage.counts(self.db)["record_origin"], storage.EXPECTED["record_origin"])

    def test_table_transform_step_row_count(self):
        self.assertEqual(storage.counts(self.db)["transform_step"], storage.EXPECTED["transform_step"])

    def test_event_01_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (1,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-001")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_02_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (2,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-002")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_03_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (3,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-003")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_04_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (4,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-004")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_05_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (5,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-005")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_06_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (6,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-006")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_07_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (7,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-007")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_08_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (8,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-008")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_09_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (9,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-009")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_10_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (10,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-010")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_11_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (11,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-011")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

    def test_event_12_payload_chain(self):
        row = self.db.execute("SELECT case_id,asset_id,payload_sha256,chain_sha256 FROM v24_case_event WHERE sequence_no=?", (12,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "SYN-CASE-012")
        self.assertEqual(len(row[2]), 64)
        self.assertEqual(len(row[3]), 64)

if __name__ == "__main__":
    unittest.main()
