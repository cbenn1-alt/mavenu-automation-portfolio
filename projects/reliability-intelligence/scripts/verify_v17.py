"""V17 expected-output fixture verification report for invented maintenance data.

Runs upstream V10-V16 source correctness/lineage checks before computing
golden fixture metrics. Exact authored reference outputs are NOT customer,
domain, maintenance, finance, or independently adjudicated ground truth.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

import calculations_v17 as golden
import ingest_v14
import lineage_v16
import verify_v10
import verify_v11
import verify_v12
import verify_v13
import verify_v15

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V17"
REPORT = EVIDENCE / "golden_reference_report.json"
COMPARISON = EVIDENCE / "expected_output_comparison.json"


class V17VerificationError(ValueError):
    """Fixed diagnostic code, no customer record content."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V17VerificationError(code)


def generate() -> dict[str, Any]:
    frozen = verify_v10.verify_freeze(verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
            "v10_phase_decision_misrepresented")

    dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    idx = verify_v11.validate_dictionary(dictionary)
    contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    groups = verify_v12.validate_contract(contract, dictionary)
    source = verify_v11.load_sources()
    verify_v11.validate_rows(idx, source)
    verify_v13.validate_semantic_bounds(groups, idx, source)
    conversion = verify_v15.reference()
    verify_v15.validate_reference(conversion)
    verify_v15.execute_cases(conversion)

    policy = lineage_v16.load_policy()
    lineage_v16.validate_policy(policy)
    documents, source_hashes = lineage_v16.load_source_documents()
    require(documents == source, "v16_v11_synthetic_sources_differ")
    source_digest_before = ingest_v14.sha256(documents)
    trace = lineage_v16.reconstruct_trace(policy, documents, source_hashes)
    lineage = lineage_v16.validate_trace(trace, policy, documents, source_hashes)
    require(lineage["records_traced"] == 34 and
            lineage["transformations_traced"] == 36,
            "upstream_lineage_evidence_incomplete")

    reference = golden.load_reference()
    golden.validate_reference(reference)
    computed = golden.compute(trace)
    result = golden.compare(computed, reference)
    second = golden.compute(copy.deepcopy(trace))
    require(second == computed and
            ingest_v14.sha256(second) == ingest_v14.sha256(computed),
            "nondeterministic_reference_arithmetic")

    # Referential/aggregate invariants plus a second provenance check.
    require(ingest_v14.sha256(documents) == source_digest_before,
            "original_fixtures_modified")
    verify = lineage_v16.validate_trace(trace, policy, documents, source_hashes)
    require(verify["file_and_row_hashes_verified"] is True,
            "source_lineage_unverified")
    return {
        "increment": "V17",
        "objective": "Define golden/reference calculations",
        "required_proof": "Expected-output fixtures",
        "result": "authored_synthetic_reference_outputs_matched_approval_pending",
        "reference_status": reference["reference_status"],
        "fixture_set_id": reference["fixture_set_id"],
        "source_baseline_commit": reference["source_baseline_commit"],
        "v10_frozen_files_verified": frozen["frozen_files_verified"],
        "v10_formal_phase_promotion": "BLOCKED_RECOMMENDATION_PENDING_HUMAN_SIGNOFF",
        "v11_dictionary_approved": False,
        "v12_schema_owner_approved": False,
        "v17_owner_approved": False,
        "independent_domain_ground_truth": False,
        "real_customer_data_used": False,
        "operational_outcomes_measured": False,
        "original_fixture_data_unchanged": True,
        "source_fingerprints": source_hashes,
        "source_trace_sha256": trace["trace_batch_sha256"],
        "calculation_reference_sha256": ingest_v14.sha256(reference),
        "calculated_outputs_sha256": ingest_v14.sha256(computed),
        "matches_expected_reference_sha256": ingest_v14.sha256({
            "summary": reference["expected_summary"],
            "asset_aggregates": reference["expected_asset_aggregates"],
            "case_history": reference["expected_case_history"],
        }),
        "verified_output_counts": result,
        "reference_values": computed,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "Reference expectations were authored from fictional fixture arithmetic; no independent SME approved their domain semantics.",
            "Recurring fictional asset IDs do not indicate failure probability or actual repeat outages.",
            "Repair-cost total is fabricated input arithmetic, not savings or audited GL expense.",
            "An empty evidence-reference array is not verified missing external documentation.",
            "Formal V10 phase promotion, V11 dictionary and customer data authorization remain outstanding.",
        ],
    }


def main() -> int:
    report = generate()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = {k: v for k, v in report.items() if k != "reference_values"}
    REPORT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    COMPARISON.write_text(json.dumps({
        "increment": "V17",
        "source": "fabricated_synthetic_fixture_only",
        "proof": "Expected-output fixtures",
        "reference_status": report["reference_status"],
        "expected_sha256": report["matches_expected_reference_sha256"],
        "actual_sha256": report["calculated_outputs_sha256"],
        "comparison": report["verified_output_counts"],
        "summary": report["reference_values"]["summary"],
        "assets": report["reference_values"]["asset_aggregates"],
        "cases": report["reference_values"]["case_history"],
        "domain_ground_truth": False,
        "customer_approved": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V17_GOLDEN_OUTPUTS: " + json.dumps({
        "result": report["result"],
        "summary_metrics": report["verified_output_counts"]["summary_metrics"],
        "asset_outputs": report["verified_output_counts"]["asset_aggregates_checked"],
        "case_outputs": report["verified_output_counts"]["case_history_rows_checked"],
        "values_verified": report["verified_output_counts"]["total_synthetic_reference_values_verified"],
        "source_unchanged": True,
        "frozen_files": report["v10_frozen_files_verified"],
        "independent_domain_ground_truth": False,
        "approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V17VerificationError, golden.GoldenCalculationRejected,
            lineage_v16.LineageRejected, verify_v10.DecisionEvidenceError,
            verify_v11.FieldDictionaryError, verify_v12.SchemaContractError,
            verify_v13.V13NegativeCaseError, verify_v15.ConversionEvidenceError,
            ValueError, OSError, KeyError, TypeError):
        print("V17_GOLDEN_OUTPUTS_FAILED: reference_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
