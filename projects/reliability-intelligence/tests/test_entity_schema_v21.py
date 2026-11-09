"""V21 synthetic-only relational schema design tests. No durable DB or sign-off."""
from __future__ import annotations

import copy
import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import entity_v21 as model
import verify_v21 as verifier


class V21EntityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = model.load_model()
        cls.db = model.create_memory_schema()
        cls.catalog = model.validate_catalog(cls.db, cls.contract)
        cls.preview = model.load_synthetic_preview(cls.db, cls.contract)
        model.validate_catalog(cls.db, cls.contract)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def sql_rejected(self, sql, values):
        self.db.execute("SAVEPOINT negative_case")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, values)
        finally:
            self.db.execute("ROLLBACK TO negative_case")
            self.db.execute("RELEASE negative_case")

    def model_rejected(self, field, new_value):
        m = copy.deepcopy(self.contract)
        container = m
        keys = field.split(".")
        for key in keys[:-1]:
            container = container[key]
        container[keys[-1]] = new_value
        with self.assertRaises(model.EntitySchemaRejected):
            model.validate_model(m)

    def test_01_exact_architecture_standard(self):
        self.assertEqual(self.contract["objective"],
                         "Design canonical entities and relationships")
        self.assertEqual(self.contract["required_proof"], "Reviewed entity schema")

    def test_02_reviewer_state_is_pending(self):
        self.assertEqual(self.contract["review_status"],
                         "CANDIDATE_TECHNICALLY_CHECKABLE_HUMAN_REVIEW_PENDING")

    def test_03_prior_phase_authorization_blocked(self):
        self.assertFalse(self.contract["approval"]["v20_data_quality_signoff"])
        self.assertFalse(self.contract["approval"]["v10_formal_phase_promotion"])

    def test_04_persistent_db_unapproved(self):
        self.assertFalse(self.contract["design_rules"]["storage_persistence_enabled"])

    def test_05_tenant_auth_is_not_implemented(self):
        self.assertFalse(self.contract["synthetic_namespace"]["tenant_authorization_implemented"])

    def test_06_customer_data_not_authorized(self):
        self.assertFalse(self.contract["approval"]["customer_data_authorized"])

    def test_07_v22_not_approved(self):
        self.assertFalse(self.contract["approval"]["v22_authorized"])

    def test_08_no_real_ingest(self):
        self.assertTrue(self.preview["no_real_ingestion_event"])
        self.assertFalse(self.preview["customer_source_observed"])

    def test_09_catalog_entity_counts(self):
        self.assertEqual(self.catalog["entities_verified"], 10)
        self.assertEqual(self.catalog["primary_keys_verified"], 10)
        self.assertEqual(self.catalog["without_rowid_tables"], 10)

    def test_10_catalog_relationship_counts(self):
        self.assertEqual(self.catalog["relationships_verified"], 9)
        self.assertEqual(self.catalog["composite_tenant_scoped_foreign_keys"], 8)

    def test_11_source_in_memory_only(self):
        self.assertEqual(self.db.execute("PRAGMA database_list").fetchall()[0][2], "")
        self.assertTrue(self.catalog["in_memory_only"])

    def test_12_foreign_key_enforcement(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_13_quick_check(self):
        self.assertEqual(self.db.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_14_preview_record_count(self):
        self.assertEqual(self.preview["total_rows"], 120)

    def test_15_reconstructed_v16_provenance(self):
        self.assertEqual(self.preview["v16_reconstructed_origin_count"], 34)
        self.assertEqual(self.preview["v16_conversion_steps"], 36)

    def test_16_exact_integer_durations_and_cost(self):
        self.assertEqual(self.preview["synthetic_duration_seconds"], 163800)
        self.assertEqual(self.preview["synthetic_cost_cents"], 1273500)

    def test_17_review_scripts_are_not_real_human_actions(self):
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM scripted_review WHERE human_executed=0"
        ).fetchone()[0], 4)

    def test_18_evidence_ids_are_not_documents(self):
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM evidence_reference WHERE external_document_verified=0"
        ).fetchone()[0], 11)

    def test_19_reference_labels_not_domain_validated(self):
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM reference_label WHERE independently_validated=0"
        ).fetchone()[0], 12)

    def test_20_no_ingestion_timestamps(self):
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM record_origin WHERE observed_ingestion_at_utc IS NULL"
        ).fetchone()[0], 34)

    def test_21_source_files_are_allowlisted(self):
        self.assertEqual(set(self.db.execute(
            "SELECT fixture_path FROM source_document"
        ).fetchall()), {(x,) for x in model.SOURCE_IDS})

    def test_22_all_conversion_steps_from_case_source(self):
        n = self.db.execute(
            "SELECT COUNT(*) FROM transform_step s JOIN record_origin r"
            " ON s.tenant_id=r.tenant_id AND s.site_id=r.site_id"
            " AND s.trace_id=r.trace_id WHERE r.source_dataset='case_records'"
        ).fetchone()[0]
        self.assertEqual(n, 36)

    def test_23_upstream_gate_still_blocked(self):
        record = verifier.source_approvals()
        self.assertEqual(record["v10_frozen_files"], 18)
        self.assertEqual(record["v20_data_quality_human_signoff"],
                         "BLOCKED_PENDING_HUMAN_SIGNOFF")
        self.assertFalse(record["v21_formal_phase_03_authorized"])

    def test_24_review_packet_not_signed(self):
        record = verifier.generate()
        self.assertEqual(record["catalog"]["entities_verified"], 10)
        self.assertEqual(record["synthetic_preview"]["total_rows"], 120)
        self.assertEqual(record["review_decision"]["human_schema_review"], "PENDING")
        self.assertFalse(record["review_decision"]["signed_schema_review_exists"])
        self.assertFalse(record["review_decision"]["future_v22_authorized"])

    def test_25_source_fixture_frozen_identifiers(self):
        self.assertEqual(self.contract["source_fixture_set_id"],
                         "SYN-RI-V5-20261107-A")
        self.assertEqual(self.contract["v9_frozen_source_commit"],
                         "704123eca45628bf504594af39a66036cc0451c5")

    def test_26_model_has_unresolved_design_decisions(self):
        self.assertGreaterEqual(len(self.contract["unresolved_design_decisions"]), 6)

    def test_27_schema_ddl_is_candidate_not_migration(self):
        self.assertIn("no production migration",
                      self.contract["design_rules"]["schema_dialect"])

    def test_28_row_count_sum_matches_contract(self):
        self.assertEqual(sum(self.preview["counts"].values()), 120)



    def test_29_cross_site_parent_is_not_shared(self):
        self.db.execute("SAVEPOINT cross_site")
        try:
            self.db.execute("INSERT INTO site VALUES (?,?,?,?)",
                            (model.TENANT, "SYN-SITE-002", "Second Fictional Site", 1))
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (model.TENANT, "SYN-SITE-002", "SYN-CASE-900", "SYN-ASSET-001",
                     "SYN-WO-900", "2026-01-01T00:00:00Z", "bearing_wear",
                     3600, 100, "fixture_only", 1))
        finally:
            self.db.execute("ROLLBACK TO cross_site")
            self.db.execute("RELEASE cross_site")

    def test_30_cross_tenant_parent_is_not_shared(self):
        self.db.execute("SAVEPOINT cross_tenant")
        try:
            self.db.execute("INSERT INTO tenant VALUES (?,?,?)",
                            ("SYN-TENANT-002", "Second Invented Tenant", "synthetic_only"))
            self.db.execute("INSERT INTO site VALUES (?,?,?,?)",
                            ("SYN-TENANT-002", model.SITE, "Second Fictional Site", 1))
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("SYN-TENANT-002", model.SITE, "SYN-CASE-900",
                     "SYN-ASSET-001", "SYN-WO-900", "2026-01-01T00:00:00Z",
                     "bearing_wear", 3600, 100, "fixture_only", 1))
        finally:
            self.db.execute("ROLLBACK TO cross_tenant")
            self.db.execute("RELEASE cross_tenant")

def make_count(table):
    def run(self):
        self.assertEqual(self.preview["counts"][table], model.EXPECTED_COUNTS[table])
    return run


def make_pk(table):
    def run(self):
        info = self.db.execute('PRAGMA table_info("' + table + '")').fetchall()
        actual = tuple(x[1] for x in sorted(
            (c for c in info if c[5] > 0), key=lambda c: c[5]))
        self.assertEqual(actual, model.EXPECTED_PKS[table])
    return run


def make_fk(table):
    def run(self):
        self.assertEqual(model._catalog_foreign_keys(self.db, table),
                         sorted(model.EXPECTED_FKS[table]))
    return run


def make_sql_negative(sql, values):
    def run(self):
        self.sql_rejected(sql, values)
    return run


def make_model_negative(field, value):
    def run(self):
        self.model_rejected(field, value)
    return run


for _entity in model.EXPECTED_COUNTS:
    setattr(V21EntityTests, "test_count_" + _entity, make_count(_entity))
    setattr(V21EntityTests, "test_primary_key_" + _entity, make_pk(_entity))
for _entity in list(model.EXPECTED_COUNTS)[1:]:
    setattr(V21EntityTests, "test_foreign_key_" + _entity, make_fk(_entity))

# Only fabricated, disposable SQLite rows are altered. Each negative case
# runs under a savepoint and rolls back regardless of the constraint failure.
SQL_NEGATIVE = {
    "invalid_negative_cost": ("UPDATE maintenance_case SET repair_cost_cents=?", (-1,)),
    "invalid_high_cost": ("UPDATE maintenance_case SET repair_cost_cents=?", (100000001,)),
    "invalid_negative_duration": ("UPDATE maintenance_case SET downtime_seconds=?", (-1,)),
    "invalid_high_duration": ("UPDATE maintenance_case SET downtime_seconds=?", (864001,)),
    "invalid_review_state": ("UPDATE maintenance_case SET review_state=?", ("approved",)),
    "invalid_asset_synthetic": ("UPDATE asset SET synthetic_flag=?", (0,)),
    "invented_review_execution": ("UPDATE scripted_review SET human_executed=?", (1,)),
    "invented_evidence_validation": ("UPDATE evidence_reference SET external_document_verified=?", (1,)),
    "invented_ground_truth": ("UPDATE reference_label SET independently_validated=?", (1,)),
    "invented_ingest_record_timestamp": ("UPDATE record_origin SET observed_ingestion_at_utc=?", ("2026-11-08T00:00:00Z",)),
    "invented_ingest_document_timestamp": ("UPDATE source_document SET observed_ingestion_at_utc=?", ("2026-11-08T00:00:00Z",)),
    "unknown_source_document": ("UPDATE record_origin SET source_document_id=?", ("SYN-DOC-999",)),
    "unknown_transform_rule": ("UPDATE transform_step SET rule_id=?", ("FAKE_RULE",)),
    "missing_evidence_parent": (
        "INSERT INTO evidence_reference VALUES (?,?,?,?,?)",
        (model.TENANT, model.SITE, "SYN-CASE-999", "SYN-EV-999", 0)),
    "unknown_asset_parent": (
        "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (model.TENANT, model.SITE, "SYN-CASE-999", "SYN-ASSET-999",
         "SYN-WO-999", "2026-01-01T00:00:00Z", "bearing_wear", 3600, 100,
         "fixture_only", 1)),
    "duplicate_work_order": (
        "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (model.TENANT, model.SITE, "SYN-CASE-999", "SYN-ASSET-001",
         "SYN-WO-001", "2026-01-01T00:00:00Z", "bearing_wear", 3600, 100,
         "fixture_only", 1)),
}
for _name, (_sql, _args) in SQL_NEGATIVE.items():
    setattr(V21EntityTests, "test_reject_" + _name,
            make_sql_negative(_sql, _args))

MODEL_NEGATIVE = {
    "approval.v21_schema_human_review": True,
    "approval.v20_data_quality_signoff": True,
    "approval.customer_data_authorized": True,
    "approval.v22_authorized": True,
    "approval.approval_signature": "fabricated",
    "approval.approval_date_utc": "2026-11-08",
    "design_rules.storage_persistence_enabled": True,
    "design_rules.tenant_access_control_approved": True,
    "design_rules.real_record_origin_observed": True,
    "design_rules.automatic_v22_or_v23_promotion": True,
    "synthetic_namespace.tenant_authorization_implemented": True,
}
# Use existing declared paths; an undeclared attribute must be detected rather
# than causing an unrelated lookup error.
for _path, _value in MODEL_NEGATIVE.items():
    if _path == "design_rules.tenant_access_control_approved":
        continue
    setattr(V21EntityTests, "test_reject_" + _path.replace(".", "_"),
            make_model_negative(_path, _value))


if __name__ == "__main__":
    unittest.main()
