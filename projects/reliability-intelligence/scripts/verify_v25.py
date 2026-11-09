"""V25 synthetic-only index selection and performance acceptance evidence.

Mavenu development architecture V4 p43:
    V25 Add indexes and performance profiling.
    Proof: Query-plan and threshold report.

Creates benchmark solely in automatically deleted SQLite test folders.
A passing plan/threshold is a CI baseline, not a production latency SLA.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import gate_v20
import index_v25
import lineage_v16
import verify_v10
import verify_v21

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence/V25"
REPORT = EVIDENCE / "query_plan_threshold_report.json"
BASELINE = EVIDENCE / "indexed_vs_baseline_profile.json"
PACKET = EVIDENCE / "unsigned_index_review.json"


class V25EvidenceRejected(ValueError):
    """Non-sensitive fixed rejection category."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V25EvidenceRejected(code)


def _prior_reports(*, required: bool) -> dict[str, Any]:
    if not required:
        return {"upstream_v23_v24_1_technical": "NOT_READ_IN_UNIT_MODE"}
    sources = (
        ("V23", "evidence/V23/up_down_migration_report.json"),
        ("V24", "evidence/V24/transactional_integrity_report.json"),
        ("V24.1", "evidence/V24_1/migration_persistence_integration.json"),
    )
    seen = {}
    for increment, path in sources:
        try:
            report = json.loads((PROJECT/path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V25EvidenceRejected("missing_upstream_integrity_report") from None
        require(report.get("increment") == increment and
                report.get("technical_evidence") == "PASS",
                "prior_release_technical_state_mismatch")
        if increment == "V23":
            require(report.get("up_steps_verified") == 2 and
                    report.get("down_steps_verified") == 2 and
                    report.get("fault_injections_rolled_back") == 4 and
                    report.get("production_migration_authorized") is False,
                    "v23_upgrade_rollback_evidence_inadequate")
        elif increment == "V24":
            require(report.get("committed_fabricated_records") == 120 and
                    report.get("committed_fabricated_events") == 12 and
                    report.get("duplicate_replay_additional_rows") == 0 and
                    report.get("customer_data_authorized") is False,
                    "v24_transaction_evidence_inadequate")
        else:
            require(report.get("integration_scenarios") == 8 and
                    report.get("v24_bootstrap_uses_v23_runner") is True and
                    report.get("v24_1_signoff_obtained") is False,
                    "v24_1_integration_evidence_inadequate")
        seen[increment] = "TECHNICAL_PASS_UNSIGNED"
    return seen


def generate(*, require_prior_reports: bool = False) -> dict[str, Any]:
    policy = index_v25.load_contract()
    index_v25.validate_contract(policy)
    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"] == 18,
            "v10_source_freeze_missing")
    upstream = verify_v21.source_approvals(
        require_v20_report=require_prior_reports
    )
    require(upstream["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            upstream["v21_formal_phase_03_authorized"] is False,
            "prior_phase_gate_falsely_approved")
    previous = _prior_reports(required=require_prior_reports)
    _, source_hashes = lineage_v16.load_source_documents()
    prior_hashes = {
        name: hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()
        for name in source_hashes
    }
    require(prior_hashes == source_hashes,
            "before_benchmark_fixture_hash_inconsistent")
    performance = index_v25.run_profile()
    after_hashes = {
        name: hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()
        for name in source_hashes
    }
    require(prior_hashes == after_hashes and
            performance["temporary_db_cleaned"] is True and
            performance["query_plan_and_threshold_report"]
            ["queries_verified"] == 4 and
            performance["candidate_indexes"]["index_count"] == 4 and
            performance["sqlite_schema_user_version"] == 2 and
            performance["index_install_is_v23_migration"] is False,
            "v25_source_or_benchmark_invariant")
    cases = performance["query_plan_and_threshold_report"]["comparisons"]
    require(len(cases) == 4 and
            all(v["index_chosen"] and v["sort_avoided"] and
                v["result_identical"] and v["threshold_passed"]
                for v in cases.values()),
            "query_plan_threshold_contract_not_met")
    return {
        "increment": "V25",
        "objective": "Add indexes and performance profiling",
        "required_proof": "Query-plan and threshold report",
        "result": "synthetic_query_plans_and_thresholds_verified_human_review_pending",
        "technical_evidence": "PASS",
        "workload": performance["synthetic_workload"],
        "candidate_index_inventory": performance["candidate_indexes"],
        "query_plan_thresholds": performance["query_thresholds_ms"],
        "comparison": performance["query_plan_and_threshold_report"],
        "index_ddl_rollback_verified":
            performance["injected_index_ddl_rollback_verified"],
        "schema_user_version_unchanged": True,
        "schema_user_version": performance["sqlite_schema_user_version"],
        "source_contract_sha256": performance["contract_sha256"],
        "source_sql_sha256": performance["source_sql_sha256"],
        "sqlite_version": performance["sqlite_version"],
        "source_fixture_sha256": prior_hashes,
        "source_fixtures_unchanged": True,
        "temporary_database_deleted": True,
        "v10_frozen_files": 18,
        "prior_technical_reports": previous,
        "v10_formal_phase_approval": False,
        "v20_data_quality_signoff": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_v24_1_human_reviews": "PENDING",
        "v25_human_index_review": "PENDING",
        "v25_index_is_production_migration": False,
        "customer_data_authorized": False,
        "production_index_deployment_authorized": False,
        "performance_SLA_approved": False,
        "human_review_signature": None,
        "github_sha": os.environ.get("GITHUB_SHA","not_provided"),
        "open_decisions": policy["open_decisions"],
    }


def main() -> int:
    evidence = generate(require_prior_reports=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps({
            key: value for key, value in evidence.items()
            if key != "comparison"
        },sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    BASELINE.write_text(
        json.dumps({
            "increment": "V25",
            "required_proof": evidence["required_proof"],
            "indexed_queries": evidence["comparison"],
            "benchmark_schema_version": 2,
            "baseline_relative_speedup_is_not_pass_condition": True,
            "measured_latency_not_production_SLA": True,
            "source_fixture_data_used": False,
            "customer_data_used": False,
        },sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    PACKET.write_text(
        json.dumps({
            "increment": "V25",
            "technical_result": "PASS",
            "status": "UNSIGNED_INDEX_AND_PERFORMANCE_REVIEW",
            "named_reviewer": None,
            "approved_at_utc": None,
            "signature": None,
            "independent_query_plan_review": False,
            "v10_formal_promotion": False,
            "v20_data_quality_signoff": False,
            "v21_v24_1_reviewed": False,
            "v25_index_migration_approved": False,
            "index_production_deployment_authorized": False,
            "customer_data_authorized": False,
            "open_decisions": evidence["open_decisions"],
        },sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    ms = evidence["comparison"]["comparisons"]
    print("V25_INDEX_PROFILE: "+json.dumps({
        "technical": "PASS",
        "candidate_indexes": evidence["candidate_index_inventory"]["index_count"],
        "synthetic_rows": evidence["workload"]["total_generated_rows"],
        "queries": evidence["comparison"]["queries_verified"],
        "plan_index_selected": 4,
        "threshold_passed": 4,
        "median_ms": {k:v["indexed_latency"]["median_ms"] for k,v in ms.items()},
        "p95_ms": {k:v["indexed_latency"]["p95_ms"] for k,v in ms.items()},
        "index_ddl_rollback": True,
        "source_fixtures_unchanged": True,
        "human_review": "PENDING",
        "v20_signoff": "BLOCKED",
        "production_index_deployment": False,
    },sort_keys=True),flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V25EvidenceRejected,index_v25.IndexProfileRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            OSError, UnicodeError, TypeError, KeyError,
            ValueError, sqlite3.Error):
        print("V25_INDEX_PROFILE_FAILED: synthetic_query_or_gate_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
