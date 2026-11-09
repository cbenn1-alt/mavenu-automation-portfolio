"""V23 migration up/down and failure evidence. Synthetic-only test files.

The connected repository already had V24 merged into V22 before V23 backfill;
these tests add migration contracts without modifying historical V24 bootstrap.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT / "scripts"))

import entity_v21
import migrate_v23 as mig
import persist_v24
import verify_v23


class V23ReversibleMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="mavenu-v23-")
        self.path=Path(self.temp.name)/mig.FILE_NAME
        self.db=mig.connect(self.path)
        self.contract=mig.policy()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def upgrade(self,version=2):
        return mig.migrate_to(self.db,version)

    def rejected_policy(self,key,value):
        doc=copy.deepcopy(self.contract)
        node=doc
        segments=key.split(".")
        for x in segments[:-1]:
            node=node[x]
        node[segments[-1]]=value
        with self.assertRaises(mig.MigrationRejected):
            mig.validate_policy(doc)

    def test_01_architecture_objective_and_proof(self):
        self.assertEqual(self.contract["objective"],
                         "Implement reversible schema migration path")
        self.assertEqual(self.contract["required_proof"],
                         "Up/down migration evidence")

    def test_02_policy_is_unsigned_candidate(self):
        mig.validate_policy(self.contract)
        self.assertEqual(self.contract["state"],
                         "SYNTHETIC_TECHNICAL_MIGRATION_CANDIDATE_UNREVIEWED")

    def test_03_not_customer_or_production_upgrade(self):
        self.assertFalse(self.contract["design"]["no_real_customer_data"] is False)
        self.assertTrue(self.contract["design"]["no_production_upgrade"])
        self.assertFalse(self.contract["decision"]["production_schema_change_authorized"])

    def test_04_formal_phase_gates_remain_blocked(self):
        for key in ("v10_formal_promotion","v20_data_quality_signoff",
                    "v21_entity_schema_human_review",
                    "v22_identity_human_review",
                    "v23_migration_human_review",
                    "v24_persistence_human_review"):
            self.assertIs(self.contract["decision"][key],False)

    def test_05_no_named_reviewer_or_signature(self):
        for key in ("named_data_architect","named_database_administrator",
                    "named_security_reviewer","reviewed_at_utc",
                    "approval_signature"):
            self.assertIsNone(self.contract["decision"][key])

    def test_06_existing_v24_is_the_branch_baseline(self):
        self.assertEqual(self.contract["baseline_branch"],
                         "feature/reliability-intelligence-v22")
        self.assertIn("already",self.contract["limitations"][-1])

    def test_07_initial_v0_empty(self):
        state=mig.validate_version(self.db,0)
        self.assertEqual(state["tables"],0)
        self.assertEqual(state["triggers"],0)

    def test_08_database_is_only_approved_temp_file(self):
        self.assertTrue(self.path.parent.name.startswith("mavenu-v23-"))
        self.assertEqual(Path(self.db.execute("PRAGMA database_list")
                         .fetchall()[0][2]).resolve(),self.path.resolve())

    def test_09_transactional_sqlite_pragmas(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0],1)
        self.assertEqual(self.db.execute("PRAGMA synchronous").fetchone()[0],2)
        self.assertEqual(self.db.execute("PRAGMA journal_mode").fetchone()[0],"delete")

    def test_10_up_to_v1_ten_tables(self):
        result=mig.migrate_step(self.db,1)
        self.assertEqual(result["from"],0)
        self.assertEqual(result["to"],1)
        self.assertEqual(mig.validate_version(self.db)["tables"],10)

    def test_11_up_to_v2_thirteen_tables(self):
        result=self.upgrade()
        self.assertEqual(result["applied_steps"],2)
        self.assertEqual(result["final_state"]["tables"],13)
        self.assertEqual(result["final_state"]["triggers"],6)

    def test_12_v2_has_six_immutable_ledger_triggers(self):
        self.upgrade()
        tables,triggers=mig._tables_triggers(self.db)
        self.assertEqual(triggers,set(mig.V24_TRIGGERS))
        self.assertEqual(len(tables),13)

    def test_13_v2_to_v1_drops_only_empty_ledger(self):
        self.upgrade()
        step=mig.migrate_step(self.db,1)
        self.assertEqual(step["to"],1)
        self.assertEqual(mig.validate_version(self.db,1)["tables"],10)

    def test_14_v1_to_v0_drops_only_empty_entities(self):
        self.upgrade(1)
        step=mig.migrate_step(self.db,0)
        self.assertEqual(step["to"],0)
        self.assertEqual(mig.validate_version(self.db,0)["tables"],0)

    def test_15_complete_schema_roundtrip_restores_v0_hash(self):
        before=mig.validate_version(self.db,0)
        self.upgrade()
        self.upgrade(0)
        after=mig.validate_version(self.db,0)
        self.assertEqual(before["schema_sha256"],after["schema_sha256"])

    def test_16_schema_v1_hash_stable_after_v2_roundtrip(self):
        self.upgrade(1)
        first=mig.validate_version(self.db,1)
        self.upgrade(2)
        self.upgrade(1)
        self.assertEqual(first["schema_sha256"],
                         mig.validate_version(self.db,1)["schema_sha256"])

    def test_17_v2_schema_hash_stable_after_full_replay(self):
        self.upgrade(2)
        first=mig.validate_version(self.db,2)
        self.upgrade(0)
        self.upgrade(2)
        self.assertEqual(first["schema_sha256"],
                         mig.validate_version(self.db,2)["schema_sha256"])

    def test_18_reopen_preserves_schema_version(self):
        self.upgrade(2)
        second=mig.connect(self.path)
        try:
            self.assertEqual(mig.validate_version(second,2)["tables"],13)
        finally:
            second.close()

    def test_19_repeated_target_is_safe_noop(self):
        self.upgrade(2)
        report=mig.migrate_to(self.db,2)
        self.assertEqual(report["applied_steps"],0)
        self.assertEqual(report["final_state"]["version"],2)

    def test_20_nonadjacent_v0_to_v2_direct_step_denied(self):
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "non_adjacent_migration_denied"):
            mig.migrate_step(self.db,2)

    def test_21_nonadjacent_v2_to_v0_direct_step_denied(self):
        self.upgrade(2)
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "non_adjacent_migration_denied"):
            mig.migrate_step(self.db,0)

    def test_22_invalid_target_is_denied(self):
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "invalid_migration_target"):
            mig.migrate_to(self.db,4)

    def test_23_boolean_target_is_denied(self):
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "invalid_migration_target"):
            mig.migrate_step(self.db,True)

    def test_24_unknown_user_version_rejected(self):
        self.db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "unknown_schema_version"):
            mig.validate_version(self.db)

    def test_25_unexpected_schema_table_rejected(self):
        self.db.execute("CREATE TABLE unapproved_table (id INTEGER)")
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "unexpected_physical_schema"):
            mig.validate_version(self.db,0)

    def test_26_fks_always_enabled_after_migration(self):
        self.upgrade(2)
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0],1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_27_no_untracked_indexed_source_table(self):
        self.upgrade(2)
        tables,_=mig._tables_triggers(self.db)
        self.assertEqual(tables,set(mig.V21_TABLES)|set(mig.V24_TABLES))

    def test_28_nested_transaction_migration_denied(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaisesRegex(mig.MigrationRejected,
                                        "nested_migration_transaction_denied"):
                mig.migrate_step(self.db,1)
        finally:
            self.db.execute("ROLLBACK")

    def test_29_invalid_failure_token_denied(self):
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "invalid_migration_failure_injection"):
            mig.migrate_step(self.db,1,inject_failure="any_failure")

    def test_30_failure_token_wrong_step_denied(self):
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "failure_injection_step_mismatch"):
            mig.migrate_step(self.db,1,
                             inject_failure="down_v2_after_1_drop")

    def test_31_file_outside_allowlist_denied(self):
        with self.assertRaises(mig.MigrationRejected):
            mig.connect(Path("/tmp/customer-production.sqlite3"))

    def test_32_in_memory_connection_cannot_be_migrated(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with self.assertRaisesRegex(mig.MigrationRejected,
                                        "persistent_temporary_file_required"):
                mig.validate_version(db)
        finally:
            db.close()

    def test_33_v24_ledger_can_be_created_by_migration(self):
        self.upgrade(2)
        self.assertEqual(set(mig.V24_TABLES),
                         {x for x in mig._tables_triggers(self.db)[0]
                          if x.startswith("v24_")})

    def test_34_v21_table_foreign_key_declarations_survive_v2(self):
        self.upgrade(2)
        for name in mig.V21_TABLES:
            self.assertEqual(entity_v21._catalog_foreign_keys(self.db,name),
                             sorted(entity_v21.EXPECTED_FKS[name]))

    def test_35_downward_migration_refuses_nonempty_v21(self):
        self.upgrade(1)
        entity_v21.load_synthetic_preview(self.db,entity_v21.load_model())
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "data_bearing_downgrade_denied"):
            mig.migrate_step(self.db,0)
        self.assertEqual(mig.validate_version(self.db,1)["tables"],10)

    def test_36_populated_v21_rows_survive_v2_then_v1(self):
        self.upgrade(1)
        entity_v21.load_synthetic_preview(self.db,entity_v21.load_model())
        first=persist_v24.records_sha(self.db)
        self.upgrade(2)
        self.upgrade(1)
        self.assertEqual(persist_v24.records_sha(self.db),first)
        self.assertEqual(entity_v21.preview_counts(self.db)["total_rows"],120)

    def test_37_populated_v24_ledger_refuses_downgrade(self):
        self.upgrade(2)
        data=persist_v24.commit_snapshot(self.db)
        with self.assertRaisesRegex(mig.MigrationRejected,
                                    "data_bearing_downgrade_denied"):
            mig.migrate_step(self.db,1)
        self.assertEqual(mig.validate_version(self.db,2)["tables"],13)
        self.assertEqual(persist_v24.verify_integrity(self.db)
                         ["receipt_sha256"],data["integrity"]["receipt_sha256"])

    def test_38_populated_v24_ledger_reopens_after_denied_down(self):
        self.upgrade(2)
        persist_v24.commit_snapshot(self.db)
        with self.assertRaises(mig.MigrationRejected):
            mig.migrate_step(self.db,1)
        second=mig.connect(self.path)
        try:
            self.assertEqual(persist_v24.verify_integrity(second)
                             ["total_rows"],134)
        finally:
            second.close()

    def test_39_reference_golden_sources_unmodified(self):
        self.upgrade(2)
        self.assertEqual(mig.validate_version(self.db,2)["integrity"],"ok")

    def test_40_independent_evidence_generator_returns_unsigned_state(self):
        report=verify_v23.generate(require_prior_report=False)
        self.assertEqual(report["technical_evidence"],"PASS")
        self.assertEqual(report["up_steps_verified"],2)
        self.assertEqual(report["down_steps_verified"],2)
        self.assertEqual(report["fault_injections_rolled_back"],4)
        self.assertEqual(report["committed_v24_rows_protected"],134)
        self.assertFalse(report["production_migration_authorized"])
        self.assertEqual(report["v23_human_migration_review"],"PENDING")

    def test_41_policy_cannot_claim_production_upgrade(self):
        self.rejected_policy("decision.production_schema_change_authorized",True)

    def test_42_policy_cannot_fabricate_signoff(self):
        self.rejected_policy("decision.approval_signature","FAKE")

    def test_43_policy_cannot_claim_v20_approved(self):
        self.rejected_policy("decision.v20_data_quality_signoff",True)

    def test_44_policy_cannot_expand_storage_scope(self):
        self.rejected_policy("design.allowed_storage","production PostgreSQL")

    def test_45_policy_cannot_weaken_rollback_safety(self):
        self.rejected_policy("design.destructive_down_migrations_require_empty_affected_tables",False)

    def test_46_policy_cannot_modify_source_schema(self):
        self.rejected_policy("design.source_v21","other.sql")

    def test_47_policy_cannot_remove_failure_case(self):
        self.rejected_policy("design.failure_injection",[])

    def test_48_policy_cannot_change_stage_versions(self):
        self.rejected_policy("stages",[{}])

    def test_49_policy_cannot_add_customer_records(self):
        self.rejected_policy("expected.actual_customer_records",1)

    def test_50_policy_cannot_claim_human_v23_approval(self):
        self.rejected_policy("decision.v23_migration_human_review",True)

    def test_51_created_schema_remains_readable_after_noop(self):
        self.upgrade(2)
        before=mig.validate_version(self.db,2)
        mig.migrate_to(self.db,2)
        self.assertEqual(before,mig.validate_version(self.db,2))


def _make_table_test(table):
    def run(self):
        self.upgrade(1)
        self.assertIn(table,mig._tables_triggers(self.db)[0])
        self.assertEqual(
            tuple(c[1] for c in sorted(
                (c for c in self.db.execute(
                    'PRAGMA table_info("' + table + '")') if c[5]>0
                ),key=lambda c:c[5])),
            entity_v21.EXPECTED_PKS[table])
    return run


def _make_v24_table_test(table):
    def run(self):
        self.upgrade(2)
        self.assertIn(table,mig._tables_triggers(self.db)[0])
        self.assertEqual(self.db.execute(
            'SELECT COUNT(*) FROM "' + table + '"').fetchone()[0],0)
    return run


def _make_trigger_test(trigger):
    def run(self):
        self.upgrade(2)
        self.assertIn(trigger,mig._tables_triggers(self.db)[1])
        self.upgrade(1)
        self.assertNotIn(trigger,mig._tables_triggers(self.db)[1])
    return run


def _make_fault_test(start,target,fault):
    def run(self):
        self.upgrade(start)
        before=mig.validate_version(self.db,start)
        with self.assertRaisesRegex(
                mig.MigrationRejected,
                "^injected_migration_rollback_"+fault+"$"):
            mig.migrate_step(self.db,target,inject_failure=fault)
        after=mig.validate_version(self.db,start)
        self.assertEqual(after["schema_sha256"],before["schema_sha256"])
        second=mig.connect(self.path)
        try:
            self.assertEqual(
                mig.validate_version(second,start)["schema_sha256"],
                before["schema_sha256"])
        finally:
            second.close()
        self.assertEqual(mig.migrate_step(self.db,target)["to"],target)
    return run


for _name in mig.V21_TABLES:
    setattr(V23ReversibleMigrationTests,"test_v21_table_"+_name,
            _make_table_test(_name))
for _name in mig.V24_TABLES:
    setattr(V23ReversibleMigrationTests,"test_v24_table_"+_name,
            _make_v24_table_test(_name))
for _name in mig.V24_TRIGGERS:
    setattr(V23ReversibleMigrationTests,"test_trigger_"+_name,
            _make_trigger_test(_name))
for _start,_target,_fault in (
    (0,1,"up_v1_after_3_tables"),
    (1,2,"up_v2_after_1_ledger"),
    (2,1,"down_v2_after_1_drop"),
    (1,0,"down_v1_after_4_drops"),
):
    setattr(V23ReversibleMigrationTests,"test_atomic_"+_fault,
            _make_fault_test(_start,_target,_fault))

if __name__=="__main__":
    unittest.main()
