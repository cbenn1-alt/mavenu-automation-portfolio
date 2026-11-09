"""V26 synthetic tenant-scope and data-rights design regression.

Actor IDs are fabricated; the checks exercise only an application-layer
reference guard, not actual authentication, tenant authorization or RLS.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))

import isolation_v26 as iso
import migrate_v23
import persist_v24
import verify_v26


class V26IsolationDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="mavenu-v24-")
        cls.path=Path(cls.temp.name)/persist_v24.NAME
        cls.db=persist_v24.connect(cls.path)
        persist_v24.bootstrap(cls.db)
        cls.fixture=iso.seed_isolated_fixture(cls.db)
        cls.policy=iso.load_policy()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.temp.cleanup()

    def _policy_rejected(self,key,value):
        record=copy.deepcopy(self.policy)
        node=record
        parts=key.split(".")
        for part in parts[:-1]:
            node=node[part]
        node[parts[-1]]=value
        with self.assertRaises(iso.V26InvariantError):
            iso.validate_policy(record)

    def _denied(self,actor,tenant,site,op):
        with self.assertRaisesRegex(iso.ScopeDenied,"^scope_denied$"):
            iso.read_scope(self.db,actor_id=actor,tenant_id=tenant,
                           site_id=site,operation=op)

    def test_01_exact_objective_and_proof(self):
        self.assertEqual(self.policy["objective"],
                         "Document tenant boundaries and data rights")
        self.assertEqual(self.policy["required_proof"],
                         "Isolation design decision")

    def test_02_policy_is_proposed_not_ratified(self):
        iso.validate_policy(self.policy)
        self.assertEqual(self.policy["design_state"],"PROPOSED_NOT_RATIFIED")
        self.assertEqual(self.policy["production_choice"],
                         "UNDECIDED_PENDING_CUSTOMER_AND_SECURITY_REVIEW")

    def test_03_synthetic_tenant_model_proposed_only(self):
        self.assertEqual(self.policy["selected_for_synthetic_prototype"],
                         "logical_tenant_site_scoping")
        self.assertEqual(len(self.policy["design_options"]),3)

    def test_04_alternative_database_per_tenant_assessed(self):
        self.assertIn("database_per_tenant",
                      [x["key"] for x in self.policy["design_options"]])

    def test_05_alternative_schema_per_tenant_assessed(self):
        self.assertIn("schema_per_tenant",
                      [x["key"] for x in self.policy["design_options"]])

    def test_06_no_external_authentication(self):
        self.assertEqual(self.policy["trust_boundaries"]
                         ["external_actor_authentication"],"NOT_IMPLEMENTED")

    def test_07_no_real_database_row_level_security(self):
        self.assertEqual(self.policy["trust_boundaries"]
                         ["row_level_security"],"NOT_IMPLEMENTED")

    def test_08_no_authenticated_principal_identity(self):
        self.assertEqual(self.policy["trust_boundaries"]
                         ["caller_identity_provider"],"NONE")

    def test_09_uniform_scope_error_does_not_disclose_target(self):
        self._denied("SYN-ACTOR-999","SYN-TENANT-001","SYN-SITE-001",
                     "read_case_summary")
        self._denied("SYN-ACTOR-999","SYN-TENANT-999","SYN-SITE-001",
                     "read_case_summary")

    def test_10_four_tenant_site_scopes(self):
        self.assertEqual(len(iso.TENANT_SITE),4)
        self.assertEqual(self.fixture["tenant_site_scopes"],4)

    def test_11_reused_case_identifier_requires_full_scope(self):
        self.assertEqual(self.fixture["duplicate_case_001_count"],4)

    def test_12_total_synthetic_rows(self):
        self.assertEqual(self.fixture["total_rows"],38)
        self.assertEqual(self.fixture["table_counts"],iso.EXPECTED_COUNTS)

    def test_13_six_synthetic_actors(self):
        self.assertEqual(len(iso.GRANTS),6)

    def test_14_authorized_operations_read_only(self):
        self.assertEqual(iso.OPERATIONS,
                         ("read_case_summary","read_evidence_reference"))
        self.assertNotIn("export_case",iso.OPERATIONS)
        self.assertNotIn("delete_case",iso.OPERATIONS)

    def test_15_no_real_customer_data(self):
        self.assertFalse(self.fixture["real_customer_data"])
        self.assertFalse(self.fixture["authn_or_database_rls_implemented"])

    def test_16_schema_version_two_unchanged(self):
        self.assertEqual(migrate_v23.validate_version(self.db,2)["version"],2)

    def test_17_no_fk_violations(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check")
                         .fetchall(),[])

    def test_18_case_query_explicitly_binds_tenant_and_site(self):
        sql,_=iso.SCOPED_QUERIES["read_case_summary"]
        self.assertIn("WHERE tenant_id=? AND site_id=?",sql)
        self.assertEqual(sql.count("?"),2)

    def test_19_evidence_query_explicitly_binds_tenant_and_site(self):
        sql,_=iso.SCOPED_QUERIES["read_evidence_reference"]
        self.assertIn("WHERE tenant_id=? AND site_id=?",sql)
        self.assertEqual(sql.count("?"),2)

    def test_20_explicit_projections_no_star_select(self):
        for sql,_ in iso.SCOPED_QUERIES.values():
            self.assertNotIn("SELECT *",sql)
            self.assertTrue(sql.startswith("SELECT "))

    def test_21_only_fixed_lookup_tables(self):
        sql_case,_=iso.SCOPED_QUERIES["read_case_summary"]
        sql_evidence,_=iso.SCOPED_QUERIES["read_evidence_reference"]
        self.assertIn("FROM maintenance_case ",sql_case)
        self.assertIn("FROM evidence_reference ",sql_evidence)

    def test_22_unassigned_actor_denied(self):
        self._denied("SYN-ACTOR-006",iso.TENANTS[0],iso.SITES[0],
                     iso.OPERATIONS[0])

    def test_23_unknown_actor_denied(self):
        self._denied("SYN-ACTOR-900",iso.TENANTS[0],iso.SITES[0],
                     iso.OPERATIONS[0])

    def test_24_invalid_operation_denied(self):
        self._denied("SYN-ACTOR-001",iso.TENANTS[0],iso.SITES[0],
                     "write_case")

    def test_25_sql_injection_like_scope_denied(self):
        self._denied("SYN-ACTOR-001","SYN-TENANT-001 OR 1=1",
                     iso.SITES[0],iso.OPERATIONS[0])

    def test_26_non_ascii_tenant_id_denied(self):
        self._denied("SYN-ACTOR-001","SYN-TENANT-０01",
                     iso.SITES[0],iso.OPERATIONS[0])

    def test_27_missing_tenant_scope_denied(self):
        self._denied("SYN-ACTOR-001",None,
                     iso.SITES[0],iso.OPERATIONS[0])

    def test_28_unassigned_evidence_role_denied(self):
        self._denied("SYN-ACTOR-001",iso.TENANTS[0],iso.SITES[0],
                     "read_evidence_reference")

    def test_29_dual_site_cannot_cross_tenant(self):
        self._denied("SYN-ACTOR-005",iso.TENANTS[1],iso.SITES[0],
                     iso.OPERATIONS[0])

    def test_30_cross_site_does_not_infer_rights(self):
        self._denied("SYN-ACTOR-001",iso.TENANTS[0],iso.SITES[1],
                     iso.OPERATIONS[0])

    def test_31_evidence_reviewer_limited_to_own_scope(self):
        self._denied("SYN-ACTOR-002",iso.TENANTS[1],iso.SITES[1],
                     "read_evidence_reference")

    def test_32_raw_database_bypass_remains_possible(self):
        # Deliberately verifies why this prototype is NOT database RLS.
        n=self.db.execute("SELECT COUNT(*) FROM maintenance_case").fetchone()[0]
        self.assertEqual(n,12)
        self.assertFalse(self.policy["human_decision"]
                         ["production_architecture_selected"])

    def test_33_no_legal_controller_identified(self):
        self.assertFalse(self.policy["rights_position"]
                         ["actual_controller_identified"])

    def test_34_no_executed_data_license(self):
        self.assertFalse(self.policy["rights_position"]
                         ["actual_data_license_executed"])

    def test_35_retention_deletion_export_not_approved(self):
        rights=self.policy["rights_position"]
        for key in ("retention_period_approved","deletion_method_approved",
                    "export_policy_approved"):
            self.assertIs(rights[key],False)

    def test_36_subprocessor_and_cross_border_unapproved(self):
        rights=self.policy["rights_position"]
        self.assertFalse(rights["subprocessor_rights_approved"])
        self.assertFalse(rights["cross_border_transfer_approved"])

    def test_37_unexecuted_operator_reviews_not_readable(self):
        self._denied("SYN-ACTOR-003",iso.TENANTS[1],iso.SITES[0],
                     "read_source_document")

    def test_38_actual_customer_data_access_not_granted(self):
        self.assertFalse(self.policy["rights_position"]
                         ["actual_customer_data_access"])

    def test_39_complete_proposed_rights_schedule_exists(self):
        self.assertEqual(len(self.policy["rights_position"]
                             ["required_contracts"]),5)

    def test_40_policy_forbids_fake_approval(self):
        self._policy_rejected("human_decision.production_architecture_selected",
                              True)

    def test_41_policy_forbids_fake_signature(self):
        self._policy_rejected("human_decision.signature","fabricated")

    def test_42_policy_forbids_fake_data_license(self):
        self._policy_rejected("rights_position.actual_data_license_executed",
                              True)

    def test_43_policy_forbids_invented_authentication(self):
        self._policy_rejected(
            "trust_boundaries.external_actor_authentication","IMPLEMENTED")

    def test_44_policy_forbids_claiming_rls(self):
        self._policy_rejected(
            "trust_boundaries.row_level_security","IMPLEMENTED")

    def test_45_policy_forbids_grant_changes(self):
        self._policy_rejected("synthetic_actors",[])

    def test_46_policy_forbids_scope_inventory_changes(self):
        self._policy_rejected("inventory.synthetic_rows",999)

    def test_47_policy_forbids_changing_synthetic_prototype_choice(self):
        self._policy_rejected("selected_for_synthetic_prototype",
                             "database_per_tenant")

    def test_48_policy_forbids_claiming_signed_v20(self):
        self._policy_rejected("human_decision.gate_status.v20_data_signoff",
                             True)

    def test_49_policy_forbids_production_tenant_access(self):
        self._policy_rejected("human_decision.gate_status.production_customer_access",
                             True)

    def test_50_policy_requires_cross_tenant_negative_tests(self):
        self.assertTrue(self.policy["tests_required"]
                        ["cross_tenant_read_denied"])
        self.assertTrue(self.policy["tests_required"]
                        ["cross_site_read_denied"])

    def test_51_matrix_all_48_scope_operation_combinations(self):
        matrix=iso.evaluate_matrix(self.db)
        self.assertEqual(matrix["attempted_grant_combinations"],48)
        self.assertEqual(matrix["allowed_reads"],8)
        self.assertEqual(matrix["denied_reads"],40)

    def test_52_matrix_ten_malformed_probes_denied(self):
        matrix=iso.evaluate_matrix(self.db)
        self.assertEqual(matrix["malformed_or_unsupported_probes_denied"],10)

    def test_53_all_scopes_with_duplicate_case_ids(self):
        for tenant,site in iso.TENANT_SITE:
            count=self.db.execute(
                "SELECT COUNT(*) FROM maintenance_case "
                "WHERE tenant_id=? AND site_id=? AND case_id=?",
                (tenant,site,"SYN-CASE-001")
            ).fetchone()[0]
            self.assertEqual(count,1)

    def test_54_case_summary_projections_match_keys(self):
        for op,(_,cols) in iso.SCOPED_QUERIES.items():
            self.assertEqual(cols[0:3],("tenant_id","site_id","case_id"))

    def test_55_no_customer_owned_signoff_fields(self):
        decision=self.policy["human_decision"]
        for field in ("owner","security_reviewer","data_steward",
                      "legal_reviewer","approved_at_utc","signature"):
            self.assertIsNone(decision[field])

    def test_56_prior_v20_and_v10_gates_blocked(self):
        gates=self.policy["human_decision"]["gate_status"]
        self.assertFalse(gates["v20_data_signoff"])
        self.assertFalse(gates["v10_promotion"])

    def test_57_unsigned_verifier_does_not_grant_access(self):
        report=verify_v26.generate(require_prior_reports=False)
        self.assertEqual(report["technical_evidence"],"PASS")
        self.assertFalse(report["v26_isolation_decision_signed"])
        self.assertFalse(report["real_authentication_implemented"])
        self.assertFalse(report["database_row_level_security_implemented"])
        self.assertEqual(report["synthetic_isolation_results"]["matrix"]
                         ["denied_reads"],40)

    def test_58_reference_harness_remains_read_only(self):
        before=self.db.execute(
            "SELECT COUNT(*) FROM maintenance_case").fetchone()[0]
        iso.evaluate_matrix(self.db)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM maintenance_case").fetchone()[0],before)

    def test_59_customer_data_rights_reviewer_remains_unassigned(self):
        self.assertIsNone(self.policy["human_decision"]["legal_reviewer"])

    def test_60_fixed_error_code_for_unknown_operation(self):
        for op in iso.DENIED_OPERATIONS:
            self._denied("SYN-ACTOR-001",iso.TENANTS[0],iso.SITES[0],op)

    def test_61_authorized_tenant_scope_never_exceeds_grants(self):
        for actor_id,(_,grants) in iso.GRANTS.items():
            for (tenant,site),operations in grants.items():
                for op in operations:
                    rows=iso.read_scope(
                        self.db,actor_id=actor_id,
                        tenant_id=tenant,site_id=site,operation=op
                    )
                    self.assertEqual(len(rows),3)
                    self.assertTrue(all(x["tenant_id"]==tenant and
                                        x["site_id"]==site for x in rows))

    def test_62_cross_tenant_fk_violation_rejected(self):
        self.db.execute("SAVEPOINT v26_cross_tenant")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO evidence_reference VALUES (?,?,?,?,?)",
                    (iso.TENANTS[0],iso.SITES[0],"SYN-CASE-999",
                     "SYN-EV-999",0))
        finally:
            self.db.execute("ROLLBACK TO v26_cross_tenant")
            self.db.execute("RELEASE v26_cross_tenant")

    def test_63_api_not_used_for_actual_login(self):
        self.assertEqual(self.policy["trust_boundaries"]
                         ["principal_context_origin"],
                         "SYNTHETIC_SERVER_SIDE_TEST_FIXTURE_ONLY")

    def test_64_all_rights_categories_are_noncustomer(self):
        classes=self.policy["data_classes"]
        self.assertTrue(all(x["customer_ownership"]=="UNDETERMINED"
                            for x in classes))

    def test_65_cleanup_on_new_replay(self):
        evidence=iso.run_isolation_replay()
        self.assertTrue(evidence["temporary_database_deleted"])
        self.assertFalse(evidence["customer_data_used"])


def _check_actor_scope(actor, tenant, site, operation):
    def case(self):
        grants=iso.GRANTS[actor][1]
        allowed=operation in grants.get((tenant,site),())
        if allowed:
            rows=iso.read_scope(
                self.db,actor_id=actor,tenant_id=tenant,
                site_id=site,operation=operation)
            self.assertEqual(len(rows),3)
            self.assertEqual({x["tenant_id"] for x in rows},{tenant})
            self.assertEqual({x["site_id"] for x in rows},{site})
        else:
            self._denied(actor,tenant,site,operation)
    return case


def _no_write_operation(op):
    def case(self):
        self._denied("SYN-ACTOR-003",iso.TENANTS[1],iso.SITES[0],op)
    return case


for a in iso.GRANTS:
    for t,s in iso.TENANT_SITE:
        for operation in iso.OPERATIONS:
            method = ("test_scope_%s_%s_%s_%s" %
                      (a[-3:],t[-3:],s[-3:],operation))
            setattr(V26IsolationDesignTests,method,
                    _check_actor_scope(a,t,s,operation))
for operation in iso.DENIED_OPERATIONS:
    setattr(V26IsolationDesignTests,
            "test_denied_operation_"+operation,
            _no_write_operation(operation))


if __name__ == "__main__":
    unittest.main()
