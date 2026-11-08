"""V16 synthetic provenance and transformation trace regression tests.

The evidence reconstructs source locators from committed fictional data.
These tests must not be interpreted as observed ingestion events, signed
custody logs, or authorization to touch a real customer's CMMS/OT assets.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import lineage_v16 as lin
import verify_v16 as verify
import normalize_v15 as norm


class V16LineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = lin.load_policy()
        cls.source, cls.hashes = lin.load_source_documents()
        cls.trace = lin.reconstruct_trace(cls.policy, cls.source, cls.hashes)
        cls.validation = lin.validate_trace(cls.trace, cls.policy, cls.source, cls.hashes)
        cls.sample = lin.select_sample(cls.trace, cls.policy)
        cls.by_id = {(x["origin"]["source_dataset"], x["origin"]["source_record_id"]): x
                     for x in cls.trace["record_traces"]}

    def modified_trace(self):
        return copy.deepcopy(self.trace)

    def invalid(self, record, error):
        with self.assertRaisesRegex(lin.LineageRejected, "^" + error + "$"):
            lin.validate_trace(record, self.policy, self.source, self.hashes)

    def test_01_exact_objective_and_proof(self):
        self.assertEqual(self.policy["objective"],
                         "Capture ingestion origin and transform lineage")
        self.assertEqual(self.policy["required_proof"], "Record-level trace sample")

    def test_02_technical_scope_is_reconstructed_and_synthetic(self):
        self.assertEqual(self.trace["origin_method"],
                         "reconstructed_from_committed_synthetic_files")
        self.assertFalse(self.trace["observed_ingest_event"])
        self.assertFalse(self.trace["customer_data_ingested"])
        self.assertEqual(self.trace["data_classification"], "fabricated_non_personal")

    def test_03_source_file_allowlist_is_exact(self):
        self.assertEqual(tuple(self.policy["source_allowlist"]), lin.SOURCE_FILES)
        self.assertEqual(len(self.hashes), 3)

    def test_04_all_thirty_four_records_traced(self):
        self.assertEqual(self.trace["record_count"], 34)
        self.assertEqual(self.validation["records_traced"], 34)
        self.assertEqual(len(self.trace["record_traces"]), 34)

    def test_05_twelve_cases_have_thirty_six_steps(self):
        self.assertEqual(self.trace["transform_step_count"], 36)
        self.assertEqual(self.validation["transformations_traced"], 36)
        self.assertEqual(self.trace["pass_through_count"], 22)

    def test_06_five_record_sample_has_six_transform_steps(self):
        self.assertEqual(len(self.sample), 5)
        self.assertEqual(sum(len(x["transformations"]) for x in self.sample), 6)
        self.assertEqual(
            [(x["origin"]["source_dataset"], x["origin"]["source_record_id"])
             for x in self.sample], list(lin.EXPECTED_SAMPLE))

    def test_07_every_row_locator_points_to_a_real_fabricated_row(self):
        for item in self.trace["record_traces"]:
            with self.subTest(trace_id=item["trace_id"]):
                origin = item["origin"]
                pointer, index = origin["json_pointer"].lstrip("/").split("/")
                source_row = self.source[origin["source_file"]][pointer][int(index)]
                self.assertEqual(origin["source_record_sha256"],
                                 lin.sha256_object(source_row))
                self.assertEqual(source_row[origin["source_identity_field"]],
                                 origin["source_record_id"])

    def test_08_original_file_checksums_match_raw_bytes(self):
        for file, digest in self.hashes.items():
            with self.subTest(file=file):
                self.assertEqual(
                    lin.sha256_bytes((PROJECT / file).read_bytes()), digest)

    def test_09_trace_checksum_matches_complete_ordered_records(self):
        self.assertEqual(self.trace["trace_batch_sha256"],
                         lin.sha256_object(self.trace["record_traces"]))

    def test_10_rebuild_is_deterministic(self):
        other = lin.reconstruct_trace(self.policy, self.source, self.hashes)
        self.assertEqual(self.trace, other)
        self.assertEqual(lin.sha256_object(self.trace), lin.sha256_object(other))

    def test_11_source_documents_still_unmodified(self):
        before = lin.sha256_object(self.source)
        lin.reconstruct_trace(self.policy, self.source, self.hashes)
        self.assertEqual(lin.sha256_object(self.source), before)

    def test_12_source_is_frozen_under_v10(self):
        frozen = verify.verify_v10.verify_freeze(
            verify.verify_v10.read_json(verify.verify_v10.BASELINE))
        self.assertEqual(frozen["frozen_files_verified"], 18)

    def test_13_v10_approval_is_not_fabricated(self):
        decision = verify.verify_v11.read_json(verify.verify_v11.DECISION_PATH)
        self.assertFalse(decision["formal_phase_promotion_authorized"])
        self.assertEqual(decision["recommended_promotion_decision"], "BLOCKED")

    def test_14_v16_approval_remains_unsigned(self):
        fields = self.policy["approval"]
        for key in ("customer_data_authorized", "v10_formal_promotion_authorized",
                    "v11_source_dictionary_approved", "v12_schema_approved",
                    "v16_lineage_owner_approved", "production_integration_authorized",
                    "ot_writes_permitted"):
            self.assertFalse(fields[key])
        self.assertIsNone(fields["approval_signature"])

    def test_15_approval_rejects_customer_provenance_claim(self):
        changed = copy.deepcopy(self.policy)
        changed["trace_rules"]["real_source_provenance_established"] = True
        with self.assertRaises(lin.LineageRejected):
            lin.validate_policy(changed)

    def test_16_approval_rejects_invented_ingestion_timestamp(self):
        changed = copy.deepcopy(self.policy)
        changed["trace_rules"]["record_ingested_at_utc"] = "2026-01-01T00:00:00Z"
        with self.assertRaises(lin.LineageRejected):
            lin.validate_policy(changed)

    def test_17_approval_rejects_invented_reviewer_signature(self):
        changed = copy.deepcopy(self.policy)
        changed["approval"]["approval_signature"] = "fabricated approver"
        with self.assertRaises(lin.LineageRejected):
            lin.validate_policy(changed)

    def test_18_unapproved_source_file_is_rejected(self):
        changed = copy.deepcopy(self.policy)
        changed["source_allowlist"].append("fixtures/customer_export.csv")
        with self.assertRaises(lin.LineageRejected):
            lin.validate_policy(changed)

    def test_19_unapproved_transform_rule_is_rejected(self):
        changed = copy.deepcopy(self.policy)
        changed["normalization_steps"][0]["rule_id"] = "UNKNOWN"
        with self.assertRaises(lin.LineageRejected):
            lin.validate_policy(changed)

    def test_20_source_bytes_incorrectly_hashed_are_detected(self):
        changed = self.modified_trace()
        changed["source_file_sha256"]["fixtures/cases.json"] = "0" * 64
        self.invalid(changed, "source_file_digest_mismatch")

    def test_21_trace_origin_pointer_tampering_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["origin"]["json_pointer"] = "/records/999"
        self.invalid(changed, "origin_locator_mismatch")

    def test_22_trace_origin_source_file_tampering_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["origin"]["source_file"] = "customer/workorders.json"
        self.invalid(changed, "origin_locator_mismatch")

    def test_23_trace_source_record_hash_tampering_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["source_record_sha256"] = "0" * 64
        self.invalid(changed, "source_record_digest_mismatch")

    def test_24_trace_origin_file_digest_tampering_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["origin"]["source_file_sha256"] = "0" * 64
        self.invalid(changed, "origin_locator_mismatch")

    def test_25_trace_identity_mutation_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["trace_id"] = "OTHER"
        self.invalid(changed, "trace_id_mismatch")

    def test_26_duplicate_trace_identity_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][1] = copy.deepcopy(changed["record_traces"][0])
        self.invalid(changed, "duplicate_trace_identity")

    def test_27_missing_trace_record_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"].pop()
        self.invalid(changed, "trace_coverage_mismatch")

    def test_28_tampered_normalized_record_rejected(self):
        changed = self.modified_trace()
        row = next(x for x in changed["record_traces"]
                   if x["origin"]["source_dataset"] == "case_records")
        row["normalized_record"]["repair_cost_usd"] = "123456.00"
        self.invalid(changed, "normalized_value_mismatch")

    def test_29_tampered_normalized_record_digest_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["normalized_record_sha256"] = "0" * 64
        self.invalid(changed, "normalized_record_digest_mismatch")

    def test_30_tampered_batch_digest_rejected(self):
        changed = self.modified_trace()
        changed["trace_batch_sha256"] = "0" * 64
        self.invalid(changed, "trace_batch_digest_mismatch")

    def test_31_tampered_trace_order_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"] = list(reversed(changed["record_traces"]))
        self.invalid(changed, "trace_record_order_mismatch")

    def test_32_deleted_transform_step_rejected(self):
        changed = self.modified_trace()
        row = next(x for x in changed["record_traces"]
                   if x["origin"]["source_dataset"] == "case_records")
        row["transformations"].pop()
        self.invalid(changed, "transform_step_coverage_mismatch")

    def test_33_tampered_transform_rule_rejected(self):
        changed = self.modified_trace()
        row = next(x for x in changed["record_traces"]
                   if x["origin"]["source_dataset"] == "case_records")
        row["transformations"][0]["rule_id"] = "MADE_UP_CONVERTER"
        self.invalid(changed, "transform_step_mismatch")

    def test_34_tampered_transform_value_hash_rejected(self):
        changed = self.modified_trace()
        row = next(x for x in changed["record_traces"]
                   if x["origin"]["source_dataset"] == "case_records")
        row["transformations"][1]["source_value_sha256"] = "0" * 64
        self.invalid(changed, "transform_step_mismatch")

    def test_35_false_record_ingest_timestamp_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"][0]["origin"]["observed_ingestion_at_utc"] = "now"
        self.invalid(changed, "origin_locator_mismatch")

    def test_36_unobserved_ingest_misrepresented_rejected(self):
        changed = self.modified_trace()
        changed["observed_ingest_event"] = True
        self.invalid(changed, "false_lineage_origin_claim")

    def test_37_unknown_dataset_in_source_rejected(self):
        changed_docs = copy.deepcopy(self.source)
        changed_docs["fixtures/customer.json"] = {"records": []}
        with self.assertRaisesRegex(lin.LineageRejected, "unexpected_lineage_source_set"):
            lin.reconstruct_trace(self.policy, changed_docs, self.hashes)

    def test_38_empty_source_inventory_rejected(self):
        changed_docs = copy.deepcopy(self.source)
        changed_docs["fixtures/cases.json"]["assets"] = []
        with self.assertRaisesRegex(lin.LineageRejected, "lineage_source_row_count"):
            lin.reconstruct_trace(self.policy, changed_docs, self.hashes)

    def test_39_sample_missing_record_rejected(self):
        changed = self.modified_trace()
        changed["record_traces"] = [
            x for x in changed["record_traces"]
            if not (x["origin"]["source_dataset"] == "case_records" and
                    x["origin"]["source_record_id"] == "SYN-CASE-009")
        ]
        with self.assertRaisesRegex(lin.LineageRejected, "sample_trace_record_missing"):
            lin.select_sample(changed, self.policy)

    def test_40_record_level_trace_and_sample_consistent(self):
        report = verify.generate_proof()
        self.assertEqual(report["source_records"], 34)
        self.assertEqual(report["transforms_replayed"], 36)
        self.assertEqual(report["sample_record_count"], 5)
        self.assertEqual(report["sample_transform_count"], 6)
        self.assertEqual(report["trace_batch_sha256"], self.trace["trace_batch_sha256"])
        self.assertFalse(report["actual_ingest_event_observed"])
        self.assertFalse(report["v16_human_approved"])

    def test_41_case_timestamp_exactly_matches_v15(self):
        case = self.by_id[("case_records", "SYN-CASE-001")]
        self.assertEqual(case["normalized_record"]["occurred_at_utc"],
                         norm.normalize_timestamp("2026-01-05T10:00:00Z", "en-US"))

    def test_42_case_money_uses_decimal_2_places(self):
        case = self.by_id[("case_records", "SYN-CASE-001")]
        self.assertEqual(case["normalized_record"]["repair_cost_usd"], "860.00")

    def test_43_case_duration_does_not_change_semantics(self):
        case = self.by_id[("case_records", "SYN-CASE-001")]
        self.assertEqual(case["normalized_record"]["downtime_hours"], "2.5")

    def test_44_pass_through_keeps_original_data_type(self):
        item = self.by_id[("asset_records", "SYN-ASSET-001")]
        source = self.source["fixtures/cases.json"]["assets"][0]
        self.assertEqual(item["normalized_record"], source)
        self.assertEqual(item["transformations"], [])

    def test_45_trace_uses_explicit_proposed_origin_not_customer(self):
        for row in self.trace["record_traces"]:
            self.assertEqual(row["origin"]["kind"],
                             "committed_synthetic_fixture_reconstruction")
            self.assertIsNone(row["origin"]["observed_ingestion_at_utc"])
            self.assertFalse(row["origin"]["customer_source_observed"])


def _make_source_record_test(dataset, file, pointer, row_id):
    def check(self):
        item = self.by_id[(dataset, row_id)]
        source_doc = self.source[file]
        origin = item["origin"]
        self.assertEqual(origin["source_record_id"], row_id)
        self.assertEqual(item["source_record_sha256"],
                         lin.sha256_object(source_doc[pointer][origin["row_index"]]))
        self.assertEqual(origin["source_file_sha256"], self.hashes[file])
    return check


def _make_transform_step_test(row_id, field_name, ordinal, rule):
    def check(self):
        item = self.by_id[("case_records", row_id)]
        step = item["transformations"][ordinal]
        self.assertEqual(step["source_field"], field_name)
        self.assertEqual(step["rule_id"], rule)
        self.assertEqual(step["canonical_value_sha256"],
                         lin.sha256_object(step["canonical_value"]))
        self.assertEqual(step["canonical_value"],
                         item["normalized_record"][field_name])
    return check


for _dataset, _file, _pointer, _key in (
    ['asset_records','fixtures/cases.json','assets','asset_id'],
    ['case_records','fixtures/cases.json','records','case_id'],
    ['scripted_review_entries','fixtures/demo_review_script.json','entries','case_id'],
    ['seeded_reference_labels','fixtures/reference_labels.json','records','case_id'],
):
    for _row in lin.load_source_documents()[0][_file][_pointer]:
        _row_id = _row[_key]
        _method = "test_row_" + _dataset + "_" + _row_id.lower().replace("-", "_")
        setattr(V16LineageTests, _method,
                _make_source_record_test(_dataset, _file, _pointer, _row_id))

for _row in lin.load_source_documents()[0]["fixtures/cases.json"]["records"]:
    for _ordinal, (_field, _rule, _, _) in enumerate(lin.CASE_STEPS):
        _method = ("test_step_" + _row["case_id"].lower().replace("-", "_")
                   + "_" + _field)
        setattr(V16LineageTests, _method,
                _make_transform_step_test(_row["case_id"], _field, _ordinal, _rule))


if __name__ == "__main__":
    unittest.main()
