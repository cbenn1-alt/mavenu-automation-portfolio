"""V27 verification — backup success/failure telemetry, simulated UTC schedule.

V27: Schedule backups and integrity checks.
Proof: Backup success telemetry.

Produces reports only; each fabricated SQLite source and backup is deleted
before script exits. No actual cron installation, retained recovery copy,
production restore, real customer or tenant-isolation approval is asserted.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import backup_v27
import lineage_v16
import verify_v10
import verify_v21

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/V27"
SUCCESS_FILE = EVIDENCE / "backup_success_telemetry.json"
MATRIX_FILE = EVIDENCE / "failure_and_schedule_matrix.json"
REVIEW_FILE = EVIDENCE / "unsigned_backup_operations_review.json"


class V27VerificationRejected(ValueError):
    """Non-sensitive fixed error category."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V27VerificationRejected(code)


def read_prior_v26(*, required: bool) -> dict[str, Any]:
    if not required:
        return {"v26_technical_evidence":"NOT_READ_IN_UNIT_MODE"}
    try:
        prior = json.loads(
            (ROOT/"evidence/V26/isolation_design_decision.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V27VerificationRejected("missing_v26_isolation_evidence") from None
    require(prior.get("increment") == "V26" and
            prior.get("technical_evidence") == "PASS" and
            prior.get("v26_isolation_decision_signed") is False and
            prior.get("real_authentication_implemented") is False and
            prior.get("database_row_level_security_implemented") is False and
            prior.get("production_data_access_authorized") is False,
            "v26_security_proposal_misrepresented")
    return {"v26_technical_evidence":"PASS_UNRATIFIED",
            "prior_human_isolation_review": "PENDING"}


def generate(*, require_prior_reports: bool = False) -> dict[str, Any]:
    cfg=backup_v27.policy()
    backup_v27.validate_policy(cfg)

    frozen=verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"]==18,
            "v10_frozen_files_changed")

    approvals=verify_v21.source_approvals(
        require_v20_report=require_prior_reports)
    require(approvals["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            approvals["v21_formal_phase_03_authorized"] is False,
            "v20_phase_03_falsely_approved")
    prior=read_prior_v26(required=require_prior_reports)
    _, expected_hashes=lineage_v16.load_source_documents()
    before={
        name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        for name in expected_hashes
    }
    require(before==expected_hashes,
            "synthetic_fixture_source_manifest_invalid")

    report=backup_v27.run_evidence()
    after={
        name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        for name in expected_hashes
    }
    require(after==before and
            report["technical_evidence"]=="PASS" and
            report["simulation_successful_backups"]==2 and
            report["simulation_failed_backups"]==3 and
            report["schedule_cases_checked"]==6 and
            report["true_background_schedule_active"] is False and
            report["retained_recoverable_copy"] is False and
            report["external_restore_verified"] is False and
            report["formal_backup_review_signed"] is False,
            "v27_synthetic_backup_report_invalid")
    successes=[x for x in report["backups"] if x["status"]=="SUCCESS"]
    failures=[x for x in report["backups"] if x["status"]=="FAILED"]
    require(len(successes)==2 and len(failures)==3 and
            all(x["copy_rows_verified"]==134 and
                x["copy_file_sha256"] is not None and
                x["reopened_copy_verified"] and
                x["copy_receipt_matches_source"] and
                x["copy_file_deleted"] for x in successes) and
            all(x["copy_rows_verified"]==0 and
                x["copy_file_sha256"] is None and
                x["integrity_verified"] is False and
                x["copy_file_deleted"] for x in failures),
            "v27_backup_telemetry_false_positive")

    return {
        "increment":"V27",
        "objective":"Schedule backups and integrity checks",
        "required_proof":"Backup success telemetry",
        "result":
            "synthetic_backup_copy_integrity_verified_scheduler_and_human_approval_missing",
        "technical_evidence":"PASS",
        "schedule_policy":{
            "cron":cfg["design"]["schedule"],
            "timezone":"UTC",
            "grace_minutes":30,
            "activated":False,
            "actual_unattended_runs":0,
        },
        "success_telemetry":successes,
        "failure_telemetry":failures,
        "schedule_cases":report["schedule_matrix"],
        "successful_copies_reopened_and_verified":len(successes),
        "failed_copies_detected":len(failures),
        "no_false_successes":True,
        "copy_retained_after_test":False,
        "source_fixture_sha256":before,
        "source_fixtures_unchanged":True,
        "v10_frozen_paths":18,
        "v20_data_quality_signoff":"BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_v26_human_reviews":"PENDING",
        "v27_backup_review":"PENDING",
        "tenant_isolation_authorized":False,
        "actual_customer_data_used":False,
        "production_backup_enabled":False,
        "offsite_copy_enabled":False,
        "production_restore_verified":False,
        "legal_retention_plan_approved":False,
        "github_sha":os.environ.get("GITHUB_SHA","not_provided"),
        "prerequisite_status":prior,
        "limitations":cfg["limitations"],
        "operator_gates":cfg["operator_gates"],
    }


def main() -> int:
    report=generate(require_prior_reports=True)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    SUCCESS_FILE.write_text(json.dumps({
        "increment":"V27",
        "required_proof":"Backup success telemetry",
        "technical_evidence":"PASS",
        "successful_backups":2,
        "backup_rows_each":134,
        "actual_production_backups":0,
        "unattended_job_activated":False,
        "retained_recoverable_backup_files":0,
        "telemetry":report["success_telemetry"],
        "human_review":"PENDING",
        "customer_data_used":False,
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    MATRIX_FILE.write_text(json.dumps({
        "increment":"V27",
        "failures":report["failure_telemetry"],
        "schedule_states":report["schedule_cases"],
        "simulated_due_slot_backups":2,
        "simulated_due_slot_failures":3,
        "no_false_successes":True,
        "actual_scheduled_task_executions":0,
        "customer_data_used":False,
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    REVIEW_FILE.write_text(json.dumps({
        "increment":"V27",
        "state":"UNSIGNED_BACKUP_SCHEDULE_AND_INTEGRITY_REVIEW",
        "technical_evidence":"PASS",
        "data_owner":None,
        "security_reviewer":None,
        "backup_operator":None,
        "approved_at_utc":None,
        "signature":None,
        "v10_formal_promotion":False,
        "v20_data_correctness_signoff":False,
        "v21_v26_human_reviews":False,
        "v27_formal_backup_approval":False,
        "customer_data_access_authorized":False,
        "production_backup_enabled":False,
        "backup_retention_approved":False,
        "encryption_key_management_approved":False,
        "offsite_copy_authorized":False,
        "independent_disaster_restore_verified":False,
        "operator_gates":report["operator_gates"],
        "limitations":report["limitations"],
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("V27_BACKUP_TELEMETRY: "+json.dumps({
        "technical":"PASS",
        "synthetic_successful_copies":2,
        "synthetic_failed_copies":3,
        "validated_source_and_backup_rows":134,
        "schedule_states_tested":6,
        "receipt_and_fk_verified":True,
        "copy_reopened":True,
        "temporary_copies_retained":0,
        "actual_cron_enabled":False,
        "customer_backups":0,
        "human_review":"PENDING",
        "v20_signoff":"BLOCKED",
    },sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (V27VerificationRejected,backup_v27.BackupRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            sqlite3.Error,OSError,UnicodeError,TypeError,KeyError,ValueError):
        print("V27_BACKUP_TELEMETRY_FAILED: backup_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
