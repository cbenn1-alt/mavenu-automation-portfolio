"""V18 adverse-case regression evidence for fabricated maintenance inputs.

Architecture V4 p.42: Test missing, stale and malformed inputs.
Required proof: Adverse-case regression suite.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import adverse_v18 as adverse
import ingest_v14
import verify_v10
import verify_v11
import verify_v12
import verify_v13
import verify_v15
import verify_v16
import verify_v17

PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "evidence" / "V18" / "adverse_regression_report.json"


class V18VerificationError(ValueError):
    """Fail closed with fixed non-sensitive diagnostic categories."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V18VerificationError(code)


def generate() -> dict[str, Any]:
    frozen = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
            "v10_formal_promotion_pending")
    dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    index = verify_v11.validate_dictionary(dictionary)
    contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    groups = verify_v12.validate_contract(contract, dictionary)
    sources = verify_v11.load_sources()
    verify_v11.validate_rows(index, sources)
    verify_v13.validate_semantic_bounds(groups, index, sources)

    # V15-V17 outputs are still replayed independently in the CI sequence.
    # Here only the new V18 staleness policy is applied to already validated
    # synthetic source rows, without any production runtime data modification.
    corpus = adverse.read_corpus()
    inventory = adverse.validate_corpus(corpus)
    digest = ingest_v14.sha256(sources)
    results = adverse.exercise(corpus, sources, dictionary, contract)
    require(ingest_v14.sha256(sources) == digest,
            "frozen_synthetic_source_modified")
    require(results["negative_cases"] == 44 and
            results["positive_controls"] == 5 and
            results["original_source_unchanged"],
            "adverse_regression_coverage_incomplete")
    return {
        "increment": "V18",
        "objective": "Test missing, stale and malformed inputs",
        "required_proof": "Adverse-case regression suite",
        "result": "synthetic_adverse_cases_verified_human_approval_pending",
        "reference_clock_utc": adverse.FIXED_CLOCK,
        "synthetic_max_age_days": adverse.AGE_DAYS,
        "synthetic_max_future_skew_hours": adverse.FUTURE_HOURS,
        "reference_freshness_customer_approved": False,
        "v10_frozen_source_files_verified": frozen["frozen_files_verified"],
        "v10_formal_phase_promotion_authorized": False,
        "v11_source_dictionary_approved": False,
        "v12_schema_approved": False,
        "v18_owner_approved": False,
        "customer_data_used": False,
        "production_ingestion_enabled": False,
        "external_sources_accessed": False,
        "source_digest_unchanged": True,
        "adverse_inventory": inventory,
        "adverse_results": results,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "All 44 adverse and 5 positive cases use fabricated in-memory fixture copies.",
            "Staleness windows are explicit synthetic test parameters, not customer-approved SLAs.",
            "Malformed JSON and invalid UTF-8 are deterministic test byte strings, not external ingest payloads.",
            "No customer data, product runtime changes, production connectors, OT/CMMS writes, or live events.",
            "V10 phase promotion and V11/V12 source contract approvals remain outstanding.",
        ],
    }


def main() -> int:
    report = generate()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    result = report["adverse_results"]
    print("V18_ADVERSE_REGRESSION: " + json.dumps({
        "result": report["result"],
        "adverse_rejected": result["negative_cases"],
        "positive_accepted": result["positive_controls"],
        "category_counts": result["negative_by_category"],
        "source_records": result["baseline"]["records_checked"],
        "timestamps": result["baseline"]["timestamps_checked"],
        "frozen_files": report["v10_frozen_source_files_verified"],
        "real_customer_ingestion": False,
        "formally_approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V18VerificationError, adverse.AdverseRejected,
            verify_v10.DecisionEvidenceError, verify_v11.FieldDictionaryError,
            verify_v12.SchemaContractError, verify_v13.V13NegativeCaseError,
            ValueError, KeyError, TypeError, OSError):
        print("V18_ADVERSE_REGRESSION_FAILED: synthetic_validation_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
