"""V25 indexing, query-plan and synthetic latency regression.

No customer data, no live SQLite deployment migration, no production SLA.
The complete benchmark uses a short-lived SQLite file and fabricated rows.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

import index_v25 as performance
import migrate_v23
import persist_v24
import verify_v25


class V25IndexPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = performance.load_contract()
        cls.snapshot = performance.run_profile()

    def test_01_exact_architecture_requirement(self):
        self.assertEqual(self.contract["objective"],
                         "Add indexes and performance profiling")
        self.assertEqual(self.contract["required_proof"],
                         "Query-plan and threshold report")

    def test_02_contract_is_unsigned_candidate(self):
        performance.validate_contract(self.contract)
        self.assertEqual(self.contract["status"],
                         "SYNTHETIC_INDEX_CANDIDATE_HUMAN_REVIEW_PENDING")

    def test_03_v24_1_integrated_in_base(self):
        self.assertTrue(self.contract["v24_1_migration_integrated"])
        self.assertEqual(self.contract["branch_base"],
                         "feature/reliability-intelligence-v22")

    def test_04_v23_version_marker_unchanged(self):
        self.assertEqual(self.snapshot["sqlite_schema_user_version"], 2)
        self.assertFalse(self.snapshot["index_install_is_v23_migration"])

    def test_05_four_index_candidates(self):
        self.assertEqual(self.snapshot["candidate_indexes"]["index_count"],4)

    def test_06_four_exact_queries_compared(self):
        self.assertEqual(self.snapshot["query_plan_and_threshold_report"]
                         ["queries_verified"],4)

    def test_07_synthetic_cases_count(self):
        counts=self.snapshot["synthetic_workload"]["generated_row_counts"]
        self.assertEqual(counts["maintenance_case"],3600)
        self.assertEqual(counts["asset"],1800)

    def test_08_synthetic_evidence_count(self):
        self.assertEqual(self.snapshot["synthetic_workload"]
                         ["generated_row_counts"]["evidence_reference"],3600)

    def test_09_site_and_tenant_count(self):
        counts=self.snapshot["synthetic_workload"]["generated_row_counts"]
        self.assertEqual(counts["site"],300)
        self.assertEqual(counts["tenant"],1)

    def test_10_total_benchmark_rows(self):
        self.assertEqual(self.snapshot["synthetic_workload"]
                         ["total_generated_rows"],9301)

    def test_11_no_customer_records(self):
        self.assertEqual(self.snapshot["synthetic_workload"]["customer_records"],0)
        self.assertFalse(self.snapshot["customer_data_used"])

    def test_12_no_foreign_key_violation(self):
        self.assertEqual(self.snapshot["synthetic_workload"]
                         ["foreign_key_violations"],0)

    def test_13_all_query_plan_indexes_selected(self):
        self.assertTrue(self.snapshot["query_plan_and_threshold_report"]
                        ["all_index_plans_selected"])

    def test_14_all_queries_return_identical_results(self):
        self.assertTrue(self.snapshot["query_plan_and_threshold_report"]
                        ["all_results_identical"])

    def test_15_absolute_latency_thresholds_met(self):
        self.assertTrue(self.snapshot["query_plan_and_threshold_report"]
                        ["thresholds_passed"])

    def test_16_no_speedup_ratio_as_pass_condition(self):
        self.assertTrue(self.snapshot["query_plan_and_threshold_report"]
                        ["baseline_vs_index_speedup_not_required"])

    def test_17_no_production_latency_sla_claim(self):
        self.assertFalse(self.snapshot["production_latency_SLA_verified"])
        self.assertTrue(self.snapshot["baseline_and_candidate_queries_warm_cache"])

    def test_18_index_ddl_rollback_verification(self):
        self.assertTrue(self.snapshot["injected_index_ddl_rollback_verified"])

    def test_19_four_original_query_fingerprints_present(self):
        comparisons=self.snapshot["query_plan_and_threshold_report"]["comparisons"]
        self.assertEqual(len(comparisons),4)
        self.assertTrue(all(len(row["result_sha256"])==64
                            for row in comparisons.values()))

    def test_20_production_index_rollout_not_approved(self):
        self.assertFalse(self.snapshot["production_index_rollout_approved"])
        self.assertFalse(self.contract["approval"]
                         ["production_index_migration_authorized"])

    def test_21_human_reviews_not_fabricated(self):
        for key in ("v10_formal_promotion","v20_data_correctness_signoff",
                    "v21_entity_schema_review","v22_identity_review",
                    "v23_migration_review","v24_storage_review",
                    "v24_1_integration_review","v25_index_plan_review"):
            self.assertIs(self.contract["approval"][key],False)

    def test_22_reviewer_signature_unset(self):
        for field in ("reviewer_id","review_date_utc","signature"):
            self.assertIsNone(self.contract["approval"][field])

    def test_23_exact_index_sql_allowlisted(self):
        self.assertEqual(len(performance._allowed_ddl()),4)

    def test_24_no_source_table_modification(self):
        self.assertEqual(self.snapshot["temp_schema_tables"],13)
        self.assertTrue(self.snapshot["temporary_db_cleaned"])

    def test_25_observed_latency_has_valid_sample_counts(self):
        comp=self.snapshot["query_plan_and_threshold_report"]["comparisons"]
        for label,row in comp.items():
            with self.subTest(name=label):
                self.assertEqual(row["baseline_latency"]["runs"],37)
                self.assertEqual(row["indexed_latency"]["runs"],37)
                self.assertEqual(row["indexed_latency"]["warmups"],5)
                self.assertGreaterEqual(row["indexed_latency"]["median_ms"],0)
                self.assertGreaterEqual(row["indexed_latency"]["p95_ms"],0)

    def test_26_report_carries_sqlite_engine_version(self):
        self.assertTrue(self.snapshot["sqlite_version"])

    def test_27_baseline_sql_is_read_only(self):
        for _, sql, _ in performance.QUERY_SPECS.values():
            self.assertTrue(sql.startswith("SELECT "))
            self.assertNotIn("INSERT",sql)
            self.assertNotIn("UPDATE",sql)
            self.assertNotIn("DELETE",sql)

    def test_28_candidate_index_names_are_fixed(self):
        self.assertEqual(len(performance.INDEX_COLUMNS),4)
        self.assertTrue(all(name.startswith("idx_v25_")
                            for name in performance.INDEX_COLUMNS))

    def test_29_data_preview_does_not_change_source(self):
        self.assertEqual(self.snapshot["synthetic_workload"]["source"],
                         "deterministic_generated_benchmark_not_frozen_v5_fixtures")

    def test_30_refuses_unknown_approval(self):
        changed=copy.deepcopy(self.contract)
        changed["approval"]["v25_index_plan_review"]=True
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_31_refuses_customer_data_authorization(self):
        changed=copy.deepcopy(self.contract)
        changed["approval"]["customer_data_authorized"]=True
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_32_refuses_fake_reviewer_identity(self):
        changed=copy.deepcopy(self.contract)
        changed["approval"]["reviewer_id"]="FAKE"
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_33_refuses_softening_latency_guards(self):
        changed=copy.deepcopy(self.contract)
        changed["policy"]["thresholds"]["p95_ms_max"]=10000
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_34_refuses_removing_index(self):
        changed=copy.deepcopy(self.contract)
        changed["indexes"].pop()
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_35_refuses_changing_composite_site_scope(self):
        changed=copy.deepcopy(self.contract)
        changed["indexes"][0]["columns"]=[["occurred_at_utc","DESC"]]
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_36_refuses_non_read_only_query_contract(self):
        changed=copy.deepcopy(self.contract)
        changed["queries"][0]["sql"]="DELETE FROM maintenance_case"
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_37_refuses_unapproved_workload_growth(self):
        changed=copy.deepcopy(self.contract)
        changed["policy"]["sites"]=100000
        with self.assertRaises(performance.IndexProfileRejected):
            performance.validate_contract(changed)

    def test_38_report_is_unsigned_and_pending(self):
        result=verify_v25.generate(require_prior_reports=False)
        self.assertEqual(result["technical_evidence"],"PASS")
        self.assertEqual(result["comparison"]["queries_verified"],4)
        self.assertEqual(result["v25_human_index_review"],"PENDING")
        self.assertFalse(result["production_index_deployment_authorized"])
        self.assertTrue(result["temporary_database_deleted"])

    def test_39_baseline_index_vs_result_mismatch_rejected(self):
        source=self.snapshot["query_plan_and_threshold_report"]["comparisons"]
        before={}
        candidate={}
        for name,(index,sql,args) in performance.QUERY_SPECS.items():
            row=source[name]
            before[name]={
                "sql":sql,"arguments":list(args),
                "result_rows":[["OK"]],
                "result_sha256":"A"
            }
            candidate[name]={
                "sql":sql,"arguments":list(args),
                "result_rows":[["NOT OK"]],
                "result_sha256":"B",
                "plan":row["indexed_plan"],
                "latency":row["indexed_latency"]
            }
        with self.assertRaises(performance.IndexProfileRejected):
            performance.compare_profiles(before,candidate)

    def test_40_benchmark_stores_no_real_event_receipts(self):
        self.assertFalse(self.snapshot["customer_data_used"])

    def test_41_sqlite_only_disposable_database(self):
        self.assertEqual(self.contract["policy"]["temporary_filename"],
                         "v24_synthetic.sqlite3")
        self.assertTrue(self.contract["policy"]["schema_version_unchanged"])

    def test_42_v23_migration_is_not_rewritten(self):
        self.assertFalse(self.snapshot["index_install_is_v23_migration"])

    def test_43_readonly_queries_protect_tenant_site_keys(self):
        for name,(_,sql,args) in performance.QUERY_SPECS.items():
            with self.subTest(query=name):
                self.assertIn("tenant_id=?",sql)
                self.assertIn("site_id=?",sql)
                self.assertEqual(args[0],performance.TENANT)

    def test_44_no_index_ddl_in_prod_version_metadata(self):
        self.assertEqual(self.snapshot["sqlite_schema_user_version"],2)

    def test_45_thresholds_are_explicit_prototype_guardrails(self):
        self.assertEqual(self.snapshot["query_thresholds_ms"],
                         {"median":80,"p95":200})


def _indexed_query_test(name):
    def run(self):
        row=self.snapshot["query_plan_and_threshold_report"]["comparisons"][name]
        self.assertTrue(row["index_chosen"])
        self.assertTrue(row["sort_avoided"])
        self.assertTrue(row["result_identical"])
        self.assertTrue(row["threshold_passed"])
        self.assertLessEqual(row["indexed_latency"]["median_ms"],80)
        self.assertLessEqual(row["indexed_latency"]["p95_ms"],200)
        self.assertGreaterEqual(row["result_count"],1)
    return run


def _index_catalog_test(name):
    def run(self):
        row=self.snapshot["candidate_indexes"]["index_details"][name]
        self.assertTrue(row["matches_spec"])
        table, keys=performance.INDEX_COLUMNS[name]
        self.assertEqual(row["table"],table)
        self.assertEqual(row["key_columns"],[list(k) for k in keys])
    return run


def _real_index_rollback_test(step):
    def run(self):
        with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as dirname:
            db=persist_v24.connect(Path(dirname)/persist_v24.NAME)
            try:
                persist_v24.bootstrap(db)
                performance.seed_benchmark(db)
                with self.assertRaisesRegex(
                        performance.IndexProfileRejected,
                        "injected_candidate_index_rollback"):
                    performance.install_indexes(db,
                                                inject_failure_after=step)
                self.assertEqual(performance._candidate_index_names(db),set())
                self.assertEqual(migrate_v23.validate_version(db,2)["version"],2)
                performance.install_indexes(db)
                self.assertEqual(len(performance._candidate_index_names(db)),4)
            finally:
                db.close()
    return run


for _name in performance.QUERY_SPECS:
    setattr(V25IndexPerformanceTests,"test_query_plan_"+_name,
            _indexed_query_test(_name))
for _name in performance.INDEX_COLUMNS:
    setattr(V25IndexPerformanceTests,"test_index_catalog_"+_name,
            _index_catalog_test(_name))
setattr(V25IndexPerformanceTests,"test_46_transactional_index_rollback",
        _real_index_rollback_test(2))


if __name__=="__main__":
    unittest.main()
