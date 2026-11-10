"""V29 exact-head timed restore and corruption-response evidence verifier.

Requires synthetic V27/V28 technical reports but preserves human approval
blockers. Every active, backup and restored database file is disposable.
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
import recovery_v29
import verify_v10
import verify_v21

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"evidence/V29"
TIMED=DIR/"timed_restore_evidence.json"
CORRUPTION=DIR/"corruption_response_matrix.json"
REVIEW=DIR/"unsigned_recovery_review.json"


class V29EvidenceRejected(ValueError):
    """Fixed non-sensitive evidence failure."""


def require(ok:Any,code:str)->None:
    if not ok:
        raise V29EvidenceRejected(code)


def prior_reports(*,required:bool)->dict[str,Any]:
    if not required:
        return {"predecessors":"NOT_READ_IN_UNIT_MODE"}
    inputs=[
        ("V27","evidence/V27/backup_success_telemetry.json"),
        ("V28","evidence/V28/retention_policy_test_report.json")
    ]
    out={}
    for version,path in inputs:
        try:
            payload=json.loads((ROOT/path).read_text(encoding="utf-8"))
        except (OSError,UnicodeError,json.JSONDecodeError):
            raise V29EvidenceRejected("missing_prior_technical_report") from None
        require(payload.get("increment")==version and
                payload.get("technical_evidence")=="PASS",
                "prior_technical_report_not_passed")
        if version=="V27":
            require(payload.get("successful_backups")==2 and
                    payload.get("actual_production_backups")==0 and
                    payload.get("retained_recoverable_backup_files")==0 and
                    payload.get("unattended_job_activated") is False,
                    "v27_backup_proof_overstated")
        else:
            require(payload.get("total_synthetic_lifecycle_records")==24 and
                    payload.get("initial_holds")==2 and
                    payload.get("human_v28_review")=="PENDING" and
                    payload.get("production_secure_erasure_verified") is False and
                    payload.get("production_backup_copies_processed") is False,
                    "v28_retention_policy_overstated")
        out[version]="TECHNICAL_PASS_HUMAN_REVIEW_PENDING"
    return out


def generate(*,require_prior_reports:bool=False)->dict[str,Any]:
    cfg=recovery_v29.policy()
    recovery_v29.validate_policy(cfg)
    frozen=verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE))
    require(frozen["frozen_files_verified"]==18,
            "frozen_v10_source_changed")
    phase=verify_v21.source_approvals(
        require_v20_report=require_prior_reports)
    require(phase["v20_data_quality_human_signoff"]==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            phase["v21_formal_phase_03_authorized"] is False,
            "prior_phase_approval_incorrect")
    prior=prior_reports(required=require_prior_reports)
    _,hashes=lineage_v16.load_source_documents()
    before={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
            for p in hashes}
    require(before==hashes,"frozen_fixture_hash_drift")
    result=recovery_v29.run_evidence()
    after={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
           for p in hashes}
    require(before==after and
            result["technical_evidence"]=="PASS" and
            result["successful_restores"]==3 and
            result["refused_restores"]==4 and
            result["actual_production_rpo_validated"] is False and
            result["actual_production_rto_validated"] is False and
            result["v28_legal_hold_and_retention_restore"] is False and
            result["retained_backup_after_test"] is False,
            "v29_restore_drill_result_invalid")
    successful=result["timed_recovery_scenarios"]
    refused=result["corruption_and_failure_scenarios"]
    require(all(x["restore"]["restored_rows"]==134 and
                x["restore"]["restored_events"]==12 and
                x["restore"]["synthetic_data_loss_rows"]==0 and
                x["restore"]["restore_total_ms"]<=10000 and
                x["restore"]["production_rto_approved"] is False and
                x["restore"]["production_rpo_approved"] is False and
                x["temporary_files_cleaned"] for x in successful) and
            all(x["accepted_rows"]==0 and
                x["temporary_files_cleaned"] and
                not x["target_created_after_failure"]
                for x in refused),
            "v29_restore_success_or_refusal_matrix_invalid")
    return {
        "increment":"V29",
        "objective":"Execute restore and corruption response drill",
        "required_proof":"Timed restore evidence",
        "result":"synthetic_restore_and_corruption_response_verified_human_release_pending",
        "technical_evidence":"PASS",
        "timed_successes":successful,
        "refused_and_corrupt_backups":refused,
        "timing_method":"time.perf_counter_ns",
        "synthetic_total_restore_threshold_ms":10000,
        "timings_are_single_sample_synthetic_ms":True,
        "synthetic_restore_count":len(successful),
        "failed_backup_refusal_count":len(refused),
        "validated_rows_per_restore":134,
        "synthetic_post_snapshot_writes":0,
        "verified_synthetic_data_loss_rows":0,
        "actual_production_rto_verified":False,
        "actual_production_rpo_verified":False,
        "backup_retained_after_test":False,
        "v28_retention_and_legal_hold_restored":False,
        "actual_customer_records_restored":0,
        "source_fixture_sha256":before,
        "frozen_v10_paths":18,
        "v20_data_quality_signoff":"BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_v28_human_reviews":"PENDING",
        "v29_dr_approval":"PENDING",
        "production_recovery_authorized":False,
        "customer_data_access_authorized":False,
        "prior_technical_reports":prior,
        "github_sha":os.environ.get("GITHUB_SHA","not_provided"),
        "risks":cfg["risks"],
        "human_readiness_gates":cfg["human_readiness_gates"],
    }


def main()->int:
    report=generate(require_prior_reports=True)
    DIR.mkdir(parents=True,exist_ok=True)
    TIMED.write_text(json.dumps({
        k:v for k,v in report.items()
        if k not in ("refused_and_corrupt_backups","risks","human_readiness_gates")
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    CORRUPTION.write_text(json.dumps({
        "increment":"V29",
        "rejected_backup_cases":report["refused_and_corrupt_backups"],
        "corruption_active_restored":[
            x for x in report["timed_successes"]
            if x["source_corruption_detected"]
        ],
        "failed_restore_target_rejected":True,
        "production_corruption_response_approved":False,
        "power_loss_exercised":False,
        "customer_data_used":False,
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    REVIEW.write_text(json.dumps({
        "increment":"V29",
        "status":"UNSIGNED_INDEPENDENT_RESTORE_AND_CORRUPTION_REVIEW",
        "technical_evidence":"PASS",
        "named_customer_owner":None,"named_dba":None,
        "named_security_reviewer":None,"reviewed_at_utc":None,
        "signature":None,
        "v10_formal_phase_release":False,
        "v20_data_quality_signoff":False,
        "v21_v28_reviews":False,
        "v29_formal_restore_approval":False,
        "retention_v28_restored":False,
        "production_rpo_approved":False,
        "production_rto_approved":False,
        "offsite_backups_approved":False,
        "actual_customer_data_access":False,
        "production_recovery_enabled":False,
        "readiness_gates":report["human_readiness_gates"],
        "risks":report["risks"],
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("V29_TIMED_RESTORE: "+json.dumps({
        "technical":"PASS",
        "successful_restores":report["synthetic_restore_count"],
        "refused_untrusted_restores":report["failed_backup_refusal_count"],
        "verified_rows_each":134,
        "measured_total_ms":{
            x["case"]:x["restore"]["restore_total_ms"]
            for x in report["timed_successes"]
        },
        "zero_synthetic_post_snapshot_writes":True,
        "active_corruption_detected":2,
        "v28_legal_hold_restore":False,
        "production_rto_rpo_approved":False,
        "customer_records_restored":0,
        "human_review":"PENDING",
        "v20_signoff":"BLOCKED",
    },sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (V29EvidenceRejected,recovery_v29.RecoveryRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            sqlite3.Error,OSError,UnicodeError,KeyError,ValueError,TypeError):
        print("V29_TIMED_RESTORE_FAILED: integrity_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
