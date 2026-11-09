"""V24.1 tests the real V23 → V24 bootstrap integration.

Only disposable synthetic SQLite files. No customer records, production
migration authorization, power-loss certification, or human sign-off.
"""

from __future__ import annotations

import copy
import sqlite3
import sys
import tempfile
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

import entity_v21
import migrate_v23 as migration
import persist_v24 as persist
import verify_v24_1 as integrated


class V241MigrationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = integrated.policy()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mavenu-v24-")
        self.path = Path(self.temp.name) / persist.NAME
        self.db = persist.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def assert_policy_rejected(self, key, value):
        policy = copy.deepcopy(self.cfg)
        obj = policy
        names = key.split(".")
        for name in names[:-1]:
            obj = obj[name]
        obj[names[-1]] = value
        with self.assertRaises(integrated.V241Rejected):
            integrated.validate_policy(policy)

    def test_01_v241_objective_and_proof(self):
        self.assertEqual(self.cfg["increment"], "V24.1")
        self.assertIn("Integrate V23 schema migrator", self.cfg["objective"])
        self.assertIn("Combined migration + transaction",
                      self.cfg["required_proof"])

    def test_02_contract_integrity(self):
        integrated.validate_policy(self.cfg)

    def test_03_v24_legacy_contract_preserved(self):
        self.assertTrue(
            self.cfg["historical_contract_is_superseded_for_bootstrap_only"])
        self.assertEqual(
            self.cfg["historical_v24_contract"],
            "docs/data/PERSISTENCE_CONTRACT_V24.json")
        self.assertFalse(
            persist.policy()["prerequisites"]["v23_migration_implemented"])

    def test_04_source_pinned_to_v22_merged_history(self):
        self.assertEqual(self.cfg["branch_base"],
                         "feature/reliability-intelligence-v22")

    def test_05_no_production_storage_permission(self):
        self.assertFalse(
            self.cfg["boundaries"]["production_database_authorized"])
        self.assertFalse(
            self.cfg["boundaries"]["customer_data_authorized"])

    def test_06_no_actual_ownership_approval(self):
        self.assertFalse(
            self.cfg["boundaries"]["v24_1_integration_reviewed"])
        self.assertFalse(
            self.cfg["boundaries"]["v23_migration_reviewed"])
        self.assertFalse(
            self.cfg["boundaries"]["v24_storage_reviewed"])

    def test_07_frozen_phase_signoffs_remain_blocked(self):
        self.assertFalse(
            self.cfg["boundaries"]["v10_human_promotion_approved"])
        self.assertFalse(
            self.cfg["boundaries"]["v20_data_quality_signed"])

    def test_08_no_cryptographic_or_disaster_recovery_overclaim(self):
        self.assertFalse(
            self.cfg["boundaries"]["real_power_loss_verified"])
        self.assertFalse(
            self.cfg["boundaries"]["durable_migration_backup_proven"])

    def test_09_v0_empty_initial(self):
        record = migration.validate_version(self.db, 0)
        self.assertEqual(record["tables"], 0)
        self.assertEqual(record["triggers"], 0)

    def test_10_v0_bootstrap_uses_versioned_migrations(self):
        persist.bootstrap(self.db)
        state = migration.validate_version(self.db, 2)
        self.assertEqual(state["tables"], 13)
        self.assertEqual(state["triggers"], 6)

    def test_11_v0_bootstrap_ends_with_v2_marker(self):
        persist.bootstrap(self.db)
        self.assertEqual(
            self.db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_12_v24_integrity_inspection_accepts_migrated_schema(self):
        persist.bootstrap(self.db)
        self.assertEqual(persist.check_structure(self.db)["schema_tables"],13)

    def test_13_normal_synthetic_persistence_after_migration(self):
        persist.bootstrap(self.db)
        result = persist.commit_snapshot(self.db)
        self.assertEqual(result["write_result"],"COMMITTED")
        self.assertEqual(result["integrity"]["total_rows"],134)

    def test_14_v24_receipt_survives_connection_reopen(self):
        persist.bootstrap(self.db)
        record=persist.commit_snapshot(self.db)
        independent=persist.inspect_reopen(
            self.path,record["integrity"]["source_manifest_sha256"])
        self.assertEqual(independent["receipt_sha256"],
                         record["integrity"]["receipt_sha256"])

    def test_15_idempotent_replay_on_migrated_schema(self):
        persist.bootstrap(self.db)
        persist.commit_snapshot(self.db)
        replay=persist.commit_snapshot(self.db)
        self.assertEqual(replay["write_result"],"ALREADY_COMMITTED")
        self.assertEqual(replay["added_rows"],0)

    def test_16_idempotent_replay_on_new_connection(self):
        persist.bootstrap(self.db)
        persist.commit_snapshot(self.db)
        connection=persist.connect(self.path)
        try:
            replay=persist.commit_snapshot(connection)
            self.assertEqual(replay["write_result"],"ALREADY_COMMITTED")
            self.assertEqual(replay["added_rows"],0)
            self.assertEqual(migration.validate_version(connection)["version"],2)
        finally:
            connection.close()

    def test_17_v1_empty_upgrade_is_resumable(self):
        migration.migrate_to(self.db,1)
        persist.bootstrap(self.db)
        self.assertEqual(migration.validate_version(self.db,2)["tables"],13)

    def test_18_failed_v1_to_v2_upgrade_does_not_leave_partial_ddl(self):
        migration.migrate_to(self.db,1)
        before=migration.validate_version(self.db,1)
        with self.assertRaises(migration.MigrationRejected):
            migration.migrate_step(
                self.db,2,inject_failure="up_v2_after_1_ledger")
        after=migration.validate_version(self.db,1)
        self.assertEqual(after["schema_sha256"],
                         before["schema_sha256"])

    def test_19_failed_upgrade_then_resume_bootstrap(self):
        migration.migrate_to(self.db,1)
        with self.assertRaises(migration.MigrationRejected):
            migration.migrate_step(
                self.db,2,inject_failure="up_v2_after_1_ledger")
        persist.bootstrap(self.db)
        self.assertEqual(migration.validate_version(self.db,2)["tables"],13)

    def test_20_partial_upgrade_marker_survives_reopen(self):
        migration.migrate_to(self.db,1)
        with self.assertRaises(migration.MigrationRejected):
            migration.migrate_step(
                self.db,2,inject_failure="up_v2_after_1_ledger")
        connection=persist.connect(self.path)
        try:
            self.assertEqual(migration.validate_version(connection)["version"],1)
            persist.bootstrap(connection)
            self.assertEqual(migration.validate_version(connection)["version"],2)
        finally:
            connection.close()

    def test_21_nonempty_v1_bootstrap_refused(self):
        migration.migrate_to(self.db,1)
        entity_v21.load_synthetic_preview(self.db,entity_v21.load_model())
        with self.assertRaisesRegex(
                persist.PersistenceRejected,"nonempty_v1_bootstrap_denied"):
            persist.bootstrap(self.db)
        self.assertEqual(migration.validate_version(self.db)["version"],1)

    def test_22_nonempty_v1_refusal_preserves_all_rows(self):
        migration.migrate_to(self.db,1)
        entity_v21.load_synthetic_preview(self.db,entity_v21.load_model())
        before=persist.records_sha(self.db)
        with self.assertRaises(persist.PersistenceRejected):
            persist.bootstrap(self.db)
        self.assertEqual(persist.records_sha(self.db),before)
        self.assertEqual(entity_v21.preview_counts(self.db)["total_rows"],120)

    def test_23_rejects_bootstrap_of_existing_empty_v2(self):
        migration.migrate_to(self.db,2)
        with self.assertRaisesRegex(
                persist.PersistenceRejected,"existing_schema_bootstrap_denied"):
            persist.bootstrap(self.db)
        self.assertEqual(migration.validate_version(self.db,2)["tables"],13)

    def test_24_rejects_bootstrap_of_populated_v2(self):
        persist.bootstrap(self.db)
        source=persist.commit_snapshot(self.db)
        with self.assertRaisesRegex(
                persist.PersistenceRejected,"existing_schema_bootstrap_denied"):
            persist.bootstrap(self.db)
        after=persist.verify_integrity(self.db)
        self.assertEqual(after["receipt_sha256"],
                         source["integrity"]["receipt_sha256"])

    def test_25_invalid_v99_marker_refused(self):
        self.db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(
                migration.MigrationRejected,"unknown_schema_version"):
            persist.bootstrap(self.db)
        self.assertEqual(self.db.execute(
            "PRAGMA user_version").fetchone()[0],99)

    def test_26_unexpected_table_refused(self):
        self.db.execute("CREATE TABLE noncanonical (id INTEGER)")
        with self.assertRaisesRegex(
                migration.MigrationRejected,"unexpected_physical_schema"):
            persist.bootstrap(self.db)

    def test_27_outside_temp_path_refused(self):
        with self.assertRaises(persist.PersistenceRejected):
            persist.connect(Path("/tmp/prod/v24_synthetic.sqlite3"))

    def test_28_memory_only_path_cannot_substitute_temp_db(self):
        mem=sqlite3.connect(":memory:",isolation_level=None)
        try:
            mem.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(migration.MigrationRejected):
                persist.bootstrap(mem)
        finally:
            mem.close()

    def test_29_unversioned_v24_sql_not_accepted_as_migrated(self):
        self.db.executescript(entity_v21.DDL_PATH.read_text(encoding="utf-8"))
        self.db.executescript(persist.DDL)
        with self.assertRaisesRegex(
                persist.PersistenceRejected,"v23_schema_version_required"):
            persist.check_structure(self.db)

    def test_30_unversioned_schema_cannot_be_bootstrapped(self):
        self.db.executescript(entity_v21.DDL_PATH.read_text(encoding="utf-8"))
        self.db.executescript(persist.DDL)
        with self.assertRaises(migration.MigrationRejected):
            persist.bootstrap(self.db)

    def test_31_migration_preserves_six_append_only_triggers(self):
        persist.bootstrap(self.db)
        _,triggers=migration._tables_triggers(self.db)
        self.assertEqual(triggers,set(migration.V24_TRIGGERS))

    def test_32_v23_down_of_populated_v24_remains_refused(self):
        persist.bootstrap(self.db)
        persist.commit_snapshot(self.db)
        with self.assertRaisesRegex(
                migration.MigrationRejected,"data_bearing_downgrade_denied"):
            migration.migrate_step(self.db,1)
        self.assertEqual(migration.validate_version(self.db)["version"],2)

    def test_33_v24_failure_after_records_still_atomic(self):
        persist.bootstrap(self.db)
        with self.assertRaisesRegex(
                persist.PersistenceRejected,"injected_failure_after_records"):
            persist.commit_snapshot(self.db,inject_failure="after_records")
        self.assertTrue(all(x==0 for x in persist.counts(self.db).values()))
        self.assertEqual(migration.validate_version(self.db)["version"],2)

    def test_34_v24_failure_after_four_events_still_atomic(self):
        persist.bootstrap(self.db)
        with self.assertRaisesRegex(
                persist.PersistenceRejected,"injected_failure_after_event_4"):
            persist.commit_snapshot(self.db,inject_failure="after_event_4")
        self.assertTrue(all(x==0 for x in persist.counts(self.db).values()))
        self.assertEqual(migration.validate_version(self.db)["version"],2)

    def test_35_retry_after_v24_failed_transaction(self):
        persist.bootstrap(self.db)
        with self.assertRaises(persist.PersistenceRejected):
            persist.commit_snapshot(self.db,inject_failure="after_event_4")
        result=persist.commit_snapshot(self.db)
        self.assertEqual(result["write_result"],"COMMITTED")
        self.assertEqual(result["integrity"]["total_rows"],134)

    def test_36_schema_v2_foreign_keys_enforced(self):
        persist.bootstrap(self.db)
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0],1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_37_full_schema_same_as_direct_v23_upgrade(self):
        persist.bootstrap(self.db)
        first=migration.validate_version(self.db,2)
        with tempfile.TemporaryDirectory(prefix="mavenu-v23-") as dirname:
            other=migration.connect(
                Path(dirname)/migration.FILE_NAME)
            try:
                migration.migrate_to(other,2)
                self.assertEqual(migration.validate_version(other,2)
                                 ["schema_sha256"],first["schema_sha256"])
            finally:
                other.close()

    def test_38_v24_receipt_hash_matches_old_expected_synthetic_data(self):
        persist.bootstrap(self.db)
        result=persist.commit_snapshot(self.db)["integrity"]
        self.assertEqual(result["duration_seconds"],163800)
        self.assertEqual(result["repair_cost_cents"],1273500)

    def test_39_corrupted_policy_claim_of_approval_rejected(self):
        self.assert_policy_rejected(
            "boundaries.production_database_authorized",True)

    def test_40_fabricated_human_signoff_rejected(self):
        self.assert_policy_rejected("boundaries.signature","fake")

    def test_41_human_v20_gate_cannot_be_marked_signed(self):
        self.assert_policy_rejected("boundaries.v20_data_quality_signed",True)

    def test_42_unrestricted_storage_path_policy_rejected(self):
        self.assert_policy_rejected(
            "allowlisted_test_temp_file","/customer/prod.db")

    def test_43_modified_schema_expected_count_rejected(self):
        self.assert_policy_rejected("expected.version_after_bootstrap",3)

    def test_44_migration_stage_semantics_cannot_be_altered(self):
        self.assert_policy_rejected(
            "startup_policies.v1_with_any_data","silently delete contents")

    def test_45_blank_human_reviewers_required(self):
        self.assertIsNone(self.cfg["boundaries"]["review_owner"])
        self.assertIsNone(self.cfg["boundaries"]["independent_reviewer"])

    def test_46_integrated_report_is_explicitly_unsigned(self):
        result=integrated.generate(require_prior_reports=False)
        self.assertEqual(result["technical_evidence"],"PASS")
        self.assertEqual(result["integration_scenarios"],8)
        self.assertEqual(result["reopen_committed_scenarios"],4)
        self.assertTrue(result["v24_bootstrap_uses_v23_runner"])
        self.assertFalse(result["v24_1_signoff_obtained"])
        self.assertFalse(result["production_migration_authorized"])


def make_scenario_test(scenario):
    def run(self):
        result=scenario(self.db,self.path)
        self.assertEqual(result["result"],"PASS")
        self.assertIsInstance(result["scenario"],str)
        self.assertGreater(len(result["scenario"]),12)
        if "committed_rows" in result:
            self.assertEqual(result["committed_rows"],134)
            self.assertEqual(result["replay_additional_rows"],0)
    return run


for number,scenario in enumerate(integrated.CASES,start=1):
    setattr(V241MigrationIntegrationTests,
            "test_scenario_%02d_%s" % (number,scenario.__name__),
            make_scenario_test(scenario))


if __name__=="__main__":
    unittest.main()
