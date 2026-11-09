"""V22 identity/reference correctness. All records are fabricated and in memory.

Tests do not treat CI, SQLite foreign keys or human-like synthetic reviewer IDs
as real customer access control, domain taxonomy acceptance or owner approval.
"""

from __future__ import annotations

import copy
import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

import entity_v21
import identity_v22 as identity
import lineage_v16
import verify_v22


class V22IdentityReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = identity.policy()
        cls.model = entity_v21.load_model()
        cls.docs, cls.source_hashes = lineage_v16.load_source_documents()
        cls.source_result = identity.validate_sources(cls.docs)
        cls.db = entity_v21.create_memory_schema()
        cls.catalog = entity_v21.validate_catalog(cls.db, cls.model)
        cls.preview = entity_v21.load_synthetic_preview(cls.db, cls.model)
        cls.sql_keys = identity.validate_sql_keys(cls.db)
        cls.negatives = {
            x["id"]: x["expected_error"] for x in cls.cfg["adverse_cases"]
        }

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_01_exact_v22_architecture_objective(self):
        self.assertEqual(self.cfg["objective"],
                         "Define identity and reference-data rules")
        self.assertEqual(self.cfg["required_proof"],
                         "Uniqueness and link tests")

    def test_02_policy_is_candidate_not_approved(self):
        identity.validate_policy(self.cfg)
        self.assertEqual(self.cfg["review_status"],
                         "CANDIDATE_IDENTITY_POLICY_HUMAN_REVIEW_PENDING")

    def test_03_v10_v20_v21_approval_blocked(self):
        for field in ("v10_formal_promotion", "v20_data_quality_signoff",
                      "v21_schema_review", "v22_identity_review"):
            self.assertIs(self.cfg["approvals"][field], False)

    def test_04_v23_migrations_are_not_approved(self):
        self.assertIs(self.cfg["approvals"]["v23_migration_approved"], False)
        self.assertIs(self.cfg["scope"]["persisted_database"], False)

    def test_05_no_real_customer_tenant_id(self):
        self.assertFalse(self.cfg["scope"]["real_customer_identities"])
        self.assertFalse(self.cfg["scope"]["authorization_enforced"])

    def test_06_scope_is_exact_synthetic_namespace(self):
        self.assertEqual(self.cfg["scope"]["tenant_id"], entity_v21.TENANT)
        self.assertEqual(self.cfg["scope"]["site_id"], entity_v21.SITE)

    def test_07_no_silent_case_or_unicode_normalization(self):
        for name in ("syn-case-001", "SYN-CASE-001 ", "SYN-CASE-０01",
                     "SYN-CASE-001\n"):
            with self.subTest(value=repr(name)):
                with self.assertRaisesRegex(
                        identity.IdentityRejected, "^noncanonical_case_id$"):
                    identity.canonical("case_id", name)

    def test_08_strict_ascii_identity_format(self):
        self.assertEqual(identity.canonical("case_id", "SYN-CASE-001"),
                         "SYN-CASE-001")
        self.assertEqual(identity.canonical("tenant_id", entity_v21.TENANT),
                         entity_v21.TENANT)

    def test_09_case_id_nonstring_rejected(self):
        with self.assertRaises(identity.IdentityRejected):
            identity.canonical("case_id", 101)

    def test_10_unknown_identifier_kind_rejected(self):
        with self.assertRaises(identity.IdentityRejected):
            identity.canonical("real_customer_id", "CUSTOMER-001")

    def test_11_unknown_reference_category_rejected(self):
        with self.assertRaises(identity.IdentityRejected):
            identity.reference("private_personnel", "Alice")

    def test_12_reference_values_are_exact_canonical_tokens(self):
        self.assertEqual(identity.reference("failure_code", "bearing_wear"),
                         "bearing_wear")
        with self.assertRaises(identity.IdentityRejected):
            identity.reference("failure_code", "Bearing Wear")

    def test_13_ten_reference_data_categories(self):
        self.assertEqual(len(identity.REFERENCE), 10)

    def test_14_nine_identity_formats(self):
        self.assertEqual(len(identity.PATTERNS), 9)

    def test_15_thirteen_uniqueness_rules(self):
        self.assertEqual(self.sql_keys["uniqueness_views_checked"], 13)
        self.assertEqual(self.sql_keys["uniqueness_violations"], 0)

    def test_16_nine_foreign_key_links(self):
        self.assertEqual(self.sql_keys["foreign_key_links_checked"], 9)
        self.assertEqual(self.sql_keys["unresolved_links"], 0)

    def test_17_no_real_user_permissions_implemented(self):
        self.assertIs(self.sql_keys["tenant_authentication_implemented"], False)

    def test_18_sqlite_in_memory_only(self):
        self.assertTrue(self.sql_keys["database_is_ephemeral"])
        self.assertTrue(self.preview["preview_database_persisted"] is False)

    def test_19_records_120_from_previous_schema(self):
        self.assertEqual(self.preview["total_rows"], 120)
        self.assertEqual(self.catalog["entities_verified"], 10)

    def test_20_all_thirty_four_sources_are_fabricated(self):
        self.assertEqual(self.preview["v16_reconstructed_origin_count"], 34)
        self.assertFalse(self.source_result["real_customer_identity_resolved"])

    def test_21_reference_counts(self):
        self.assertEqual(self.source_result["assets"], 6)
        self.assertEqual(self.source_result["cases"], 12)
        self.assertEqual(self.source_result["unique_work_order_refs"], 12)
        self.assertEqual(self.source_result["evidence_references"], 11)
        self.assertEqual(self.source_result["scripted_review_keys"], 4)
        self.assertEqual(self.source_result["authored_label_keys"], 12)

    def test_22_signed_reviewers_are_absent(self):
        a = self.cfg["approvals"]
        for key in ("named_data_architect", "named_data_steward",
                    "named_security_reviewer", "review_date_utc", "signature"):
            self.assertIsNone(a[key])

    def test_23_reject_fabricated_review_signature(self):
        changed = copy.deepcopy(self.cfg)
        changed["approvals"]["signature"] = "fake"
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_24_reject_fake_customer_source_approval(self):
        changed = copy.deepcopy(self.cfg)
        changed["approvals"]["customer_data_authorized"] = True
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_25_reject_identity_policy_scope_extension(self):
        changed = copy.deepcopy(self.cfg)
        changed["scope"]["authorization_enforced"] = True
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_26_reject_altered_identity_pattern(self):
        changed = copy.deepcopy(self.cfg)
        changed["id_patterns"]["case_id"] = "[A-Za-z0-9]+"
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_27_reject_reference_enum_extension(self):
        changed = copy.deepcopy(self.cfg)
        changed["reference_values"]["failure_code"].append("real_fault")
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_28_reject_dropped_uniqueness_key(self):
        changed = copy.deepcopy(self.cfg)
        changed["uniqueness_keys"].pop()
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_29_reject_tenant_scope_changed_on_parent_link(self):
        changed = copy.deepcopy(self.cfg)
        changed["foreign_key_links"][2]["scope"] = ["asset_id"]
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_30_reject_negative_test_suite_tampering(self):
        changed = copy.deepcopy(self.cfg)
        changed["adverse_cases"][0]["expected_error"] = "accepted"
        with self.assertRaises(identity.IdentityRejected):
            identity.validate_policy(changed)

    def test_31_fixed_negative_suite_all_cases_rejected(self):
        result = identity.exercise_cases(self.cfg, self.docs)
        self.assertEqual(result["adverse_cases_rejected"], 25)
        self.assertTrue(result["source_documents_unchanged"])
        self.assertFalse(result["customer_data"])

    def test_32_fixed_negative_suite_replay_is_identical(self):
        first = identity.exercise_cases(self.cfg, self.docs)
        second = identity.exercise_cases(self.cfg, self.docs)
        self.assertEqual(first, second)

    def test_33_mutations_do_not_change_original_sources(self):
        orig = copy.deepcopy(self.docs)
        identity.exercise_cases(self.cfg, self.docs)
        self.assertEqual(self.docs, orig)

    def test_34_bad_sql_foreign_key_parent_rejected(self):
        self.db.execute("SAVEPOINT v22_fk")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO evidence_reference VALUES (?,?,?,?,?)",
                    (entity_v21.TENANT, entity_v21.SITE,
                     "SYN-CASE-999", "SYN-EV-999", 0))
        finally:
            self.db.execute("ROLLBACK TO v22_fk")
            self.db.execute("RELEASE v22_fk")

    def test_35_cross_tenant_record_reference_cannot_be_linked(self):
        self.db.execute("SAVEPOINT v22_cross_tenant")
        try:
            self.db.execute(
                "INSERT INTO tenant VALUES (?,?,?)",
                ("SYN-TENANT-002", "Second Fabricated Tenant", "synthetic_only"))
            self.db.execute(
                "INSERT INTO site VALUES (?,?,?,?)",
                ("SYN-TENANT-002", entity_v21.SITE,
                 "Second Fictional Site", 1))
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("SYN-TENANT-002", entity_v21.SITE,
                     "SYN-CASE-900", "SYN-ASSET-001", "SYN-WO-900",
                     "2026-01-01T00:00:00Z", "bearing_wear",
                     3600, 100, "fixture_only", 1))
        finally:
            self.db.execute("ROLLBACK TO v22_cross_tenant")
            self.db.execute("RELEASE v22_cross_tenant")

    def test_36_human_review_still_pending_in_report(self):
        result = verify_v22.generate()
        self.assertEqual(result["result"],
                         "synthetic_identity_links_verified_owner_review_pending")
        self.assertEqual(result["v20_signoff"],
                         "BLOCKED_PENDING_HUMAN_SIGNOFF")
        self.assertEqual(result["v22_human_identity_review"], "PENDING")
        self.assertFalse(result["customer_data_authorized"])
        self.assertFalse(result["v23_formal_migration_approved"])
        self.assertEqual(result["adversarial_comparisons"]["adverse_cases_rejected"], 25)


def _generated_adverse(name, expected):
    def run(self):
        changed = copy.deepcopy(self.docs)
        identity._mutate(name, changed)
        with self.assertRaisesRegex(
                identity.IdentityRejected, "^" + expected + "$"):
            identity.validate_sources(changed)
    return run


def _generated_identity(kind, pattern):
    def run(self):
        self.assertEqual(self.cfg["id_patterns"][kind], pattern)
        with self.assertRaises(identity.IdentityRejected):
            identity.canonical(kind, "Real-ID")
    return run


def _generated_reference(kind, values):
    def run(self):
        self.assertEqual(self.cfg["reference_values"][kind], values)
        for v in values:
            self.assertEqual(identity.reference(kind, v), v)
    return run


def _generated_unique(name, table, columns):
    def run(self):
        self.assertEqual(self.sql_keys["duplicates_by_key"][name], 0)
        self.assertEqual(next(x["fields"] for x in
                             self.cfg["uniqueness_keys"] if x["name"] == name),
                         list(columns))
    return run


def _generated_link(name, parent, columns):
    def run(self):
        self.assertEqual(self.sql_keys["unresolved_by_child"][name], 0)
        self.assertEqual(next(x for x in self.cfg["foreign_key_links"]
                             if x["child"] == name)["scope"], list(columns))
    return run


for _name, _expected in identity.MUTATIONS.items():
    setattr(V22IdentityReferenceTests, "test_adverse_" + _name,
            _generated_adverse(_name, _expected))
for _kind, _pattern in identity.PATTERNS.items():
    setattr(V22IdentityReferenceTests, "test_pattern_" + _kind,
            _generated_identity(_kind, _pattern))
for _kind, _values in identity.REFERENCE.items():
    setattr(V22IdentityReferenceTests, "test_reference_" + _kind,
            _generated_reference(_kind, _values))
for _key, (_table, _columns) in identity.UNIQUE.items():
    setattr(V22IdentityReferenceTests, "test_unique_" + _key,
            _generated_unique(_key, _table, _columns))
for _name, (_parent, _columns) in identity.LINKS.items():
    setattr(V22IdentityReferenceTests, "test_link_" + _name,
            _generated_link(_name, _parent, _columns))


if __name__ == "__main__":
    unittest.main()
