"""V26 synthetic tenant boundaries, data rights and isolation decision evidence.

Architecture V4 p43: Document tenant boundaries and data rights.
Required proof: Isolation design decision.

The decision is PROPOSED, not customer-owned, signed, or approved. The
isolation probes demonstrate only an in-process reference guard applied
to fabricated actor IDs; database RLS and external authentication are absent.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import isolation_v26 as isolation
import lineage_v16
import verify_v10
import verify_v21

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence/V26"
REPORT = EVIDENCE / "isolation_design_decision.json"
MATRIX = EVIDENCE / "synthetic_access_probe_matrix.json"
PACKET = EVIDENCE / "unsigned_data_rights_review.json"


class V26EvidenceRejected(ValueError):
    """Stable diagnostic without arbitrary source text."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V26EvidenceRejected(code)


def _prior_reports(*, required: bool) -> dict[str, Any]:
    if not required:
        return {"upstream_current_reports": "SKIPPED_IN_UNIT_TEST_MODE"}
    requirements = (
        ("V23", "evidence/V23/up_down_migration_report.json"),
        ("V24", "evidence/V24/transactional_integrity_report.json"),
        ("V24.1", "evidence/V24_1/migration_persistence_integration.json"),
        ("V25", "evidence/V25/query_plan_threshold_report.json"),
    )
    result = {}
    for version,path in requirements:
        try:
            payload = json.loads((PROJECT / path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V26EvidenceRejected("missing_prior_release_evidence") from None
        require(payload.get("increment") == version and
                payload.get("technical_evidence") == "PASS",
                "prior_technical_release_unverified")
        if version == "V23":
            require(payload.get("up_steps_verified") == 2 and
                    payload.get("down_steps_verified") == 2 and
                    payload.get("production_migration_authorized") is False,
                    "v23_migration_governance_drift")
        elif version == "V24":
            require(payload.get("committed_fabricated_records") == 120 and
                    payload.get("duplicate_replay_additional_rows") == 0 and
                    payload.get("customer_data_authorized") is False,
                    "v24_storage_governance_drift")
        elif version == "V24.1":
            require(payload.get("v24_bootstrap_uses_v23_runner") is True and
                    payload.get("integration_scenarios") == 8 and
                    payload.get("v24_1_signoff_obtained") is False,
                    "v24_1_integration_governance_drift")
        else:
            require(payload.get("candidate_index_inventory",{})
                    .get("index_count") == 4 and
                    payload.get("query_plan_thresholds") ==
                    {"median":80,"p95":200} and
                    payload.get("production_index_deployment_authorized") is False,
                    "v25_index_approval_drift")
        result[version] = "TECHNICALLY_VERIFIED_HUMAN_REVIEW_PENDING"
    return result


def generate(*, require_prior_reports: bool = False) -> dict[str, Any]:
    policy = isolation.load_policy()
    isolation.validate_policy(policy)

    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"] == 18,
            "frozen_v10_source_files_changed")
    approvals = verify_v21.source_approvals(
        require_v20_report=require_prior_reports
    )
    require(approvals["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            approvals["v21_formal_phase_03_authorized"] is False,
            "prior_formal_gate_was_misrepresented")
    previous = _prior_reports(required=require_prior_reports)
    _, known_hashes = lineage_v16.load_source_documents()
    before = {
        name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
        for name in known_hashes
    }
    require(before == known_hashes, "fixture_digests_before_not_pinned")
    replay = isolation.run_isolation_replay()
    after = {
        name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
        for name in known_hashes
    }
    require(before == after and
            replay["entity_row_counts"]["total_rows"] == 38 and
            replay["entity_row_counts"]["duplicate_case_001_count"] == 4 and
            replay["matrix"]["attempted_grant_combinations"] == 48 and
            replay["matrix"]["allowed_reads"] == 8 and
            replay["matrix"]["denied_reads"] == 40 and
            replay["matrix"]["malformed_or_unsupported_probes_denied"] == 10 and
            replay["matrix"]["cross_tenant_or_site_leak_found"] is False and
            replay["temporary_database_deleted"] is True,
            "v26_isolation_probe_or_source_invariant")
    require(replay["principal_authentication"] == "NOT_IMPLEMENTED" and
            replay["database_row_level_security"] == "NOT_IMPLEMENTED" and
            replay["legal_customer_data_rights"] == "NOT_ESTABLISHED" and
            replay["human_design_approval"] == "PENDING" and
            replay["production_access_authorized"] is False,
            "v26_false_security_or_rights_attestation")
    return {
        "increment": "V26",
        "objective": "Document tenant boundaries and data rights",
        "required_proof": "Isolation design decision",
        "result": "synthetic_isolation_probes_verified_production_design_unratified",
        "technical_evidence": "PASS",
        "isolation_design": {
            "proposed_for_synthetic_tests":
                policy["selected_for_synthetic_prototype"],
            "production_architecture_decision":
                policy["production_choice"],
            "options_evaluated": policy["design_options"],
            "trust_boundaries": policy["trust_boundaries"],
            "rights_position": policy["rights_position"],
            "human_decision": policy["human_decision"],
        },
        "synthetic_isolation_results": replay,
        "data_classes": policy["data_classes"],
        "v10_frozen_source_files_verified": 18,
        "source_fixture_sha256": before,
        "source_fixtures_unchanged": True,
        "prior_technical_reports": previous,
        "v20_data_quality_signoff":
            "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_v25_human_reviews": "PENDING",
        "v26_isolation_decision_signed": False,
        "customer_data_license": "NOT_EXECUTED",
        "real_authentication_implemented": False,
        "database_row_level_security_implemented": False,
        "actual_production_tenant_isolation_tested": False,
        "production_data_access_authorized": False,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": policy["limitations"],
    }


def main() -> int:
    result = generate(require_prior_reports=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        {key: value for key,value in result.items()
         if key != "synthetic_isolation_results"},
        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    MATRIX.write_text(json.dumps({
        "increment": "V26",
        "required_proof": "Isolation design decision",
        "synthetic_probe": result["synthetic_isolation_results"],
        "actual_customer_actor_authentication": False,
        "actual_database_rls_enforced": False,
        "human_security_validation": "PENDING",
    },indent=2,sort_keys=True) + "\n",encoding="utf-8")
    PACKET.write_text(json.dumps({
        "increment": "V26",
        "technical_isolation_harness": "PASS",
        "state": "UNSIGNED_ISOLATION_AND_DATA_RIGHTS_DECISION",
        "provisional_prototype_isolation":
            result["isolation_design"]["proposed_for_synthetic_tests"],
        "production_isolation_choice":
            result["isolation_design"]["production_architecture_decision"],
        "named_customer_data_owner": None,
        "named_data_protection_reviewer": None,
        "named_security_reviewer": None,
        "named_technical_architect": None,
        "reviewed_at_utc": None,
        "signature": None,
        "owner_signoff": False,
        "legal_data_rights_approved": False,
        "tenant_authentication_implemented": False,
        "database_row_level_security_implemented": False,
        "v10_formal_promotion": False,
        "v20_data_correctness_signoff": False,
        "v21_v25_human_reviews": False,
        "v26_formal_approval": False,
        "customer_data_access_approved": False,
        "production_isolation_approved": False,
        "unresolved_decisions":
            result["isolation_design"]["human_decision"]["required_evidence"],
        "limitations": result["limitations"],
    },indent=2,sort_keys=True) + "\n",encoding="utf-8")
    matrix = result["synthetic_isolation_results"]["matrix"]
    print("V26_ISOLATION_DECISION: "+json.dumps({
        "technical": "PASS",
        "synthetic_tenants": 2,
        "site_scopes": 4,
        "artificial_actors": 6,
        "grant_combinations": matrix["attempted_grant_combinations"],
        "allowed_reads": matrix["allowed_reads"],
        "denied_reads": matrix["denied_reads"],
        "malformed_probes_denied":
            matrix["malformed_or_unsupported_probes_denied"],
        "cross_tenant_scope_leaks": 0,
        "actual_authentication": False,
        "database_rls": False,
        "data_rights_approved": False,
        "customer_access_authorized": False,
        "human_review": "PENDING",
        "v20_signoff": "BLOCKED",
    },sort_keys=True),flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V26EvidenceRejected, isolation.V26InvariantError,
            isolation.ScopeDenied,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            OSError,UnicodeError,TypeError,KeyError,ValueError,sqlite3.Error):
        print("V26_ISOLATION_DECISION_FAILED: synthetic_scope_or_approval_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
