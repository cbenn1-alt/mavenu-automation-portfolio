"""V18 synthetic missing, stale, and malformed input rejection.

Architecture V4 p.42: V18 Test missing, stale and malformed inputs.
Required proof: Adverse-case regression suite.

Strictly synthetic, non-destructive checks. The freshness clock is an
explicit fixed *test parameter* and is NOT a customer-approved ingestion SLA.
No live customer ingestion, current wall clock, V9 runtime modification, or
plant/CMMS/OT write is performed.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

import verify_v11
import verify_v12

PROJECT = Path(__file__).resolve().parents[1]
CORPUS = PROJECT / "fixtures" / "adverse_inputs_v18.json"
SOURCES = (
    "fixtures/cases.json",
    "fixtures/demo_review_script.json",
    "fixtures/reference_labels.json",
)
EXPECTED_ROWS = {
    "asset_records": ("fixtures/cases.json", "assets", 6),
    "case_records": ("fixtures/cases.json", "records", 12),
    "scripted_review_entries": ("fixtures/demo_review_script.json", "entries", 4),
    "seeded_reference_labels": ("fixtures/reference_labels.json", "records", 12),
}
EXPECTED_CATEGORIES = {"missing": 16, "stale": 7, "malformed": 21}
EXPECTED_NEGATIVE = 44
EXPECTED_POSITIVE = 5

EXPECTED_CASE_CODES = {
    "MISS-CASE-CASE-ID": "missing_required_field",
    "MISS-CASE-ASSET-ID": "missing_required_field",
    "MISS-CASE-WORK-ORDER-REF": "missing_required_field",
    "MISS-CASE-OCCURRED-AT-UTC": "missing_required_field",
    "MISS-CASE-FAILURE-CODE": "missing_required_field",
    "MISS-CASE-DOWNTIME-HOURS": "missing_required_field",
    "MISS-CASE-REPAIR-COST-USD": "missing_required_field",
    "MISS-CASE-EVIDENCE-REFS": "missing_required_field",
    "MISS-CASE-SYNTHETIC": "missing_required_field",
    "MISS-CASE-REVIEW-STATE": "missing_required_field",
    "MISS-CASES-DOCUMENT": "missing_source_document",
    "MISS-REVIEW-DOCUMENT": "missing_source_document",
    "MISS-CASES-COLLECTION": "missing_required_collection",
    "MISS-ASSETS-COLLECTION": "missing_required_collection",
    "MISS-REVIEW-DISPOSITION": "missing_required_field",
    "MISS-REFERENCE-LABEL": "missing_required_field",
    "STALE-BEFORE-WINDOW": "stale_record",
    "STALE-OLD-DECEMBER": "stale_record",
    "STALE-LAST-YEAR": "stale_record",
    "STALE-EXTREMELY-OLD": "stale_record",
    "STALE-SECOND-CASE": "stale_record",
    "STALE-FUTURE-SECOND": "future_record",
    "STALE-FUTURE-YEAR": "future_record",
    "MAL-UTC-MONTH": "malformed_timestamp",
    "MAL-UTC-NAIVE": "malformed_timestamp",
    "MAL-NULL-UTC": "null_required_field",
    "MAL-BOOL-DURATION": "malformed_required_value",
    "MAL-COST-TEXT": "malformed_required_value",
    "MAL-EVIDENCE-TEXT": "malformed_required_value",
    "MAL-INVALID-FAILURE": "malformed_required_value",
    "MAL-CASE-ARRAY": "malformed_source_record",
    "MAL-DOCUMENT-ARRAY": "malformed_source_document",
    "MAL-CLAIM-REAL": "invalid_synthetic_origin",
    "MAL-FALSE-SYNTHETIC": "invalid_synthetic_origin",
    "MAL-SCRIPT-HUMAN": "invalid_synthetic_origin",
    "MAL-WRONG-FIXTURE": "invalid_synthetic_origin",
    "MAL-UNDECLARED-FIELD": "unknown_field",
    "MAL-EXTRA-DOCUMENT": "unapproved_source_document",
    "MAL-INFINITE-COST": "nonfinite_numeric",
    "MAL-NAN-DURATION": "nonfinite_numeric",
    "MAL-INVALID-UTF8": "invalid_utf8_source",
    "MAL-DUPLICATE-JSON-KEY": "duplicate_json_member",
    "MAL-TRAILING-COMMA": "malformed_json_source",
    "MAL-NONFINITE-JSON": "invalid_nonfinite_json",
}
EXPECTED_POSITIVE_IDS = ["OK-BASELINE","OK-EXACT-STALE-BOUNDARY","OK-INSIDE-STALE-BOUNDARY","OK-EXACT-FUTURE-SKEW","OK-EXACT-AS-OF"]
FIXED_CLOCK = "2026-02-05T00:00:00Z"
AGE_DAYS = 45
FUTURE_HOURS = 24
ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"
ALLOWED_OPERATIONS = {
    "delete_field", "drop_document", "drop_collection", "set_field",
    "replace_row", "replace_document", "set_metadata", "add_field",
    "add_document", "special_numeric", "raw_marker",
}
RAW_MARKERS = {
    "invalid_utf8": b"\xff\xfe{",
    "duplicate_member": b'{"fixture_set_id":"SYN","fixture_set_id":"OTHER"}',
    "trailing_comma": b'{"fixture_set_id":"SYN",}',
    "nonfinite_json": b'{"value":NaN}',
}


class AdverseRejected(ValueError):
    """Fixed diagnostic category only: never emit raw row contents."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise AdverseRejected(code)


def read_corpus(path: Path = CORPUS) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise AdverseRejected("adverse_corpus_unavailable") from None
    require(type(data) is dict, "adverse_corpus_not_object")
    return data


def _utc(value: Any) -> datetime:
    require(type(value) is str, "malformed_timestamp")
    try:
        result = datetime.strptime(value, ISO_UTC)
    except ValueError:
        raise AdverseRejected("malformed_timestamp") from None
    require(result.strftime(ISO_UTC) == value, "malformed_timestamp")
    return result.replace(tzinfo=timezone.utc)


def validate_corpus(corpus: dict[str, Any]) -> dict[str, int]:
    """Lock the reference clock, artificial bounds and unsigned status."""
    require(type(corpus) is dict and corpus.get("schema_version") == "1.0.0",
            "adverse_schema_version")
    require(corpus.get("increment") == "V18", "adverse_increment")
    require(corpus.get("objective") ==
            "Test missing, stale and malformed inputs", "adverse_objective")
    require(corpus.get("required_proof") ==
            "Adverse-case regression suite", "adverse_proof")
    require(corpus.get("corpus_status") ==
            "SYNTHETIC_ADVERSARIAL_FIXTURES_NOT_CUSTOMER_APPROVED",
            "false_adverse_approval")
    require(corpus.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
            "adverse_fixture_set_drift")
    require(corpus.get("source_baseline_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5",
            "adverse_frozen_source_drift")
    require(corpus.get("allowed_sources") == list(SOURCES),
            "unapproved_source_file_added")
    policy = corpus.get("freshness_policy")
    require(type(policy) is dict and
            policy.get("reference_clock_utc") == FIXED_CLOCK and
            policy.get("max_age_days") == AGE_DAYS and
            policy.get("max_future_skew_hours") == FUTURE_HOURS and
            policy.get("exact_timestamp_format") == "YYYY-MM-DDTHH:MM:SSZ" and
            policy.get("actual_current_time_used") is False and
            policy.get("customer_approved") is False, "unapproved_freshness_claim")
    require(type(policy.get("source")) is str and
            policy["source"].startswith("Artificial test policy,"),
            "unverified_freshness_source")
    _utc(policy["reference_clock_utc"])
    approval = corpus.get("approval")
    require(type(approval) is dict, "adverse_approval_missing")
    for flag in ("formal_phase_02_authorized", "v11_dictionary_approved",
                 "v12_schema_approved", "v18_domain_owner_approved",
                 "customer_data_authorized", "ot_or_cmms_write_permitted"):
        require(approval.get(flag) is False, "false_adverse_approval_" + flag)
    require(approval.get("v10_formal_decision") == "PENDING_HUMAN_SIGNOFF" and
            approval.get("v10_recommendation") == "BLOCKED",
            "v10_promotion_claim_invalid")
    require(approval.get("named_owner") is None and
            approval.get("signature") is None, "fictitious_adverse_signoff")
    cases = corpus.get("adverse_cases")
    controls = corpus.get("positive_controls")
    require(type(cases) is list and len(cases) == EXPECTED_NEGATIVE and
            corpus.get("expected_adverse_case_count") == EXPECTED_NEGATIVE,
            "adverse_inventory_drift")
    require(type(controls) is list and len(controls) == EXPECTED_POSITIVE and
            corpus.get("expected_positive_control_count") == EXPECTED_POSITIVE,
            "positive_control_inventory_drift")
    require(corpus.get("expected_category_counts") == EXPECTED_CATEGORIES,
            "adverse_category_count_drift")
    seen: set[str] = set()
    categories = dict.fromkeys(EXPECTED_CATEGORIES, 0)
    for item in cases:
        require(type(item) is dict and
                type(item.get("id")) is str and
                re.fullmatch(r"(MISS|STALE|MAL)-[A-Z0-9-]+", item["id"]) is not None and
                item["id"] not in seen,
                "duplicate_or_invalid_adverse_case_id")
        seen.add(item["id"])
        category, operation = item.get("category"), item.get("operation")
        require(category in EXPECTED_CATEGORIES and
                operation in ALLOWED_OPERATIONS, "adverse_category_or_operation")
        require(item["id"].startswith({"missing": "MISS-", "stale": "STALE-",
                                      "malformed": "MAL-"}[category]),
                "category_id_mismatch")
        categories[category] += 1
        require(type(item.get("expected_error")) is str and
                re.fullmatch(r"[a-z0-9_]+", item["expected_error"]),
                "expected_error_invalid")
        require(item["expected_error"] == EXPECTED_CASE_CODES[item["id"]],
                "adverse_case_expected_error_drift")
        _validate_case_target(item)
    require(categories == EXPECTED_CATEGORIES and
            seen == set(EXPECTED_CASE_CODES), "adverse_case_identity_drift")
    for item in controls:
        require(type(item) is dict and type(item.get("id")) is str and
                re.fullmatch(r"OK-[A-Z0-9-]+", item["id"]) is not None and
                item["id"] not in seen and item.get("expected") == "accepted",
                "positive_case_invalid")
        seen.add(item["id"])
        require(item.get("operation") in ("baseline", "set_field"),
                "positive_operation_invalid")
        if item["operation"] == "set_field":
            _validate_case_target(item)
    require([item["id"] for item in controls] == EXPECTED_POSITIVE_IDS,
            "positive_boundary_identity_drift")
    return {"negative_count": len(cases), "positive_count": len(controls),
            "category_counts": categories}


def _validate_case_target(item: dict[str, Any]) -> None:
    operation = item.get("operation")
    if operation == "baseline":
        return
    target = item.get("target")
    require(type(target) is dict, "adverse_target_not_object")
    doc = target.get("document")
    require(type(doc) is str and
            (doc in SOURCES or
             (operation == "add_document" and doc ==
              "fixtures/customer_export.json")),
            "adverse_target_document_not_allowlisted")
    if operation in ("delete_field", "set_field", "add_field",
                     "special_numeric", "replace_row"):
        collection = target.get("collection")
        idx = target.get("row_index")
        allowed = {
            "fixtures/cases.json": {"assets": 6, "records": 12},
            "fixtures/demo_review_script.json": {"entries": 4},
            "fixtures/reference_labels.json": {"records": 12},
        }
        require(type(collection) is str and
                collection in allowed[doc] and
                type(idx) is int and 0 <= idx < allowed[doc][collection],
                "adverse_row_target_invalid")
        if operation != "replace_row":
            require(type(target.get("field")) is str and
                    re.fullmatch(r"[a-z_]+", target["field"]),
                    "adverse_field_target_invalid")
    if operation == "drop_collection":
        require(type(target.get("collection")) is str and
                target["collection"] in ("assets", "records", "entries"),
                "adverse_collection_target_invalid")
    if operation == "set_metadata":
        require(target.get("field") in ("source_system", "synthetic_only",
                                       "human_execution", "fixture_set_id"),
                "adverse_metadata_target_invalid")
    if operation == "special_numeric":
        require(item.get("value") in ("nan", "positive_infinity", "negative_infinity"),
                "unsupported_nonfinite_marker")
    if operation == "raw_marker":
        require(item.get("value") in RAW_MARKERS, "unsupported_raw_marker")


def parse_source_bytes(raw: bytes) -> dict[str, Any]:
    """Strict UTF-8 JSON parser: rejects duplicate members and non-JSON NaN."""
    require(type(raw) is bytes, "source_bytes_not_bytes")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise AdverseRejected("invalid_utf8_source") from None

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_member")
            result[key] = value
        return result

    def reject_nonfinite(_: str) -> None:
        raise AdverseRejected("invalid_nonfinite_json")

    try:
        value = json.loads(content, object_pairs_hook=unique_pairs,
                           parse_constant=reject_nonfinite)
    except (UnicodeError, json.JSONDecodeError):
        raise AdverseRejected("malformed_json_source") from None
    require(type(value) is dict, "malformed_source_document")
    return value


def validate_snapshot(documents: dict[str, Any],
                      dictionary: dict[str, Any],
                      contract: dict[str, Any]) -> dict[str, Any]:
    """Validate an in-memory synthetic source snapshot with fixed-age checks.

    Existing V11/V12/V13 constraints remain authoritative. Error categories
    remain fixed; original fixture files and V9 runtime are never modified.
    """
    require(type(documents) is dict, "malformed_source_inventory")
    required = set(SOURCES)
    require(required.issubset(documents), "missing_source_document")
    require(set(documents).issubset(required), "unapproved_source_document")
    index = verify_v11.validate_dictionary(dictionary)
    groups = verify_v12.validate_contract(contract, dictionary)
    reference = _utc(FIXED_CLOCK)
    oldest = reference - timedelta(days=AGE_DAYS)
    latest = reference + timedelta(hours=FUTURE_HOURS)
    checked_timestamps = 0
    checked_rows = 0

    for file in SOURCES:
        doc = documents[file]
        require(type(doc) is dict, "malformed_source_document")
        require(doc.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
                "invalid_synthetic_origin")
        if file == "fixtures/cases.json":
            require(doc.get("synthetic_only") is True and
                    doc.get("source_system") == "NONE",
                    "invalid_synthetic_origin")
        elif file == "fixtures/demo_review_script.json":
            require(doc.get("scripted_only") is True and
                    doc.get("human_execution") is False,
                    "invalid_synthetic_origin")
        else:
            require(doc.get("synthetic_only") is True and
                    doc.get("independently_validated") is False,
                    "invalid_synthetic_origin")
    for dataset, (file, collection, expected_count) in EXPECTED_ROWS.items():
        doc = documents[file]
        require(collection in doc, "missing_required_collection")
        rows = doc[collection]
        require(type(rows) is list and len(rows) == expected_count,
                "malformed_record_collection")
        required_fields = index[dataset]
        for row in rows:
            require(type(row) is dict, "malformed_source_record")
            require(set(required_fields).issubset(row), "missing_required_field")
            require(set(row).issubset(required_fields), "unknown_field")
            checked_rows += 1
            for field, definition in required_fields.items():
                value = row[field]
                require(value is not None, "null_required_field")
                if (definition["logical_type"] == "number" and
                        type(value) in (int, float)):
                    require(math.isfinite(value), "nonfinite_numeric")
                if definition["logical_type"] == "utc_timestamp":
                    at = _utc(value)
                    checked_timestamps += 1
                    require(oldest <= at, "stale_record")
                    require(at <= latest, "future_record")
                require(verify_v11._matches(value, definition),
                        "malformed_required_value")

    try:
        verify_v11.validate_rows(index, documents)
    except verify_v11.FieldDictionaryError:
        raise AdverseRejected("semantic_source_constraints_invalid") from None
    return {
        "datasets_checked": 4, "records_checked": checked_rows,
        "timestamps_checked": checked_timestamps,
        "source_count": len(SOURCES),
        "fixed_reference_clock": FIXED_CLOCK,
        "max_age_days": AGE_DAYS,
        "max_future_skew_hours": FUTURE_HOURS,
        "source_only_synthetic": True,
        "real_ingest_observed": False,
    }


def apply_case(item: dict[str, Any],
               original: dict[str, Any]) -> dict[str, Any]:
    """No external filesystem/connector access; mutate only a deep copy."""
    op = item["operation"]
    changed = copy.deepcopy(original)
    if op == "baseline":
        return changed
    if op == "raw_marker":
        parse_source_bytes(RAW_MARKERS[item["value"]])
        return changed
    target = item["target"]
    path = target["document"]
    if op == "drop_document":
        changed.pop(path, None)
        return changed
    if op == "add_document":
        changed[path] = copy.deepcopy(item["value"])
        return changed
    if op == "replace_document":
        changed[path] = copy.deepcopy(item["value"])
        return changed
    if op == "drop_collection":
        changed[path].pop(target["collection"], None)
        return changed
    if op == "set_metadata":
        changed[path][target["field"]] = copy.deepcopy(item["value"])
        return changed
    row = changed[path][target["collection"]][target["row_index"]]
    if op == "replace_row":
        changed[path][target["collection"]][target["row_index"]] = copy.deepcopy(item["value"])
        return changed
    name = target["field"]
    if op == "delete_field":
        row.pop(name, None)
    elif op in ("set_field", "add_field"):
        row[name] = copy.deepcopy(item["value"])
    elif op == "special_numeric":
        row[name] = {"nan": math.nan, "positive_infinity": math.inf,
                     "negative_infinity": -math.inf}[item["value"]]
    else:
        raise AdverseRejected("unsupported_adverse_operation")
    return changed


def exercise(corpus: dict[str, Any], source: dict[str, Any],
             dictionary: dict[str, Any],
             contract: dict[str, Any]) -> dict[str, Any]:
    """Run every committed example, with exact fixed-error expectations."""
    inventory = validate_corpus(corpus)
    original_hash = __import__("hashlib").sha256(json.dumps(
        source, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")).hexdigest()
    baseline = validate_snapshot(source, dictionary, contract)
    rejected: list[dict[str, str]] = []
    accepted: list[dict[str, str]] = []
    for item in corpus["adverse_cases"]:
        try:
            mutated = apply_case(item, source)
            validate_snapshot(mutated, dictionary, contract)
        except AdverseRejected as exc:
            require(str(exc) == item["expected_error"],
                    "adverse_expected_rejection_code_mismatch")
        else:
            raise AdverseRejected("adverse_case_unexpectedly_accepted")
        rejected.append({"id": item["id"], "category": item["category"],
                         "error": item["expected_error"],
                         "result": "REJECTED_AS_EXPECTED"})
    for item in corpus["positive_controls"]:
        mutated = apply_case(item, source)
        accepted_report = validate_snapshot(mutated, dictionary, contract)
        require(accepted_report["records_checked"] == 34,
                "positive_control_source_count_drift")
        accepted.append({"id": item["id"], "result": "ACCEPTED_AS_EXPECTED"})
    final_hash = __import__("hashlib").sha256(json.dumps(
        source, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")).hexdigest()
    require(original_hash == final_hash, "original_synthetic_source_mutated")
    require(len(rejected) == EXPECTED_NEGATIVE and
            len(accepted) == EXPECTED_POSITIVE, "case_execution_incomplete")
    return {
        "negative_cases": len(rejected),
        "positive_controls": len(accepted),
        "negative_by_category": inventory["category_counts"],
        "baseline": baseline,
        "expected_rejections": rejected,
        "valid_boundary_controls": accepted,
        "original_source_sha256_before_and_after": original_hash,
        "original_source_unchanged": True,
        "no_external_ingestion": True,
        "fake_plant_clock_used": False,
        "in_memory_only": True,
    }
