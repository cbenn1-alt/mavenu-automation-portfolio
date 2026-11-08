"""V16 synthetic source-origin and transform-lineage reconstruction.

Architecture V4 p.42: Capture ingestion origin and transform lineage.
Required proof: Record-level trace sample.

This traces checked-in, fabricated JSON rows; it does NOT observe an actual
customer ingestion event, transmit data, write to V9 runtime, or create an
immutable/signed operational audit trail. Input files remain unmodified.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import ingest_v14
import normalize_v15
import verify_v11
import verify_v12
import verify_v13

PROJECT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT / "docs" / "data" / "LINEAGE_CONTRACT_V16.json"
SOURCE_FILES = (
    "fixtures/cases.json",
    "fixtures/demo_review_script.json",
    "fixtures/reference_labels.json",
)
DATASETS = (
    ("asset_records", "fixtures/cases.json", "assets", "asset_id", 6,
     "identity_pass_through"),
    ("case_records", "fixtures/cases.json", "records", "case_id", 12,
     "v15_canonical_case_view"),
    ("scripted_review_entries", "fixtures/demo_review_script.json", "entries",
     "case_id", 4, "identity_pass_through"),
    ("seeded_reference_labels", "fixtures/reference_labels.json", "records",
     "case_id", 12, "identity_pass_through"),
)
CASE_STEPS = (
    ("occurred_at_utc", "V15_UTC_EXPLICIT", "UTC", "YYYY-MM-DDTHH:MM:SSZ"),
    ("downtime_hours", "V15_HOURS_EXACT", "hours", "ASCII decimal hours"),
    ("repair_cost_usd", "V15_USD_EXACT_CENTS", "USD",
     "ASCII decimal USD 2dp"),
)
EXPECTED_SAMPLE = (
    ("asset_records", "SYN-ASSET-001"),
    ("case_records", "SYN-CASE-001"),
    ("case_records", "SYN-CASE-009"),
    ("scripted_review_entries", "SYN-CASE-001"),
    ("seeded_reference_labels", "SYN-CASE-001"),
)


class LineageRejected(ValueError):
    """Stable diagnostic categories, never raw source record values."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise LineageRejected(code)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_object(obj: Any) -> str:
    """Canonical SHA-256 using earlier V14 synthetic JSON format."""
    return ingest_v14.sha256(obj)


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise LineageRejected("lineage_policy_unavailable") from None
    require(type(data) is dict, "lineage_policy_not_object")
    return data


def validate_policy(policy: dict[str, Any]) -> None:
    require(type(policy) is dict, "lineage_policy_not_object")
    require(policy.get("schema_version") == "1.0.0", "lineage_policy_version")
    require(policy.get("increment") == "V16", "lineage_increment_mismatch")
    require(policy.get("objective") ==
            "Capture ingestion origin and transform lineage", "lineage_objective")
    require(policy.get("required_proof") == "Record-level trace sample",
            "lineage_proof")
    require(policy.get("contract_status") ==
            "SYNTHETIC_RECONSTRUCTED_LINEAGE_NOT_APPROVED",
            "unsupported_lineage_approval")
    require(policy.get("phase") ==
            "V11-V20 exploratory synthetic data correctness", "phase_claim_drift")
    require(policy.get("source_baseline_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5",
            "frozen_source_commit_drift")
    require(policy.get("source_fixture_set_id") ==
            "SYN-RI-V5-20261107-A", "fixture_provenance_drift")
    require(policy.get("source_dictionary") ==
            "docs/data/SOURCE_FIELD_DICTIONARY_V11.json", "source_dictionary_drift")
    require(policy.get("schema_contract") ==
            "docs/data/SCHEMA_CONTRACT_V12.json", "schema_contract_drift")
    require(policy.get("normalizer_reference") ==
            "scripts/normalize_v15.py", "normalizer_reference_drift")
    require(policy.get("source_allowlist") == list(SOURCE_FILES),
            "unauthorized_source_file")
    actual_datasets = policy.get("datasets")
    expected_datasets = [
        {"id": name, "file": file, "pointer": pointer, "key": key,
         "count": count, "mode": mode}
        for name, file, pointer, key, count, mode in DATASETS
    ]
    require(actual_datasets == expected_datasets, "lineage_dataset_inventory_drift")
    actual_steps = policy.get("normalization_steps")
    expected_steps = [
        {"field": field, "rule_id": rule, "unit": unit, "locale": "en-US",
         "output_type": "string", "canonical_format": format_}
        for field, rule, unit, format_ in CASE_STEPS
    ]
    require(actual_steps == expected_steps, "lineage_transform_rule_drift")
    rules = policy.get("trace_rules")
    require(type(rules) is dict, "lineage_trace_rules_missing")
    require(rules.get("origin_capture_method") ==
            "deterministic_reconstruction_from_committed_fabricated_files",
            "ingest_origin_misrepresented")
    for flag in (
        "original_ingest_event_observed", "external_source_or_connector_observed",
        "derived_output_persisted", "v9_runtime_integrated",
        "real_source_provenance_established", "audit_signature_established",
    ):
        require(rules.get(flag) is False, "unsupported_trace_authority_" + flag)
    for key in ("record_ingested_at_utc", "source_custodian_identity"):
        require(rules.get(key) is None, "invented_ingestion_fact_" + key)
    require(rules.get("digest_algorithm") == "SHA-256",
            "lineage_digest_algorithm_drift")
    require(rules.get("canonical_encoding") ==
            "UTF-8 JSON with keys sorted, compact separators and no nonfinite values",
            "lineage_canonical_encoding_drift")
    require(policy.get("expected_source_document_count") == 3,
            "source_document_count_drift")
    require(policy.get("expected_record_count") == 34,
            "source_record_count_drift")
    require(policy.get("expected_case_record_count") == 12,
            "source_case_count_drift")
    require(policy.get("expected_case_transform_steps") == 36,
            "transform_step_count_drift")
    require(policy.get("expected_passthrough_record_count") == 22,
            "passthrough_record_count_drift")
    require(policy.get("expected_sample_record_count") == 5,
            "sample_record_count_drift")
    require(policy.get("sample_cases") ==
            [{"dataset": name, "record_id": record_id}
             for name, record_id in EXPECTED_SAMPLE],
            "sample_keys_drift")
    approval = policy.get("approval")
    require(type(approval) is dict, "lineage_approval_record_missing")
    for flag in ("v10_formal_promotion_authorized", "v11_source_dictionary_approved",
                 "v12_schema_approved", "v16_lineage_owner_approved",
                 "customer_data_authorized", "production_integration_authorized",
                 "ot_writes_permitted"):
        require(approval.get(flag) is False, "unsupported_lineage_approval_" + flag)
    for field in ("named_product_owner", "named_customer_data_steward",
                  "independent_reviewer", "approval_signature", "approval_date_utc"):
        require(approval.get(field) is None, "invented_lineage_signature_" + field)


def load_source_documents(root: Path = PROJECT) -> tuple[
    dict[str, dict[str, Any]], dict[str, str]
]:
    """Load only fixed allowlisted synthetic fixture paths; hash exact raw bytes."""
    source: dict[str, dict[str, Any]] = {}
    checksums: dict[str, str] = {}
    for relative in SOURCE_FILES:
        target = root / relative
        try:
            raw = target.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise LineageRejected("fixture_file_unavailable_or_invalid") from None
        require(type(doc) is dict and
                doc.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
                "unverified_fixture_set")
        if relative == "fixtures/cases.json":
            require(doc.get("synthetic_only") is True and
                    doc.get("source_system") == "NONE",
                    "unverified_source_origin")
        if relative == "fixtures/demo_review_script.json":
            require(doc.get("human_execution") is False and
                    doc.get("scripted_only") is True,
                    "fictional_review_not_marked")
        if relative == "fixtures/reference_labels.json":
            require(doc.get("synthetic_only") is True and
                    doc.get("independently_validated") is False,
                    "false_reference_label_authority")
        source[relative] = doc
        checksums[relative] = sha256_bytes(raw)
    return source, checksums


def _canonical_case_step(field: str, source_value: Any) -> tuple[str, dict[str, str]]:
    """V15 normalization with fixed, explicit synthetic assumptions."""
    if field == "occurred_at_utc":
        require(type(source_value) is str, "source_timestamp_not_string")
        value = normalize_v15.normalize_timestamp(source_value, "en-US")
        return value, {"locale": "en-US", "timezone": "explicit_UTC_Z"}
    if field == "downtime_hours":
        require(type(source_value) in (int, float), "source_duration_not_numeric")
        value = normalize_v15.normalize_duration(
            str(source_value), "hours", "en-US")
        return value, {"locale": "en-US", "unit": "hours"}
    if field == "repair_cost_usd":
        require(type(source_value) in (int, float), "source_cost_not_numeric")
        value = normalize_v15.normalize_money(
            str(source_value), "USD", "en-US")
        return value, {"locale": "en-US", "currency": "USD"}
    raise LineageRejected("undeclared_transform_rule")


def reconstruct_trace(
    policy: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    source_file_sha256: dict[str, str],
) -> dict[str, Any]:
    """Deterministically RECONSTRUCT source origin and three case transformations."""
    validate_policy(policy)
    require(set(documents) == set(SOURCE_FILES) and
            set(source_file_sha256) == set(SOURCE_FILES),
            "unexpected_lineage_source_set")
    traces: list[dict[str, Any]] = []
    for dataset, file, field_name, identity, row_count, mode in DATASETS:
        source_doc = documents[file]
        rows = source_doc.get(field_name)
        require(type(rows) is list and len(rows) == row_count,
                "lineage_source_row_count")
        for i, row in enumerate(rows):
            require(type(row) is dict and type(row.get(identity)) is str,
                    "lineage_source_row_invalid")
            record_id = row[identity]
            require(record_id.startswith("SYN-"), "non_synthetic_record_identity")
            derived = copy.deepcopy(row)
            steps: list[dict[str, Any]] = []
            if mode == "v15_canonical_case_view":
                for field, rule_id, _, _ in CASE_STEPS:
                    before = row[field]
                    after, parameters = _canonical_case_step(field, before)
                    derived[field] = after
                    steps.append({
                        "ordinal": len(steps) + 1,
                        "rule_id": rule_id,
                        "source_field": field,
                        "target_field": field,
                        "parameters": parameters,
                        "source_value_sha256": sha256_object(before),
                        "canonical_value_sha256": sha256_object(after),
                        "canonical_value": after,
                        "source_value_type": type(before).__name__,
                        "canonical_value_type": "str",
                    })
            origin = {
                "kind": "committed_synthetic_fixture_reconstruction",
                "source_file": file,
                "json_pointer": "/" + field_name + "/" + str(i),
                "row_index": i,
                "source_dataset": dataset,
                "source_identity_field": identity,
                "source_record_id": record_id,
                "fixture_set_id": "SYN-RI-V5-20261107-A",
                "source_file_sha256": source_file_sha256[file],
                "source_record_sha256": sha256_object(row),
                "observed_ingestion_at_utc": None,
                "customer_source_observed": False,
            }
            trace = {
                "trace_id": "SYN-LINEAGE-" + dataset + "-" + record_id,
                "origin": origin,
                "source_record_sha256": sha256_object(row),
                "transform_mode": mode,
                "transformations": steps,
                "normalized_record_sha256": sha256_object(derived),
                "normalized_record": derived,
                "source_record_unchanged": True,
            }
            traces.append(trace)
    traces.sort(key=lambda t: (t["origin"]["source_dataset"],
                               t["origin"]["source_record_id"]))
    require(len(traces) == 34 and len({x["trace_id"] for x in traces}) == 34,
            "lineage_trace_count_or_duplicate")
    require(sum(len(x["transformations"]) for x in traces) == 36,
            "lineage_transform_step_count")
    batch_digest = sha256_object(traces)
    return {
        "increment": "V16",
        "data_classification": "fabricated_non_personal",
        "origin_method": "reconstructed_from_committed_synthetic_files",
        "observed_ingest_event": False,
        "customer_data_ingested": False,
        "source_file_sha256": {
            file: source_file_sha256[file] for file in sorted(SOURCE_FILES)
        },
        "record_count": len(traces),
        "transform_step_count": 36,
        "pass_through_count": 22,
        "trace_batch_sha256": batch_digest,
        "record_traces": traces,
    }


def validate_trace(
    trace: dict[str, Any], policy: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    checksums: dict[str, str],
) -> dict[str, Any]:
    """Independently bind each trace record/field/step to source and V15 rules."""
    validate_policy(policy)
    require(type(trace) is dict, "trace_not_object")
    require(trace.get("increment") == "V16" and
            trace.get("data_classification") == "fabricated_non_personal" and
            trace.get("origin_method") ==
            "reconstructed_from_committed_synthetic_files" and
            trace.get("observed_ingest_event") is False and
            trace.get("customer_data_ingested") is False,
            "false_lineage_origin_claim")
    require(trace.get("source_file_sha256") == {
        file: checksums[file] for file in sorted(SOURCE_FILES)},
        "source_file_digest_mismatch")
    records = trace.get("record_traces")
    require(type(records) is list and len(records) == 34 and
            trace.get("record_count") == 34 and
            trace.get("transform_step_count") == 36 and
            trace.get("pass_through_count") == 22,
            "trace_coverage_mismatch")
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for item in records:
        require(type(item) is dict and type(item.get("origin")) is dict,
                "trace_record_not_object")
        origin = item["origin"]
        identity = (origin.get("source_dataset"), origin.get("source_record_id"))
        require(identity not in lookup, "duplicate_trace_identity")
        lookup[identity] = item
    step_count = 0
    for dataset, file, pointer, key, count, mode in DATASETS:
        rows = documents[file][pointer]
        require(type(rows) is list and len(rows) == count,
                "source_inventory_changed")
        for pos, row in enumerate(rows):
            record_id = row[key]
            item = lookup.get((dataset, record_id))
            require(item is not None, "trace_record_missing")
            origin = item["origin"]
            require(origin == {
                "kind": "committed_synthetic_fixture_reconstruction",
                "source_file": file,
                "json_pointer": "/" + pointer + "/" + str(pos),
                "row_index": pos,
                "source_dataset": dataset,
                "source_identity_field": key,
                "source_record_id": record_id,
                "fixture_set_id": "SYN-RI-V5-20261107-A",
                "source_file_sha256": checksums[file],
                "source_record_sha256": sha256_object(row),
                "observed_ingestion_at_utc": None,
                "customer_source_observed": False,
            }, "origin_locator_mismatch")
            require(item.get("trace_id") ==
                    "SYN-LINEAGE-" + dataset + "-" + record_id,
                    "trace_id_mismatch")
            require(item.get("source_record_sha256") == sha256_object(row),
                    "source_record_digest_mismatch")
            require(item.get("source_record_unchanged") is True and
                    item.get("transform_mode") == mode,
                    "source_preservation_claim_invalid")
            steps = item.get("transformations")
            require(type(steps) is list and
                    len(steps) == (3 if mode == "v15_canonical_case_view" else 0),
                    "transform_step_coverage_mismatch")
            normalized = copy.deepcopy(row)
            for i, (field, rule, _, _) in enumerate(CASE_STEPS if steps else ()):
                expected_value, params = _canonical_case_step(field, row[field])
                step = steps[i]
                require(step == {
                    "ordinal": i + 1,
                    "rule_id": rule,
                    "source_field": field,
                    "target_field": field,
                    "parameters": params,
                    "source_value_sha256": sha256_object(row[field]),
                    "canonical_value_sha256": sha256_object(expected_value),
                    "canonical_value": expected_value,
                    "source_value_type": type(row[field]).__name__,
                    "canonical_value_type": "str",
                }, "transform_step_mismatch")
                normalized[field] = expected_value
                step_count += 1
            require(item.get("normalized_record") == normalized,
                    "normalized_value_mismatch")
            require(item.get("normalized_record_sha256") == sha256_object(normalized),
                    "normalized_record_digest_mismatch")
    require(step_count == 36 and set(lookup) == {
        (dataset, row[key])
        for dataset, file, pointer, key, _, _ in DATASETS
        for row in documents[file][pointer]
    }, "trace_coverage_mismatch")
    expected_order = sorted(records, key=lambda item: (
        item["origin"]["source_dataset"], item["origin"]["source_record_id"]
    ))
    require(records == expected_order, "trace_record_order_mismatch")
    require(trace.get("trace_batch_sha256") == sha256_object(records),
            "trace_batch_digest_mismatch")
    return {
        "records_traced": 34,
        "transformations_traced": step_count,
        "pass_through_records": 22,
        "source_documents": len(checksums),
        "file_and_row_hashes_verified": True,
        "all_transform_steps_replayed": True,
        "real_ingestion_event_observed": False,
        "signed_chain_of_custody": False,
    }


def select_sample(trace: dict[str, Any],
                  policy: dict[str, Any]) -> list[dict[str, Any]]:
    """Five representative complete record traces without invented authority."""
    validate_policy(policy)
    by_id = {
        (item["origin"]["source_dataset"], item["origin"]["source_record_id"]): item
        for item in trace["record_traces"]
    }
    sample = []
    for dataset, record_id in EXPECTED_SAMPLE:
        item = by_id.get((dataset, record_id))
        require(item is not None, "sample_trace_record_missing")
        sample.append(copy.deepcopy(item))
    require(len(sample) == 5 and
            sum(len(s["transformations"]) for s in sample) == 6,
            "sample_trace_coverage_drift")
    return sample
