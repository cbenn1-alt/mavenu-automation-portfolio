"""V28 retention-policy technical evidence — fabricated lifecycle store only.

Source: Mavenu AI SaaS Platform Development Architecture V4 p43.
V28: Enforce retention, deletion and archives.
Required proof: Retention-policy tests.

Human data rights/retention/hold authorities remain unsigned. A successful
DELETE from temporary SQLite is not durable backup purging or secure erasure.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import lineage_v16
import retention_v28
import verify_v10
import verify_v21

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "evidence/V28"
REPORT = DIR / "retention_policy_test_report.json"
MATRIX = DIR / "archive_delete_hold_matrix.json"
REVIEW = DIR / "unsigned_retention_review.json"


class V28EvidenceRejected(ValueError):
    """Non-sensitive verification category."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V28EvidenceRejected(code)


def _prerequisites(required: bool) -> dict[str, Any]:
    if not required:
        return {"prior_reports":"NOT_READ_IN_UNIT_TEST_MODE"}
    inputs = [
        ("V26", "evidence/V26/isolation_design_decision.json"),
        ("V27", "evidence/V27/backup_success_telemetry.json"),
    ]
    output={}
    for version,location in inputs:
        try:
            content=json.loads((ROOT/location).read_text(encoding="utf-8"))
        except (OSError,UnicodeError,json.JSONDecodeError):
            raise V28EvidenceRejected("missing_prior_evidence") from None
        require(content.get("increment")==version,
                "prior_increment_not_expected")
        if version=="V26":
            require(content.get("technical_evidence")=="PASS" and
                    content.get("v26_isolation_decision_signed") is False and
                    content.get("real_authentication_implemented") is False and
                    content.get("database_row_level_security_implemented") is False,
                    "v26_real_isolation_falsely_claimed")
        else:
            require(content.get("technical_evidence")=="PASS" and
                    content.get("successful_backups")==2 and
                    content.get("actual_production_backups")==0 and
                    content.get("retained_recoverable_backup_files")==0 and
                    content.get("unattended_job_activated") is False,
                    "v27_real_backup_falsely_claimed")
        output[version]="TECHNICAL_PASS_HUMAN_REVIEW_PENDING"
    return output


def generate(*, require_prior_reports: bool=False) -> dict[str,Any]:
    cfg=retention_v28.policy()
    retention_v28.validate_policy(cfg)
    frozen=verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE))
    require(frozen["frozen_files_verified"]==18,
            "v10_source_freeze_changed")
    v21=verify_v21.source_approvals(
        require_v20_report=require_prior_reports)
    require(v21["v20_data_quality_human_signoff"]==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            v21["v21_formal_phase_03_authorized"] is False,
            "v20_formal_gate_overstated")
    priors=_prerequisites(require_prior_reports)
    _,known=lineage_v16.load_source_documents()
    before={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
            for p in known}
    require(before==known,"before_fixture_hash_change")
    result=retention_v28.run_scenarios()
    after={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
           for p in known}
    require(before==after and result["technical_evidence"]=="PASS" and
            result["source_fixture_rows"]==38 and
            result["lifecycle_records"]==24 and
            result["initial_legal_holds"]==2 and
            len(result["injection_recoveries"])==2 and
            all(x["rolled_back"] and x["pre_state_recovered"]
                for x in result["injection_recoveries"]) and
            result["first_policy_application"]["after"]==
            cfg["storage_design"]["expected_after_enforcement"] and
            result["after_simulated_hold_release"]["after"]==
            cfg["storage_design"][
                "expected_after_authorized_simulated_hold_release"] and
            result["idempotent_replay"]["operations"]["archived"]==0 and
            result["idempotent_replay"]["operations"]["purged"]==0 and
            result["blocked_cross_tenant_hold_release"] is True and
            result["source_not_mutated"] is True and
            result["sqlite_audit_chain_verified"] is True and
            result["sidecar_file_deleted"] is True and
            result["source_file_deleted"] is True and
            result["secure_disk_erasure_verified"] is False and
            result["customer_data_used"] is False,
            "v28_retention_policy_evidence_inconsistent")
    return {
        "increment":"V28",
        "objective":"Enforce retention, deletion and archives",
        "required_proof":"Retention-policy tests",
        "technical_evidence":"PASS",
        "result":"synthetic_archive_purge_hold_and_rollback_verified_production_policy_unsigned",
        "total_synthetic_lifecycle_records":24,
        "archive_thresholds_days":{
            item["data_class"]:item["archive_after_days"]
            for item in cfg["storage_design"]["categories"]},
        "purge_threshold_days":90,
        "initial_holds":2,
        "first_transition_counts":result["first_policy_application"]["after"],
        "final_after_simulated_hold_release":
            result["after_simulated_hold_release"]["after"],
        "injected_rollback_count":len(result["injection_recoveries"]),
        "no_duplicate_purge_or_archive_on_replay":True,
        "cross_tenant_hold_release_rejected":True,
        "audit_hash_chain_validated":True,
        "raw_case_identifiers_in_tombstones":False,
        "retention_policy_operationally_enabled":False,
        "real_customer_records_deleted":0,
        "original_source_untouched":True,
        "source_fixture_sha256":before,
        "frozen_v10_source_files":18,
        "v20_data_quality_signoff":"BLOCKED_PENDING_HUMAN_SIGNOFF",
        "prior_technical_reports":priors,
        "human_v28_review":"PENDING",
        "actual_legal_hold_authority":False,
        "production_secure_erasure_verified":False,
        "production_backup_copies_processed":False,
        "data_rights_approved":False,
        "github_sha":os.environ.get("GITHUB_SHA","not_provided"),
        "technical_scenarios":result,
        "limitations":cfg["risks"],
        "readiness_gates":cfg["human_readiness_gates"],
    }


def main() -> int:
    report=generate(require_prior_reports=True)
    DIR.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(
        {k:v for k,v in report.items() if k!="technical_scenarios"},
        indent=2,sort_keys=True)+"\n",encoding="utf-8")
    MATRIX.write_text(json.dumps({
        "increment":"V28",
        "required_proof":"Retention-policy tests",
        "technical_scenarios":report["technical_scenarios"],
        "production_archive_present":False,
        "secure_erasure_verified":False,
        "real_data_subject_records_deleted":0,
        "human_hold_authority_approved":False,
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    REVIEW.write_text(json.dumps({
        "increment":"V28",
        "review_status":"UNSIGNED_RETENTION_AND_LEGAL_HOLD_REVIEW",
        "technical_evidence":"PASS",
        "named_legal_data_owner":None,
        "named_legal_hold_authority":None,
        "named_security_reviewer":None,
        "reviewed_at_utc":None,"signature":None,
        "retention_periods_approved":False,
        "legal_hold_release_workflow_authorized":False,
        "secure_deletion_and_backup_coverage_approved":False,
        "tenant_isolation_approved":False,
        "v10_formal_promotion":False,
        "v20_data_correctness_signoff":False,
        "v21_v27_human_reviews":False,
        "v28_production_release":False,
        "customer_data_access_authorized":False,
        "readiness_gates":report["readiness_gates"],
        "risks":report["limitations"],
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("V28_RETENTION_POLICY: "+json.dumps({
        "technical":"PASS",
        "synthetic_records":24,
        "archived_on_first_run":8,
        "purged_on_first_run":6,
        "held_preserved":2,
        "additional_purged_after_fake_hold_release":2,
        "idempotent_replay":True,
        "injected_rollbacks":2,
        "audit_chain":"PASS",
        "real_customer_deletions":0,
        "secure_erase_certified":False,
        "human_review":"PENDING",
        "v20_signoff":"BLOCKED",
    },sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (V28EvidenceRejected,retention_v28.RetentionRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            sqlite3.Error,OSError,UnicodeError,ValueError,KeyError,TypeError):
        print("V28_RETENTION_POLICY_FAILED: lifecycle_or_approval_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
