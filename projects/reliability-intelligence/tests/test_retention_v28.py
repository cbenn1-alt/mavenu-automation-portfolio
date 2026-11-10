"""V28 synthetic retention/archive/delete/legal-hold technical tests.

Only automatically deleted SQLite test stores. No actual legal hold authority,
encrypted/secure erasure, production data rights, or backup deletion proof.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

import isolation_v26
import migrate_v23
import persist_v24
import retention_v28 as life
import verify_v28


class V28RetentionTests(unittest.TestCase):
    def setUp(self):
        self.source_tmp=tempfile.TemporaryDirectory(prefix="mavenu-v24-")
        self.life_tmp=tempfile.TemporaryDirectory(prefix="mavenu-v28-")
        self.source_path=Path(self.source_tmp.name)/persist_v24.NAME
        self.life_path=Path(self.life_tmp.name)/life.FILE
        self.source=persist_v24.connect(self.source_path)
        persist_v24.bootstrap(self.source)
        isolation_v26.seed_isolated_fixture(self.source)
        self.db=life.connect_lifecycle(self.life_path)
        life.initialize(self.db)
        life.seed_from_v26(self.db,self.source)
        self.cfg=life.policy()

    def tearDown(self):
        self.db.close()
        self.source.close()
        self.life_tmp.cleanup()
        self.source_tmp.cleanup()

    def holds(self):
        for key in life.HOLD_TARGETS:
            life.place_hold(self.db,key)

    def rejected_contract(self,parts,value):
        p=copy.deepcopy(self.cfg)
        obj=p
        keys=parts.split(".")
        for key in keys[:-1]:
            obj=obj[key]
        obj[keys[-1]]=value
        with self.assertRaises(life.RetentionRejected):
            life.validate_policy(p)

    def test_01_exact_v28_objective(self):
        self.assertEqual(self.cfg["objective"],
                         "Enforce retention, deletion and archives")
        self.assertEqual(self.cfg["required_proof"],
                         "Retention-policy tests")

    def test_02_policy_is_synthetic(self):
        life.validate_policy(self.cfg)
        self.assertEqual(self.cfg["state"],
                         "SYNTHETIC_LIFECYCLE_PROTOTYPE_HUMAN_REVIEW_PENDING")

    def test_03_customer_durations_unapproved(self):
        self.assertFalse(self.cfg["decision"]["retention_period_approved"])

    def test_04_purge_threshold_90_for_both_classes(self):
        self.assertEqual(life.RETENTION["case_summary"][1],90)
        self.assertEqual(life.RETENTION["evidence_reference"][1],90)

    def test_05_case_archive_after_30(self):
        self.assertEqual(life.RETENTION["case_summary"][0],30)

    def test_06_evidence_archive_after_14(self):
        self.assertEqual(life.RETENTION["evidence_reference"][0],14)

    def test_07_no_active_scheduler(self):
        self.assertTrue(self.cfg["storage_design"]["no_real_schedule"])

    def test_08_no_untrusted_customer_source(self):
        self.assertTrue(self.cfg["storage_design"]["no_customer_records"])

    def test_09_stores_in_separate_temp_files(self):
        self.assertNotEqual(self.source_path,self.life_path)
        self.assertTrue(self.source_path.exists())
        self.assertTrue(self.life_path.exists())

    def test_10_host_sqlite_schema_stays_version_two(self):
        self.assertEqual(migrate_v23.validate_version(
            self.source,2)["version"],2)

    def test_11_sidecar_has_exact_table_inventory(self):
        tables={x[0] for x in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,life.TABLES)
        self.assertEqual(life.check(self.db)["triggers"],2)

    def test_12_source_has_38_rows(self):
        self.assertEqual(self.source.execute(
            "SELECT COUNT(*) FROM maintenance_case").fetchone()[0],12)

    def test_13_lifecycle_initial_24_objects(self):
        self.assertEqual(life.state(self.db),{
            "active":24,"archived":0,"purged":0,
            "holds":0,"active_held":0,"events":0})

    def test_14_composite_scope_identity(self):
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM active_record WHERE "
            "case_id='SYN-CASE-001'").fetchone()[0],8)

    def test_15_holds_require_exact_tenant_scope(self):
        bad=("SYN-TENANT-999","SYN-SITE-001",
             "SYN-CASE-003","case_summary")
        with self.assertRaisesRegex(
                life.RetentionRejected,"hold_target_not_in_scoped_active_store"):
            life.place_hold(self.db,bad)

    def test_16_holds_require_known_reviewer_in_test(self):
        with self.assertRaisesRegex(
                life.RetentionRejected,"not_a_simulated_hold_reviewer"):
            life.place_hold(self.db,life.HOLD_TARGETS[0],
                            reviewer="SYN-REVIEWER-UNKNOWN")

    def test_17_first_hold_creates_append_only_audit(self):
        life.place_hold(self.db,life.HOLD_TARGETS[0])
        s=life.state(self.db)
        self.assertEqual((s["holds"],s["events"]),(1,1))

    def test_18_two_hold_targets_are_distinct(self):
        self.holds()
        self.assertEqual(life.state(self.db)["holds"],2)

    def test_19_duplicate_hold_attempt_rejected(self):
        life.place_hold(self.db,life.HOLD_TARGETS[0])
        with self.assertRaises(sqlite3.IntegrityError):
            life.place_hold(self.db,life.HOLD_TARGETS[0])
        self.assertEqual(life.state(self.db)["events"],1)

    def test_20_active_held_record_not_archived(self):
        self.holds()
        life.enforce(self.db)
        self.assertEqual(life.state(self.db)["active_held"],2)

    def test_21_archive_and_purge_under_active_holds(self):
        self.holds()
        result=life.enforce(self.db)["after"]
        self.assertEqual(result,{"active":10,"archived":8,"purged":6,
                                 "holds":2,"active_held":2,"events":16})

    def test_22_nonheld_120_day_cohorts_purged(self):
        self.holds()
        life.enforce(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM purge_tombstone").fetchone()[0],6)

    def test_23_40_day_cohorts_archived(self):
        life.enforce(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM archive_record WHERE "
            "case_id='SYN-CASE-002'").fetchone()[0],8)

    def test_24_5_day_cohorts_remain_active(self):
        life.enforce(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM active_record WHERE "
            "case_id='SYN-CASE-001'").fetchone()[0],8)

    def test_25_no_holds_purges_all_older_cases(self):
        result=life.enforce(self.db)
        self.assertEqual(result["after"]["purged"],8)
        self.assertEqual(result["after"]["active"],8)

    def test_26_no_holds_archives_eight(self):
        self.assertEqual(life.enforce(self.db)["after"]["archived"],8)

    def test_27_all_cases_accounted_for(self):
        self.holds()
        state=life.enforce(self.db)["after"]
        self.assertEqual(state["active"]+state["archived"]+state["purged"],24)

    def test_28_hold_release_denied_wrong_reviewer(self):
        self.holds()
        with self.assertRaisesRegex(
                life.RetentionRejected,"not_a_simulated_hold_reviewer"):
            life.release_hold(self.db,life.HOLD_TARGETS[0],
                              reviewer="FAKE")

    def test_29_hold_release_denied_wrong_scope(self):
        self.holds()
        with self.assertRaisesRegex(
                life.RetentionRejected,"hold_not_found_in_scope"):
            life.release_hold(
                self.db,("SYN-TENANT-002","SYN-SITE-001",
                         "SYN-CASE-003","case_summary"))

    def test_30_hold_released_does_not_immediately_purge(self):
        self.holds()
        life.enforce(self.db)
        life.release_hold(self.db,life.HOLD_TARGETS[0])
        self.assertEqual(life.state(self.db)["purged"],6)

    def test_31_released_hold_purges_on_next_policy_run(self):
        self.holds()
        life.enforce(self.db)
        life.release_hold(self.db,life.HOLD_TARGETS[0])
        result=life.enforce(self.db)
        self.assertEqual(result["after"]["purged"],7)

    def test_32_both_released_holds_purge(self):
        self.holds()
        life.enforce(self.db)
        for key in life.HOLD_TARGETS:
            life.release_hold(self.db,key)
        state=life.enforce(self.db)["after"]
        self.assertEqual(state,{"active":8,"archived":8,"purged":8,
                                "holds":0,"active_held":0,"events":20})

    def test_33_repeated_policy_is_idempotent(self):
        self.holds()
        life.enforce(self.db)
        first=life.state(self.db)
        second=life.enforce(self.db)
        self.assertEqual(second["after"],first)
        self.assertEqual(second["operations"]["archived"],0)
        self.assertEqual(second["operations"]["purged"],0)

    def test_34_hold_never_automatically_expires(self):
        self.holds()
        life.enforce(self.db)
        life.enforce(self.db)
        self.assertEqual(life.state(self.db)["holds"],2)

    def test_35_frozen_now_only(self):
        with self.assertRaisesRegex(
                life.RetentionRejected,"unreviewed_retention_as_of"):
            life.enforce(self.db,as_of="2027-01-01T12:00:00Z")

    def test_36_invalid_failure_token_rejected(self):
        with self.assertRaisesRegex(
                life.RetentionRejected,"unknown_retention_injection"):
            life.enforce(self.db,inject_failure="erase_backups")

    def test_37_rollback_after_first_archive(self):
        self.holds()
        before=life.state(self.db)
        with self.assertRaisesRegex(
                life.RetentionRejected,"injected_transition_rollback"):
            life.enforce(self.db,inject_failure="after_first_transition")
        self.assertEqual(life.state(self.db),before)

    def test_38_rollback_after_first_purge(self):
        self.holds()
        before=life.state(self.db)
        with self.assertRaisesRegex(
                life.RetentionRejected,"injected_purge_rollback"):
            life.enforce(self.db,inject_failure="after_first_purge")
        self.assertEqual(life.state(self.db),before)

    def test_39_retry_succeeds_after_rollback(self):
        self.holds()
        with self.assertRaises(life.RetentionRejected):
            life.enforce(self.db,inject_failure="after_first_purge")
        self.assertEqual(life.enforce(self.db)["after"]["purged"],6)

    def test_40_audit_chain_survives_rollback(self):
        self.holds()
        with self.assertRaises(life.RetentionRejected):
            life.enforce(self.db,inject_failure="after_first_transition")
        self.assertEqual(life.assert_chain(self.db),2)
        self.assertEqual(life.state(self.db)["events"],2)

    def test_41_audit_chain_has_correct_sequence(self):
        self.holds()
        life.enforce(self.db)
        self.assertEqual(life.assert_chain(self.db),16)

    def test_42_audit_rows_resist_update(self):
        self.holds()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE audit_event SET action='FAKE' WHERE sequence=1")

    def test_43_audit_rows_resist_delete(self):
        self.holds()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM audit_event WHERE sequence=1")

    def test_44_tombstones_have_only_opaque_hash_class_and_time(self):
        life.enforce(self.db)
        cols={r[1] for r in self.db.execute(
            "PRAGMA table_info(purge_tombstone)")}
        self.assertEqual(cols,{"object_sha256","data_class","purged_at_utc"})
        self.assertNotIn("tenant_id",cols)
        self.assertNotIn("case_id",cols)

    def test_45_tombstone_hash_is_deterministic(self):
        key=("SYN-TENANT-001","SYN-SITE-001",
             "SYN-CASE-003","case_summary")
        self.assertEqual(life.object_hash(key),life.object_hash(key))
        self.assertEqual(len(life.object_hash(key)),64)

    def test_46_tombstone_hash_includes_tenant_scope(self):
        a=life.object_hash(("SYN-TENANT-001","SYN-SITE-001",
                            "SYN-CASE-003","case_summary"))
        b=life.object_hash(("SYN-TENANT-002","SYN-SITE-001",
                            "SYN-CASE-003","case_summary"))
        self.assertNotEqual(a,b)

    def test_47_held_target_kept_physically_in_active_table(self):
        self.holds()
        life.enforce(self.db)
        for key in life.HOLD_TARGETS:
            self.assertEqual(self.db.execute(
                "SELECT COUNT(*) FROM active_record WHERE tenant_id=? "
                "AND site_id=? AND case_id=? AND data_class=?",key
            ).fetchone()[0],1)

    def test_48_deleted_target_absent_from_active_and_archive(self):
        life.enforce(self.db)
        key=life.HOLD_TARGETS[0]
        for table in ("active_record","archive_record"):
            self.assertEqual(self.db.execute(
                "SELECT COUNT(*) FROM "+table+" WHERE tenant_id=? "
                "AND site_id=? AND case_id=? AND data_class=?",key
            ).fetchone()[0],0)

    def test_49_deleted_target_has_hash_tombstone(self):
        life.enforce(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM purge_tombstone WHERE object_sha256=?",
            (life.object_hash(life.HOLD_TARGETS[0]),)
        ).fetchone()[0],1)

    def test_50_staged_archive_payload_hash_unchanged(self):
        key=("SYN-TENANT-001","SYN-SITE-001",
             "SYN-CASE-002","case_summary")
        old=self.db.execute(
            "SELECT payload_sha256 FROM active_record WHERE tenant_id=? "
            "AND site_id=? AND case_id=? AND data_class=?",key
        ).fetchone()[0]
        life.enforce(self.db)
        new=self.db.execute(
            "SELECT payload_sha256 FROM archive_record WHERE tenant_id=? "
            "AND site_id=? AND case_id=? AND data_class=?",key
        ).fetchone()[0]
        self.assertEqual(old,new)

    def test_51_archive_is_real_separate_table(self):
        life.enforce(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM active_record WHERE case_id='SYN-CASE-002'"
        ).fetchone()[0],0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM archive_record WHERE case_id='SYN-CASE-002'"
        ).fetchone()[0],8)

    def test_52_source_database_unchanged_by_policy_run(self):
        original=life._source_hash(self.source)
        self.holds()
        life.enforce(self.db)
        self.assertEqual(life._source_hash(self.source),original)

    def test_53_source_still_has_v26_12_cases(self):
        self.holds()
        life.enforce(self.db)
        self.assertEqual(self.source.execute(
            "SELECT COUNT(*) FROM maintenance_case").fetchone()[0],12)

    def test_54_no_production_customer_data_rights(self):
        self.assertFalse(self.cfg["decision"]["customer_access_authorized"])
        self.assertFalse(self.cfg["decision"]["production_data_lifecycle_authorized"])

    def test_55_no_authenticated_legal_hold_reviewer(self):
        self.assertFalse(self.cfg["decision"]["authenticated_reviewer_implemented"])

    def test_56_secure_disk_erase_not_claimed(self):
        self.assertTrue(self.cfg["storage_design"]
                        ["secure_erase_of_old_db_pages_unverified"])

    def test_57_backups_untouched(self):
        self.assertTrue(self.cfg["storage_design"]["no_real_backup_deletion"])

    def test_58_signatures_unassigned(self):
        for k in ("owner","security_reviewer","legal_reviewer",
                  "approved_at_utc","signature"):
            self.assertIsNone(self.cfg["decision"][k])

    def test_59_formal_approvals_blocked(self):
        for k in ("v10_formal_promotion","v20_data_quality_signoff",
                  "v21_v27_human_reviews_complete",
                  "independent_v28_review_approved"):
            self.assertFalse(self.cfg["decision"][k])

    def test_60_policy_cannot_expand_customer_access(self):
        self.rejected_contract("decision.customer_access_authorized",True)

    def test_61_policy_cannot_claim_real_erase(self):
        self.rejected_contract(
            "storage_design.secure_erase_of_old_db_pages_unverified",False)

    def test_62_policy_cannot_change_retention_duration(self):
        p=copy.deepcopy(self.cfg)
        p["storage_design"]["categories"][0]["purge_after_days"]=1
        with self.assertRaises(life.RetentionRejected):
            life.validate_policy(p)

    def test_63_policy_cannot_remove_legal_hold(self):
        self.rejected_contract("storage_design.hold_targets",[])

    def test_64_policy_cannot_claim_signed_reviewer(self):
        self.rejected_contract("decision.signature","FAKE")

    def test_65_policy_cannot_upgrade_schema_version(self):
        self.rejected_contract("schema_version","2.0.0")

    def test_66_policy_cannot_hide_rollback_failures(self):
        self.rejected_contract("storage_design.failure_injections",[])

    def test_67_report_keeps_human_signoff_pending(self):
        result=verify_v28.generate(require_prior_reports=False)
        self.assertEqual(result["technical_evidence"],"PASS")
        self.assertEqual(result["human_v28_review"],"PENDING")
        self.assertFalse(result["production_secure_erasure_verified"])
        self.assertEqual(result["first_transition_counts"]["purged"],6)
        self.assertEqual(result["final_after_simulated_hold_release"]["purged"],8)

    def test_68_no_live_scheduler(self):
        self.assertTrue(self.cfg["storage_design"]["no_real_schedule"])

    def test_69_open_database_revalidation(self):
        self.holds()
        life.enforce(self.db)
        other=life.connect_lifecycle(self.life_path)
        try:
            self.assertEqual(life.state(other)["purged"],6)
            self.assertEqual(life.check(other)["audit_chain"],"VALID")
        finally:
            other.close()

    def test_70_outside_temp_path_rejected(self):
        with self.assertRaises(life.RetentionRejected):
            life.connect_lifecycle(Path("/tmp/customer-prod.db"))

    def test_71_unknown_class_hash_rejected(self):
        with self.assertRaisesRegex(
                life.RetentionRejected,"invalid_lifecycle_object_key"):
            life.object_hash(("SYN-TENANT-001","SYN-SITE-001",
                              "SYN-CASE-003","unapproved_class"))

    def test_72_missing_hold_release_denied(self):
        with self.assertRaisesRegex(
                life.RetentionRejected,"hold_not_found_in_scope"):
            life.release_hold(self.db,life.HOLD_TARGETS[0])

    def test_73_every_event_is_hash_linked(self):
        self.holds()
        life.enforce(self.db)
        rows=self.db.execute(
            "SELECT COUNT(*) FROM audit_event").fetchone()[0]
        self.assertEqual(life.assert_chain(self.db),rows)
        self.assertEqual(rows,16)

    def test_74_audit_tamper_detected_if_triggers_removed(self):
        self.holds()
        self.db.execute("DROP TRIGGER v28_audit_no_update")
        self.db.execute(
            "UPDATE audit_event SET event_sha256=? WHERE sequence=1",
            ("a"*64,)
        )
        with self.assertRaisesRegex(
                life.RetentionRejected,"lifecycle_audit_hash_invalid"):
            life.assert_chain(self.db)

    def test_75_no_longterm_archive_or_backup_retention(self):
        self.assertFalse(self.cfg["decision"]["backup_retention_approved"])
        self.assertFalse(self.cfg["decision"]["deletion_or_export_rights_approved"])

    def test_76_not_production_tenant_isolation(self):
        self.assertFalse(self.cfg["decision"]["production_data_lifecycle_authorized"])

    def test_77_no_unspecified_yearlong_hold_autoexpiry(self):
        self.assertIn("never automatically expires",
                      self.cfg["storage_design"]["hold_behavior"])

    def test_78_source_clock_is_not_real_world_timestamp(self):
        self.assertIn("NOT treated as observed real-world history",
                      self.cfg["storage_design"]["retention_clock"])


def make_record_test(tenant,site,case,cls):
    def run(self):
        key=(tenant,site,case,cls)
        before=self.db.execute(
            "SELECT COUNT(*) FROM active_record WHERE tenant_id=? "
            "AND site_id=? AND case_id=? AND data_class=?",key
        ).fetchone()[0]
        self.assertEqual(before,1)
        life.enforce(self.db)
        suffix=case[-3:]
        if suffix=="001":
            target="active_record"
        elif suffix=="002":
            target="archive_record"
        else:
            target=None
        if target:
            self.assertEqual(self.db.execute(
                "SELECT COUNT(*) FROM "+target+" WHERE tenant_id=? "
                "AND site_id=? AND case_id=? AND data_class=?",key
            ).fetchone()[0],1)
        else:
            self.assertEqual(self.db.execute(
                "SELECT COUNT(*) FROM purge_tombstone WHERE object_sha256=?",
                (life.object_hash(key),)).fetchone()[0],1)
            for tab in ("active_record","archive_record"):
                self.assertEqual(self.db.execute(
                    "SELECT COUNT(*) FROM "+tab+" WHERE tenant_id=? "
                    "AND site_id=? AND case_id=? AND data_class=?",key
                ).fetchone()[0],0)
    return run


for tenant,site in isolation_v26.TENANT_SITE:
    for suffix in ("001","002","003"):
        for cls in life.CLASSES:
            method="test_record_%s_%s_%s_%s"%(tenant[-3:],site[-3:],
                                                 suffix,cls)
            setattr(V28RetentionTests,method,make_record_test(
                tenant,site,"SYN-CASE-"+suffix,cls
            ))


if __name__=="__main__":
    unittest.main()
