"""V15 conversion reference evidence runner; synthetic-only, no customer actions.

Produces deterministic timestamp/unit/locale reference checks without
mutating frozen fixtures, inferring named timezones or applying FX rates.
The V10 phase decision and V11 dictionary approval remain unsigned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import ingest_v14
import normalize_v15 as norm
import verify_v10
import verify_v11
import verify_v12
import verify_v13

PROJECT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = PROJECT / "fixtures" / "conversion_reference_v15.json"
REPORT = PROJECT / "evidence" / "V15" / "conversion_reference_report.json"
EXPECTED_ACCEPT = 27
EXPECTED_REJECT = 24
KIND_COUNTS = {"timestamp": 10, "duration": 9, "money": 8}
SUPPORTED_LOCALES = ["en-US", "en-GB", "de-DE", "fr-FR"]

class ConversionEvidenceError(ValueError):
    """A stable test-evidence failure without raw source or customer content."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise ConversionEvidenceError(code)


def reference() -> dict[str, Any]:
    try:
        result = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ConversionEvidenceError("conversion_reference_invalid_json") from None
    require(type(result) is dict, "conversion_reference_not_object")
    return result


def validate_reference(ref: dict[str, Any]) -> dict[str, int]:
    require(ref.get("schema_version") == "1.0.0", "reference_schema_version")
    require(ref.get("increment") == "V15", "reference_increment")
    require(ref.get("objective") == "Normalize timestamps, units and locales",
            "reference_objective")
    require(ref.get("required_proof") == "Conversion reference tests",
            "reference_proof")
    require(ref.get("fixture_status") == "SYNTHETIC_REFERENCE_UNAPPROVED",
            "false_conversion_approval")
    require(ref.get("source_fixture_set_id") == "SYN-RI-V5-20261107-A",
            "fixture_lineage_drift")
    require(ref.get("source_baseline_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5",
            "source_commit_drift")
    require(ref.get("supported_locales") == SUPPORTED_LOCALES,
            "supported_locale_contract_drift")
    require(ref.get("supported_duration_units") == ["hours", "minutes", "seconds"],
            "supported_unit_contract_drift")
    require(ref.get("money_currency") == "USD", "money_currency_contract_drift")
    require(ref.get("canonical_fields") == {
        "occurred_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
        "downtime_hours": "decimal ASCII hours max 6 fractional places",
        "repair_cost_usd": "decimal ASCII USD with exactly 2 fraction digits",
    }, "canonical_format_drift")
    policy = ref.get("conversion_policy")
    require(type(policy) is dict and
            policy.get("source_mutation") == "never" and
            policy.get("rounding") == "no silent precision loss for durations or money" and
            policy.get("money") == "USD only; no FX conversion or exchange rate inference" and
            policy.get("duration_range_hours") == [0, 240] and
            policy.get("usd_range") == [0, 1000000], "unsafe_conversion_policy_drift")
    approval = ref.get("approval")
    require(type(approval) is dict, "approval_record_missing")
    for key in ("formal_phase_02_authorized", "source_dictionary_approved",
                "customer_data_authorized", "owner_signoff", "production_authorized"):
        require(approval.get(key) is False, "false_approval_" + key)
    require(approval.get("reviewer") is None and
            approval.get("signature") is None, "fabricated_reviewer_identity")
    accept = ref.get("accepted_reference_cases")
    reject = ref.get("rejected_reference_cases")
    require(type(accept) is list and len(accept) == EXPECTED_ACCEPT and
            ref.get("expected_accepted_count") == EXPECTED_ACCEPT,
            "accepted_reference_inventory_drift")
    require(type(reject) is list and len(reject) == EXPECTED_REJECT and
            ref.get("expected_rejected_count") == EXPECTED_REJECT,
            "rejected_reference_inventory_drift")
    all_ids: set[str] = set()
    counts = {key: 0 for key in KIND_COUNTS}
    for item in accept + reject:
        require(type(item) is dict, "reference_case_not_object")
        id_ = item.get("id")
        kind = item.get("kind")
        require(type(id_) is str and
                re.fullmatch(r"[TEMD]-[A-Z0-9-]+", id_) is not None and
                id_ not in all_ids, "reference_id_invalid_or_duplicate")
        all_ids.add(id_)
        require(kind in KIND_COUNTS, "unsupported_fixture_type")
        counts[kind] += 1
        require(type(item.get("value")) is str and
                type(item.get("locale")) is str and item["locale"] != "",
                "reference_value_or_locale_missing")
        if kind == "duration":
            require(type(item.get("unit")) is str, "reference_unit_missing")
        if kind == "money":
            require(type(item.get("currency")) is str, "reference_currency_missing")
        require(("expected" in item) ^ ("error" in item),
                "reference_result_shape_invalid")
        if "expected" in item:
            require(type(item["expected"]) is str, "expected_value_not_string")
        else:
            require(type(item["error"]) is str and
                    re.fullmatch(r"[a-z_]+", item["error"]) is not None,
                    "expected_error_not_category")
    require(counts == {"timestamp": 18, "duration": 16, "money": 17},
            "conversion_category_coverage_drift")
    return counts


def execute_cases(ref: dict[str, Any]) -> dict[str, Any]:
    positive: list[dict[str, str]] = []
    negative: list[dict[str, str]] = []
    for item in ref["accepted_reference_cases"]:
        actual = norm.convert_reference(item)
        require(actual == item["expected"], "conversion_reference_mismatch")
        if item["kind"] == "timestamp":
            repeated = norm.normalize_timestamp(actual, "en-US")
        elif item["kind"] == "duration":
            repeated = norm.normalize_duration(actual, "hours", "en-US")
        else:
            repeated = norm.normalize_money(actual, "USD", "en-US")
        require(repeated == actual, "canonical_repeat_not_idempotent")
        positive.append({"case_id": item["id"], "kind": item["kind"],
                         "result": "MATCHED", "canonical": actual})
    for item in ref["rejected_reference_cases"]:
        try:
            norm.convert_reference(item)
        except norm.NormalizationRejected as exc:
            require(str(exc) == item["error"], "wrong_conversion_rejection")
        else:
            raise ConversionEvidenceError("invalid_reference_was_accepted")
        negative.append({"case_id": item["id"], "kind": item["kind"],
                         "result": "REJECTED_AS_EXPECTED", "error": item["error"]})
    return {
        "accepted": len(positive),
        "rejected": len(negative),
        "positive_cases": positive,
        "negative_cases": negative,
        "canonical_replay_idempotent": True,
    }


def unchanged_fixture_conversion(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    original_sha = ingest_v14.sha256(sources)
    cases = sources["fixtures/cases.json"]["records"]
    require(len(cases) == 12, "source_case_count_drift")
    rows = []
    for case in cases:
        timestamp = norm.normalize_timestamp(case["occurred_at_utc"], "en-US")
        duration = norm.normalize_duration(str(case["downtime_hours"]), "hours", "en-US")
        money = norm.normalize_money(str(case["repair_cost_usd"]), "USD", "en-US")
        require(timestamp == case["occurred_at_utc"], "existing_utc_timestamp_changed")
        require(float(duration) == float(case["downtime_hours"]),
                "existing_duration_value_changed")
        require(float(money) == float(case["repair_cost_usd"]),
                "existing_cost_value_changed")
        rows.append({
            "case_id": case["case_id"], "occurred_at_utc": timestamp,
            "downtime_hours": duration, "repair_cost_usd": money,
        })
    require(ingest_v14.sha256(sources) == original_sha, "source_changed_during_conversion")
    return {
        "case_count": len(rows),
        "source_sha256_before_and_after": original_sha,
        "source_unmodified": True,
        "synthetic_rows": rows,
    }


def main() -> int:
    frozen = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
            "v10_approval_not_pending")
    dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    index = verify_v11.validate_dictionary(dictionary)
    groups = verify_v12.validate_contract(contract, dictionary)
    sources = verify_v11.load_sources()
    verify_v11.validate_rows(index, sources)
    verify_v13.validate_semantic_bounds(groups, index, sources)
    ref = reference()
    counts = validate_reference(ref)
    results = execute_cases(ref)
    originals = unchanged_fixture_conversion(sources)
    report = {
        "increment": "V15",
        "objective": "Normalize timestamps, units and locales",
        "proof": "Conversion reference tests",
        "result": "synthetic_conversions_verified_formal_approval_pending",
        "reference_counts_by_type": counts,
        "accepted_reference_tests": results["accepted"],
        "rejected_reference_tests": results["rejected"],
        "canonical_replay_idempotent": results["canonical_replay_idempotent"],
        "test_results": results,
        "source_comparison": originals,
        "v10_frozen_source_files_verified": frozen["frozen_files_verified"],
        "v10_phase_promotion_authorized": False,
        "source_dictionary_approved": False,
        "customer_data_used": False,
        "normalizer_approved_for_customer_use": False,
        "persistent_ingestion_enabled": False,
        "external_connectors_enabled": False,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "Only explicit UTC offsets; named timezones and DST transitions are not inferred.",
            "Supported locale formats are fixed test formats, not a locale internationalization engine.",
            "USD only. No FX conversion, inflation accounting, taxes or verified customer cost semantics.",
            "Lossy duration and money conversions reject rather than round silently.",
            "V9 production runtime and V10 source freeze remain unchanged.",
            "V10 formal promotion and V11 dictionary human signatures remain outstanding.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    print("V15_CONVERSION_REFERENCES: " + json.dumps({
        "result": report["result"],
        "accepted": results["accepted"],
        "rejected": results["rejected"],
        "unchanged_fixture_cases": originals["case_count"],
        "source_changed": False,
        "canonical_replay": True,
        "frozen_source_files": frozen["frozen_files_verified"],
        "approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConversionEvidenceError, norm.NormalizationRejected,
            verify_v10.DecisionEvidenceError, verify_v11.FieldDictionaryError,
            verify_v12.SchemaContractError, verify_v13.V13NegativeCaseError,
            ValueError, OSError, KeyError, TypeError):
        print("V15_CONVERSION_REFERENCES_FAILED: reference_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
