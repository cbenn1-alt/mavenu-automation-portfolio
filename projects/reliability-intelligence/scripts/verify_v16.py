"""V16 record-level trace sample and lineage verification evidence.

Technical evidence for "Capture ingestion origin and transform lineage":
reconstructed origins are bound to pinned synthetic file bytes, JSON pointers,
record hashes, and V15 conversion steps. This does NOT observe a real ingest,
provide an immutable/signed audit trail, or assert customer-system authority.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

import ingest_v14
import lineage_v16
import verify_v10
import verify_v11
import verify_v12
import verify_v13
import verify_v15

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V16"
REPORT = EVIDENCE / "lineage_verification.json"
SAMPLE = EVIDENCE / "record_level_trace_sample.json"
FULL_TRACE = EVIDENCE / "synthetic_record_lineage.json"

class V16VerificationError(ValueError):
    """A fixed failure category, never an untrusted source value."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V16VerificationError(code)


def generate_proof() -> dict[str, Any]:
    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE))
    decision = verify_v11.read_json(verify_v11.DECISION_PATH)
    require(decision.get("formal_phase_promotion_authorized") is False and
            decision.get("recommended_promotion_decision") == "BLOCKED" and
            decision.get("formal_decision") == "PENDING_HUMAN_SIGNOFF",
            "v10_formal_promotion_not_blocked")
    dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    index = verify_v11.validate_dictionary(dictionary)
    contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    groups = verify_v12.validate_contract(contract, dictionary)
    synthetic = verify_v11.load_sources()
    verify_v11.validate_rows(index, synthetic)
    verify_v13.validate_semantic_bounds(groups, index, synthetic)
    reference = verify_v15.reference()
    verify_v15.validate_reference(reference)
    verify_v15.execute_cases(reference)

    policy = lineage_v16.load_policy()
    lineage_v16.validate_policy(policy)
    source, sha = lineage_v16.load_source_documents()
    require(source == synthetic,
            "lineage_source_differs_from_v11_validated_fixtures")
    initial_source_digest = ingest_v14.sha256(source)
    initial_source_bytes_digest = lineage_v16.sha256_object(sha)

    trace = lineage_v16.reconstruct_trace(policy, source, sha)
    review = lineage_v16.validate_trace(trace, policy, source, sha)
    sample = lineage_v16.select_sample(trace, policy)
    # A second reconstruction and validation must be byte-for-byte stable.
    repeat = lineage_v16.reconstruct_trace(policy, source, sha)
    require(repeat == trace and
            lineage_v16.sha256_object(repeat) == lineage_v16.sha256_object(trace),
            "lineage_not_deterministic")
    require(ingest_v14.sha256(source) == initial_source_digest and
            lineage_v16.sha256_object(sha) == initial_source_bytes_digest,
            "lineage_modified_original_source")
    require(len(sample) == 5 and len(trace["record_traces"]) == 34 and
            sum(len(x["transformations"]) for x in sample) == 6,
            "sample_lineage_coverage_incomplete")
    return {
        "increment": "V16",
        "objective": "Capture ingestion origin and transform lineage",
        "proof": "Record-level trace sample",
        "result": "synthetic_reconstructed_lineage_verified_human_approval_pending",
        "scope": "reconstructed provenance from authored synthetic fixtures ONLY",
        "source_commit": policy["source_baseline_commit"],
        "fixture_set_id": policy["source_fixture_set_id"],
        "v10_frozen_paths_verified": frozen["frozen_files_verified"],
        "v10_promotion_approved": False,
        "v11_dictionary_approved": False,
        "v12_schema_owner_approved": False,
        "v16_human_approved": False,
        "customer_source_observed": False,
        "actual_ingest_event_observed": False,
        "normalized_output_persisted": False,
        "ot_or_cmms_writes_permitted": False,
        "source_bytes_unchanged": True,
        "source_documents_sha256": trace["source_file_sha256"],
        "source_records": review["records_traced"],
        "transforms_replayed": review["transformations_traced"],
        "pass_through_records": review["pass_through_records"],
        "sample_record_count": len(sample),
        "sample_transform_count": sum(len(x["transformations"]) for x in sample),
        "all_trace_hashes_verified": review["file_and_row_hashes_verified"],
        "deterministic_replay": True,
        "trace_batch_sha256": trace["trace_batch_sha256"],
        "trace_document_sha256": lineage_v16.sha256_object(trace),
        "sample_sha256": lineage_v16.sha256_object(sample),
        "full_trace": trace,
        "sample_trace": sample,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "Reconstructed origin pointers are NOT timestamps of a real ingestion event.",
            "Synthetic hashes establish reproducibility, not signed chain of custody.",
            "V15 normalization assumptions and V11 source semantics are unapproved.",
            "No customer data, production APIs, OT system, CMMS writes or measured savings.",
            "The V10 human phase-promotion gate remains blocked and unsigned.",
        ],
    }


def main() -> int:
    record = generate_proof()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    # Review sample is deliberately separate and minimal, while the full
    # synthetic trace allows independent complete-record reconstruction.
    public = {k: v for k, v in record.items()
              if k not in ("sample_trace", "full_trace")}
    REPORT.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    SAMPLE.write_text(json.dumps({
        "increment": "V16",
        "proof": "Record-level trace sample",
        "origin_method": "reconstructed_from_committed_synthetic_files",
        "customer_ingest_observed": False,
        "sample_count": len(record["sample_trace"]),
        "sample_sha256": record["sample_sha256"],
        "source_commit": record["source_commit"],
        "traces": record["sample_trace"],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    FULL_TRACE.write_text(json.dumps(
        record["full_trace"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print("V16_RECORD_LINEAGE: " + json.dumps({
        "result": record["result"],
        "records": record["source_records"],
        "source_documents": len(record["source_documents_sha256"]),
        "transforms": record["transforms_replayed"],
        "sample_records": record["sample_record_count"],
        "sample_transforms": record["sample_transform_count"],
        "frozen_source_files": record["v10_frozen_paths_verified"],
        "real_ingest_observed": False,
        "formally_approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V16VerificationError, lineage_v16.LineageRejected,
            verify_v10.DecisionEvidenceError, verify_v11.FieldDictionaryError,
            verify_v12.SchemaContractError, verify_v13.V13NegativeCaseError,
            verify_v15.ConversionEvidenceError, ValueError, KeyError, TypeError,
            OSError):
        print("V16_RECORD_LINEAGE_FAILED: source_or_transform_lineage_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
