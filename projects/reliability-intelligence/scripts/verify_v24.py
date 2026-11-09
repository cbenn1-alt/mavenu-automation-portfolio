"""V24 transactional integrity verification for synthetic temporary SQLite files.

Architecture V4 p43: Persist validated records and events.
Required proof: Transactional integrity tests.

V23 up/down migrations DO NOT EXIST. This uses a temporary DB bootstrap and
does not authorize customer data, production persistence, or a human signoff.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import persist_v24
import verify_v10
import verify_v21
import verify_v22
import lineage_v16

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "V24"
REPORT = EVIDENCE / "transactional_integrity_report.json"
MATRIX = EVIDENCE / "rollback_reopen_matrix.json"
PACKET = EVIDENCE / "unsigned_persistence_review.json"


class V24EvidenceRejected(ValueError):
    """Fixed diagnostic, no source data included in failure output."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V24EvidenceRejected(code)


def generate(*, require_prior_report: bool = False) -> dict[str, Any]:
    contract = persist_v24.policy()
    persist_v24.validate_policy(contract)

    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"] == 18,
            "v10_source_frozen_files_changed")
    prior = verify_v21.source_approvals(
        require_v20_report=require_prior_report
    )
    require(prior["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            prior["v21_formal_phase_03_authorized"] is False,
            "prior_phase_permission_overstated")

    if require_prior_report:
        path = ROOT / "evidence/V22/identity_reference_validation.json"
        try:
            upstream = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V24EvidenceRejected("v22_technical_report_missing") from None
        require(upstream.get("increment") == "V22" and
                upstream.get("result") ==
                "synthetic_identity_links_verified_owner_review_pending" and
                upstream.get("v22_human_identity_review") == "PENDING" and
                upstream.get("v23_formal_migration_approved") is False and
                upstream.get("uniqueness_scopes_checked") == 13 and
                upstream.get("scoped_links_checked") == 9,
                "v22_technical_or_human_state_invalid")

    docs, hashes = lineage_v16.load_source_documents()
    before = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in hashes
    }
    require(before == hashes, "source_manifest_inconsistent_before")
    scenarios = [
        persist_v24.run_scenario(),
        persist_v24.run_scenario(inject_failure="after_records"),
        persist_v24.run_scenario(inject_failure="after_event_4"),
    ]
    require(
        all(s["first_write"] == "COMMITTED" and
            s["second_write"] == "ALREADY_COMMITTED" and
            s["duplicate_rows_added"] == 0 and
            s["reopen_integrity"]["total_rows"] == 134 and
            s["reopen_integrity"]["events"] == 12 and
            s["reopen_integrity"]["receipts"] == 1 and
            s["used_temporary_file"] and
            s["file_deleted_after_context"]
            for s in scenarios),
        "v24_atomicity_reopen_or_replay_failed"
    )
    after = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in hashes
    }
    require(before == after, "source_fixtures_changed")
    success, rolled_records, rolled_events = scenarios
    require(success["reopen_integrity"]["receipt_sha256"] ==
            rolled_records["reopen_integrity"]["receipt_sha256"] ==
            rolled_events["reopen_integrity"]["receipt_sha256"],
            "v24_scenario_final_receipts_differ")
    return {
        "increment": "V24",
        "objective": "Persist validated records and events",
        "required_proof": "Transactional integrity tests",
        "result": "synthetic_temporary_transactions_verified_v23_migration_and_human_approval_missing",
        "technical_evidence": "PASS",
        "scenarios": scenarios,
        "scenario_count": 3,
        "transactional_atomicity_checks": 2,
        "committed_fabricated_records": 120,
        "committed_fabricated_events": 12,
        "committed_batch_receipts": 2,
        "total_committed_rows_per_scenario": 134,
        "reopen_receipt_verified": True,
        "duplicate_replay_additional_rows": 0,
        "source_fixture_sha256": before,
        "source_fixtures_unchanged": True,
        "v10_frozen_paths": 18,
        "v20_data_quality_signoff": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_human_schema_review": "PENDING",
        "v22_human_identity_review": "PENDING",
        "v23_reversible_migration_implemented": False,
        "v23_up_down_migration_evidence": False,
        "v24_human_persistence_review": "PENDING",
        "formal_storage_phase_approval": False,
        "production_durability_verified": False,
        "customer_data_authorized": False,
        "ot_or_cmms_write_authorized": False,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": contract["limitations"],
    }


def main() -> int:
    result = generate(require_prior_report=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        k: v for k,v in result.items()
        if k != "scenarios"
    }, indent=2,sort_keys=True) + "\n",encoding="utf-8")
    MATRIX.write_text(json.dumps({
        "increment": "V24",
        "required_proof": result["required_proof"],
        "scenarios": result["scenarios"],
        "scenario_count": result["scenario_count"],
        "v23_migration_evidence_present": False,
        "production_durability_certified": False,
        "customer_data_used": False,
    },indent=2,sort_keys=True) + "\n",encoding="utf-8")
    PACKET.write_text(json.dumps({
        "increment":"V24",
        "required_proof":result["required_proof"],
        "status":"UNSIGNED_SYNTHETIC_STORAGE_CANDIDATE",
        "technical_integrity":"PASS",
        "human_review_complete":False,
        "named_reviewers":[],
        "approved_at_utc":None,
        "signature":None,
        "v23_reversible_migration_proof":False,
        "v20_data_quality_signoff":result["v20_data_quality_signoff"],
        "production_storage_authorized":False,
        "customer_data_access_authorized":False,
        "schema_sha256":hashlib.sha256(persist_v24.DDL.encode("utf-8")).hexdigest(),
        "reopen_receipt_sha256":result["scenarios"][0]
          ["reopen_integrity"]["receipt_sha256"],
        "human_readiness_blockers":[
            "V23 up/down migration tests and evidence absent",
            "V20 Data Correctness formal phase sign-off blocked",
            "V21/V22 independent human schema and identity reviews pending",
            "Customer data rights and production security/backup/durability approvals missing",
        ],
    },indent=2,sort_keys=True) + "\n",encoding="utf-8")
    print("V24_TRANSACTIONAL_PERSISTENCE: " + json.dumps({
        "technical":"PASS",
        "committed_records":result["committed_fabricated_records"],
        "events":result["committed_fabricated_events"],
        "scenarios":result["scenario_count"],
        "injected_rollback_checks":result["transactional_atomicity_checks"],
        "reopen_verified":result["reopen_receipt_verified"],
        "duplicate_replay_additions":result["duplicate_replay_additional_rows"],
        "source_unchanged":result["source_fixtures_unchanged"],
        "v23_migration_present":False,
        "human_review":"PENDING",
        "v20_signoff":"BLOCKED",
    },sort_keys=True),flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V24EvidenceRejected,persist_v24.PersistenceRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            OSError,UnicodeError,KeyError,TypeError,ValueError):
        print("V24_TRANSACTIONAL_PERSISTENCE_FAILED: synthetic_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
