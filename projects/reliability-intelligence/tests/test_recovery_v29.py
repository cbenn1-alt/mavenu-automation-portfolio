"""V29 timed restore / compromised backup / governance regression.

All recovery experiments use disposable, fabricated SQLite source copies.
No actual production restore/RPO/RTO, retained backups or V28 hold replay.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

import recovery_v29 as rec
import persist_v24
import verify_v29


class V29RestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=rec.policy()
        cls.data=rec.run_evidence()
        cls.success={x["case"]:x for x in cls.data["timed_recovery_scenarios"]}
        cls.refused={x["case"]:x for x in cls.data["corruption_and_failure_scenarios"]}

    def invalid_policy(self,key,value):
        changed=copy.deepcopy(self.cfg)
        node=changed
        parts=key.split(".")
        for part in parts[:-1]:
            node=node[part]
        node[parts[-1]]=value
        with self.assertRaises(rec.RecoveryRejected):
            rec.validate_policy(changed)

    def test_01_exact_v29_objective(self):
        self.assertEqual(self.cfg["objective"],
                         "Execute restore and corruption response drill")

    def test_02_exact_v29_proof(self):
        self.assertEqual(self.cfg["required_proof"],"Timed restore evidence")

    def test_03_contract_is_unsigned(self):
        rec.validate_policy(self.cfg)
        self.assertEqual(self.cfg["state"],
                         "SYNTHETIC_RESTORE_DRILL_HUMAN_REVIEW_PENDING")

    def test_04_v28_merged_baseline(self):
        self.assertEqual(self.cfg["base_branch"],
                         "feature/reliability-intelligence-v22")

    def test_05_v23_version_two_required(self):
        self.assertEqual(self.cfg["recovery_design"]["version"],2)

    def test_06_three_independent_temporary_directories(self):
        self.assertIn("three automatically deleted",
                      self.cfg["recovery_design"]["source_backup_restore_dirs"])

    def test_07_backup_copy_uses_sqlite_api(self):
        self.assertIn("SQLite online backup",
                      self.cfg["recovery_design"]["method"])

    def test_08_no_real_customer_data(self):
        self.assertFalse(self.cfg["recovery_design"]["real_customer_data_used"])

    def test_09_no_actual_production_rto(self):
        self.assertFalse(self.cfg["governance"]["production_rto_approved"])

    def test_10_no_actual_production_rpo(self):
        self.assertFalse(self.cfg["governance"]["production_rpo_approved"])

    def test_11_retention_and_legal_hold_not_restored(self):
        self.assertFalse(self.cfg["recovery_design"]
                         ["retention_v28_sidecar_restore_included"])

    def test_12_no_recoverable_backup_retained(self):
        self.assertFalse(self.cfg["recovery_design"]["production_backup_retained"])

    def test_13_no_real_power_loss(self):
        self.assertFalse(self.cfg["recovery_design"]["real_power_loss_tested"])

    def test_14_no_real_offsite_copy(self):
        self.assertFalse(self.cfg["recovery_design"]["real_offsite_copy_used"])

    def test_15_no_scheduler_activated(self):
        self.assertFalse(self.cfg["recovery_design"]["scheduler_activated"])

    def test_16_all_three_successes_present(self):
        self.assertEqual(len(self.success),3)

    def test_17_all_four_refusals_present(self):
        self.assertEqual(len(self.refused),4)

    def test_18_recovery_reopens_target(self):
        for item in self.success.values():
            self.assertTrue(item["restore"]["reopened_target"])

    def test_19_every_success_recovers_134(self):
        self.assertTrue(all(x["restore"]["restored_rows"]==134
                            for x in self.success.values()))

    def test_20_every_success_recovers_twelve_events(self):
        self.assertTrue(all(x["restore"]["restored_events"]==12
                            for x in self.success.values()))

    def test_21_version_marker_kept(self):
        self.assertTrue(all(x["restore"]["schema_version"]==2
                            for x in self.success.values()))

    def test_22_measurements_have_expected_fields(self):
        for row in self.success.values():
            for field in self.cfg["recovery_design"]["timing_fields_ms"]:
                self.assertIn(field,row["restore"])
                self.assertGreaterEqual(row["restore"][field],0)

    def test_23_timing_threshold(self):
        for row in self.success.values():
            self.assertLessEqual(row["restore"]["restore_total_ms"],10000)

    def test_24_timings_use_monotonic_timer(self):
        self.assertEqual(self.cfg["recovery_design"]["clock"],
                         "time.perf_counter_ns")

    def test_25_single_sample_not_statistical_sla(self):
        self.assertEqual(self.cfg["recovery_design"]
                         ["sample_count_per_scenario"],1)

    def test_26_zero_post_snapshot_writes_is_not_rpo(self):
        for row in self.success.values():
            self.assertEqual(row["restore"]["synthetic_post_backup_writes"],0)
            self.assertFalse(row["restore"]["production_rpo_approved"])

    def test_27_actual_rto_not_approved_from_ms(self):
        for row in self.success.values():
            self.assertFalse(row["restore"]["production_rto_approved"])

    def test_28_no_customer_restore(self):
        for row in self.success.values():
            self.assertFalse(row["restore"]["real_customer_data_restored"])

    def test_29_logic_corruption_detected(self):
        self.assertTrue(self.success[
            "logical_active_corruption_restore"]["source_corruption_detected"])

    def test_30_physical_corruption_detected(self):
        self.assertTrue(self.success[
            "physical_active_corruption_restore"]["source_corruption_detected"])

    def test_31_intact_source_not_reported_corrupt(self):
        self.assertFalse(self.success[
            "intact_baseline_restore"]["source_corruption_detected"])

    def test_32_backup_stays_valid_after_source_damage(self):
        self.assertEqual(
            len({r["restore"]["receipt_sha256"]
                 for r in self.success.values()}),1)

    def test_33_all_sources_untouched_by_restore(self):
        self.assertTrue(all(x["source_not_overwritten"]
                            for x in self.success.values()))

    def test_34_failed_target_not_retained(self):
        self.assertTrue(all(not x["target_created_after_failure"]
                            for x in self.refused.values()))

    def test_35_no_rows_accepted_from_invalid_backups(self):
        self.assertTrue(all(x["accepted_rows"]==0
                            for x in self.refused.values()))

    def test_36_all_failure_codes_are_fixed(self):
        codes={x["failure_code"] for x in self.refused.values()}
        self.assertEqual(codes,{
            "backup_missing_or_empty","backup_checksum_or_schema_failed",
            "backup_unreadable_or_corrupt","injected_restore_copy_abort"
        })

    def test_37_backup_missing_detected(self):
        self.assertEqual(self.refused["missing_backup"]["failure_code"],
                         "backup_missing_or_empty")

    def test_38_backup_record_digest_tamper_rejected(self):
        self.assertEqual(self.refused["tampered_backup_record"]["failure_code"],
                         "backup_checksum_or_schema_failed")

    def test_39_backup_header_damage_rejected(self):
        self.assertEqual(self.refused["corrupt_backup_header"]["failure_code"],
                         "backup_unreadable_or_corrupt")

    def test_40_post_copy_failure_cleanup(self):
        self.assertEqual(self.refused["injected_after_restore_copy"]["failure_code"],
                         "injected_restore_copy_abort")

    def test_41_source_and_backup_temp_cleanup(self):
        for r in self.success.values():
            self.assertTrue(r["temporary_files_cleaned"])
        for r in self.refused.values():
            self.assertTrue(r["temporary_files_cleaned"])

    def test_42_missing_backup_preflight_never_creates_target(self):
        self.assertFalse(self.refused["missing_backup"]
                         ["target_created_after_failure"])

    def test_43_untrusted_backup_never_counts_as_verified(self):
        for name in ("tampered_backup_record","corrupt_backup_header"):
            self.assertEqual(self.refused[name]["accepted_rows"],0)

    def test_44_production_risk_governance_no_approval(self):
        gov=self.cfg["governance"]
        self.assertFalse(gov["production_disaster_recovery_approved"])
        self.assertFalse(gov["actual_recovery_site_available"])

    def test_45_encryption_retention_not_approved(self):
        gov=self.cfg["governance"]
        self.assertFalse(gov["backup_encryption_approved"])
        self.assertFalse(gov["backup_retention_approved"])

    def test_46_human_owner_blank(self):
        gov=self.cfg["governance"]
        for field in ("owner","dba_reviewer","security_reviewer",
                      "reviewed_at_utc","signature"):
            self.assertIsNone(gov[field])

    def test_47_prior_phase_gates_blocked(self):
        gov=self.cfg["governance"]
        self.assertFalse(gov["v10_phase_promotion_approved"])
        self.assertFalse(gov["v20_data_quality_signoff"])
        self.assertFalse(gov["v21_to_v28_human_reviews_approved"])

    def test_48_cannot_claim_production_rto(self):
        self.invalid_policy("governance.production_rto_approved",True)

    def test_49_cannot_claim_production_rpo(self):
        self.invalid_policy("governance.production_rpo_approved",True)

    def test_50_cannot_forge_dr_signoff(self):
        self.invalid_policy("governance.signature","FAKE")

    def test_51_cannot_turn_on_real_scheduler(self):
        self.invalid_policy("recovery_design.scheduler_activated",True)

    def test_52_cannot_claim_v28_retention_restored(self):
        self.invalid_policy("recovery_design.retention_v28_sidecar_restore_included",True)

    def test_53_cannot_expand_restored_row_count(self):
        self.invalid_policy("expected.restored_rows_per_success",200)

    def test_54_cannot_drop_failure_scenarios(self):
        self.invalid_policy("recovery_design.scenarios_refused",[])

    def test_55_cannot_relax_time_guard(self):
        self.invalid_policy("recovery_design.max_synthetic_restore_total_ms",100000)

    def test_56_only_temporary_path_allowed(self):
        with self.assertRaises(rec.RecoveryRejected):
            rec.safe_path(Path("/tmp/customer.db"))

    def test_57_unknown_scenario_rejected(self):
        with self.assertRaisesRegex(
                rec.RecoveryRejected,"unknown_v29_drill_case"):
            rec.run_scenario("production_dr_certified")

    def test_58_source_backup_same_path_rejected(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            path=Path(dirname)/persist_v24.NAME
            with self.assertRaisesRegex(
                    rec.RecoveryRejected,
                    "restore_source_and_target_not_isolated"):
                rec.restore(path,path,"a"*64,"b"*64)

    def test_59_existing_target_not_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as out:
                source=Path(dirname)/persist_v24.NAME
                target=Path(out)/persist_v24.NAME
                target.write_bytes(b"preserve_me")
                with self.assertRaisesRegex(
                        rec.RecoveryRejected,
                        "restore_target_must_be_absent"):
                    rec.restore(source,target,"a"*64,"b"*64)
                self.assertEqual(target.read_bytes(),b"preserve_me")

    def test_60_invalid_manifest_rejected(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as out:
                with self.assertRaisesRegex(
                        rec.RecoveryRejected,
                        "invalid_restore_receipt_or_manifest"):
                    rec.restore(Path(dirname)/persist_v24.NAME,
                                Path(out)/persist_v24.NAME,
                                "bad","bad")

    def test_61_success_evidence_timing_extraction(self):
        r=verify_v29.generate(require_prior_reports=False)
        self.assertEqual(r["technical_evidence"],"PASS")
        self.assertEqual(r["synthetic_restore_count"],3)
        self.assertEqual(r["failed_backup_refusal_count"],4)

    def test_62_evidence_remains_unsigned(self):
        r=verify_v29.generate(require_prior_reports=False)
        self.assertEqual(r["v29_dr_approval"],"PENDING")
        self.assertFalse(r["production_recovery_authorized"])
        self.assertFalse(r["actual_production_rto_verified"])
        self.assertFalse(r["actual_production_rpo_verified"])

    def test_63_no_actual_customer_records(self):
        self.assertFalse(self.data["source_customer_data"])
        self.assertFalse(self.cfg["governance"]["actual_customer_data_access"])

    def test_64_previous_legal_hold_outside_scope(self):
        self.assertFalse(self.data["v28_legal_hold_and_retention_restore"])

    def test_65_source_and_restore_receipts_equal(self):
        self.assertTrue(all(len(v["restore"]["receipt_sha256"])==64
                            for v in self.success.values()))


def _make_success_case(name:str):
    def run(self):
        result=self.success[name]
        self.assertEqual(result["status"],"SUCCESS")
        self.assertTrue(result["verified_target"])
        self.assertEqual(result["restore"]["restored_rows"],134)
        self.assertTrue(result["temporary_files_cleaned"])
        self.assertFalse(result["restore"]["production_rto_approved"])
    return run


def _make_refusal_case(name:str):
    def run(self):
        result=self.refused[name]
        self.assertEqual(result["status"],"REFUSED")
        self.assertEqual(result["accepted_rows"],0)
        self.assertFalse(result["target_created_after_failure"])
        self.assertTrue(result["temporary_files_cleaned"])
    return run


for name in rec.SUCCESS_CASES:
    setattr(V29RestoreTests,"test_success_case_"+name,
            _make_success_case(name))
for name in rec.REFUSAL_CASES:
    setattr(V29RestoreTests,"test_refusal_case_"+name,
            _make_refusal_case(name))


if __name__=="__main__":
    unittest.main()
