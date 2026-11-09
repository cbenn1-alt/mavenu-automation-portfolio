"""V23 exact-head reversible schema migration verification.

Source: Mavenu 120-version Architecture V4 p43.
V23: Implement reversible schema migration path.
Proof: Up/down migration evidence.

Temporary synthetic SQLite files ONLY. V24 was already merged to the V22
branch before V23 was written. Here we verify compatibility with both the
V21 base tables and the V24 ledger, but do NOT rewrite V24's bootstrap to
invoke migrations, certify live upgrade paths, or assert human approvals.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any

import entity_v21
import gate_v20
import identity_v22
import lineage_v16
import migrate_v23 as migration
import persist_v24
import verify_v10
import verify_v21

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V23"
REPORT = EVIDENCE / "up_down_migration_report.json"
MATRIX = EVIDENCE / "migration_failure_matrix.json"
PACKET = EVIDENCE / "unsigned_migration_review.json"
FAULTS = (
    (0, 1, "up_v1_after_3_tables"),
    (1, 2, "up_v2_after_1_ledger"),
    (2, 1, "down_v2_after_1_drop"),
    (1, 0, "down_v1_after_4_drops"),
)


class V23EvidenceRejected(ValueError):
    """Stable non-sensitive rejection code."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V23EvidenceRejected(code)


def _db_run(fn):
    with tempfile.TemporaryDirectory(prefix="mavenu-v23-") as name:
        path = Path(name) / migration.FILE_NAME
        db = migration.connect(path)
        try:
            return fn(db, path)
        finally:
            db.close()


def empty_roundtrip() -> dict[str, Any]:
    """0 -> 1 -> 2 -> 1 -> 0; same schema after each rollback."""
    def run(db, path):
        start = migration.validate_version(db, 0)
        up1 = migration.migrate_step(db, 1)
        first = migration.validate_version(db, 1)
        up2 = migration.migrate_step(db, 2)
        second = migration.validate_version(db, 2)
        down2 = migration.migrate_step(db, 1)
        restored_one = migration.validate_version(db, 1)
        down1 = migration.migrate_step(db, 0)
        end = migration.validate_version(db, 0)
        require(first["schema_sha256"] == restored_one["schema_sha256"] and
                start["schema_sha256"] == end["schema_sha256"] and
                second["tables"] == 13 and
                second["triggers"] == 6,
                "empty_upgrade_downgrade_not_reversible")
        again = migration.migrate_to(db, 2)
        require(again["applied_steps"] == 2 and
                again["final_state"]["schema_sha256"] ==
                second["schema_sha256"],
                "migration_up_replay_not_deterministic")
        return {
            "initial": start, "up_v1": up1, "up_v2": up2,
            "down_v2": down2, "down_v1": down1,
            "reapplied": again, "restored_v1_schema_matches": True,
            "restored_v0_schema_matches": True,
            "file_in_tempdir": True,
        }
    return _db_run(run)


def populated_v21_roundtrip() -> dict[str, Any]:
    """Validated 120-row V21 source survives adding/removing empty V24 ledger."""
    def run(db, path):
        migration.migrate_step(db, 1)
        from_source = entity_v21.load_synthetic_preview(
            db, entity_v21.load_model()
        )
        require(from_source["total_rows"] == 120 and
                from_source["foreign_key_violations"] == 0,
                "populated_v21_snapshot_invalid")
        prior_rows = persist_v24.records_sha(db)
        up = migration.migrate_step(db, 2)
        require(migration.validate_version(db, 2)["tables"] == 13,
                "v24_ledger_migration_not_present")
        after_up = persist_v24.records_sha(db)
        down = migration.migrate_step(db, 1)
        after_down = persist_v24.records_sha(db)
        require(prior_rows == after_up == after_down and
                entity_v21.preview_counts(db)["total_rows"] == 120,
                "v21_records_changed_on_migration")
        try:
            migration.migrate_step(db, 0)
        except migration.MigrationRejected as err:
            require(str(err) == "data_bearing_downgrade_denied",
                    "unsafe_v21_downgrade_wrong_error")
        else:
            raise V23EvidenceRejected("unsafe_v21_downgrade_allowed")
        require(migration.validate_version(db, 1)["tables"] == 10,
                "unsafe_downgrade_changed_version")
        return {
            "source_records": 120, "up": up, "down": down,
            "source_records_sha256": prior_rows,
            "record_digest_unchanged": True,
            "nonempty_v21_downgrade_denied": True,
            "foreign_key_violations": 0,
        }
    return _db_run(run)


def populated_v24_downgrade_refused() -> dict[str, Any]:
    """Existing V24 134-row commit must make ledger-destroying down fail."""
    def run(db, path):
        migration.migrate_to(db, 2)
        receipt = persist_v24.commit_snapshot(db)
        require(receipt["write_result"] == "COMMITTED" and
                receipt["added_rows"] == 134,
                "v24_populated_commit_failed")
        before = migration.validate_version(db, 2)
        try:
            migration.migrate_step(db, 1)
        except migration.MigrationRejected as err:
            require(str(err) == "data_bearing_downgrade_denied",
                    "unsafe_v24_downgrade_wrong_error")
        else:
            raise V23EvidenceRejected("unsafe_v24_downgrade_allowed")
        after = migration.validate_version(db, 2)
        verified = persist_v24.verify_integrity(db)
        require(before["schema_sha256"] == after["schema_sha256"] and
                verified["total_rows"] == 134 and
                verified["receipt_sha256"] ==
                receipt["integrity"]["receipt_sha256"],
                "blocked_v24_downgrade_modified_data")
        return {
            "total_v24_rows": 134, "downgrade_denied": True,
            "schema_unchanged": True,
            "receipt_sha256": verified["receipt_sha256"],
            "events": verified["events"], "foreign_key_violations": 0,
        }
    return _db_run(run)


def inject_failures() -> dict[str, Any]:
    findings = []
    for start, target, fault in FAULTS:
        def run(db, path):
            migration.migrate_to(db, start)
            previous = migration.validate_version(db, start)
            try:
                migration.migrate_step(db, target, inject_failure=fault)
            except migration.MigrationRejected as err:
                require(str(err) == "injected_migration_rollback_" + fault,
                        "injected_error_not_expected")
            else:
                raise V23EvidenceRejected("fault_injection_not_detected")
            current = migration.validate_version(db, start)
            require(previous["schema_sha256"] ==
                    current["schema_sha256"] and
                    previous["tables"] == current["tables"] and
                    previous["triggers"] == current["triggers"],
                    "ddl_failed_step_not_rolled_back")
            # Reopen and inspect user_version and table inventory after failure.
            db2 = migration.connect(path)
            try:
                reopened = migration.validate_version(db2, start)
            finally:
                db2.close()
            require(reopened["schema_sha256"] == previous["schema_sha256"],
                    "schema_rollback_not_preserved_after_reopen")
            resumed = migration.migrate_step(db, target)
            require(resumed["to"] == target,
                    "post_rollback_migration_unusable")
            return {
                "fault": fault, "from": start, "to": target,
                "transaction_rolled_back": True,
                "reopen_schema_unchanged": True,
                "recovery_migration_passed": True,
            }
        findings.append(_db_run(run))
    return {"injections": 4, "all_rolled_back": True,
            "cases": findings}


def generate(*, require_prior_report: bool = False) -> dict[str, Any]:
    contract = migration.policy()
    migration.validate_policy(contract)

    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"] == 18,
            "v10_frozen_files_changed")
    upstream = verify_v21.source_approvals(
        require_v20_report=require_prior_report
    )
    require(upstream["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            upstream["v21_formal_phase_03_authorized"] is False,
            "phase_approval_falsely_claimed")

    # V22 human review was not signed; its technical report was uploaded
    # on the V22/V24 base and is regenerated by CI on this exact branch.
    if require_prior_report:
        try:
            v22 = json.loads(
                (PROJECT/"evidence/V22/identity_reference_validation.json")
                .read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V23EvidenceRejected("missing_v22_evidence") from None
        require(v22.get("increment") == "V22" and
                v22.get("review_status") ==
                "CANDIDATE_IDENTITY_POLICY_HUMAN_REVIEW_PENDING" and
                v22.get("v23_formal_migration_approved") is False,
                "upstream_identity_signoff_not_pending")

    _, hashes = lineage_v16.load_source_documents()
    before = {
        k:hashlib.sha256((PROJECT/k).read_bytes()).hexdigest()
        for k in hashes
    }
    require(before == hashes, "synthetic_source_hash_drift")

    empty = empty_roundtrip()
    fixture = populated_v21_roundtrip()
    v24 = populated_v24_downgrade_refused()
    failed = inject_failures()
    after = {
        k:hashlib.sha256((PROJECT/k).read_bytes()).hexdigest()
        for k in hashes
    }
    require(before == after and
            fixture["record_digest_unchanged"] and
            fixture["source_records"] == 120 and
            v24["total_v24_rows"] == 134 and
            failed["injections"] == 4 and
            empty["restored_v0_schema_matches"],
            "v23_migration_integrity_evidence_failed")

    return {
        "increment":"V23",
        "objective":"Implement reversible schema migration path",
        "required_proof":"Up/down migration evidence",
        "result":"synthetic_up_down_migrations_verified_human_approval_pending",
        "technical_evidence":"PASS",
        "up_steps_verified":2,
        "down_steps_verified":2,
        "fault_injections_rolled_back":4,
        "retained_synthetic_v21_rows":120,
        "committed_v24_rows_protected":134,
        "nonempty_destructive_downgrades_denied":2,
        "schema_v2_tables":13,
        "schema_v2_triggers":6,
        "empty_roundtrip":empty,
        "populated_v21":fixture,
        "populated_v24":v24,
        "rollback_tests":failed,
        "source_fixtures_sha256":before,
        "source_fixtures_unchanged":True,
        "frozen_v10_source_paths":18,
        "v10_formal_promotion":False,
        "v20_data_quality_signoff":False,
        "v21_entity_schema_review":False,
        "v22_identity_policy_review":False,
        "v23_human_migration_review":"PENDING",
        "v24_human_persistence_review":"PENDING",
        "customer_data_authorized":False,
        "production_migration_authorized":False,
        "actual_power_failure_tested":False,
        "original_v24_bootstrap_integration":False,
        "github_sha":os.environ.get("GITHUB_SHA","not_provided"),
        "limitations":contract["limitations"],
    }


def main() -> int:
    data = generate(require_prior_report=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        key:value for key,value in data.items()
        if key not in ("empty_roundtrip","populated_v21","populated_v24",
                       "rollback_tests")
    }, sort_keys=True,indent=2)+"\n",encoding="utf-8")
    MATRIX.write_text(json.dumps({
        "increment":"V23",
        "required_proof":data["required_proof"],
        "empty_roundtrip":data["empty_roundtrip"],
        "populated_v21_data_preservation":data["populated_v21"],
        "populated_v24_refuses_destructive_rollback":data["populated_v24"],
        "fault_injection_matrix":data["rollback_tests"],
        "human_migration_review":"PENDING",
        "real_customer_data":False,
    },sort_keys=True,indent=2)+"\n",encoding="utf-8")
    PACKET.write_text(json.dumps({
        "increment":"V23",
        "required_proof":"Up/down migration evidence",
        "review_state":"UNSIGNED_TECHNICAL_CANDIDATE",
        "technical_verification":"PASS",
        "human_reviewed":False,
        "reviewer_id":None,
        "signed_at_utc":None,
        "signature":None,
        "v10_formal_gate_approved":False,
        "v20_data_quality_gate_approved":False,
        "v21_and_v22_reviewed":False,
        "v24_rewired_to_migration_runner":False,
        "production_schema_changes_authorized":False,
        "customer_data_authorized":False,
        "limitations":data["limitations"],
    },sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("V23_UP_DOWN_MIGRATIONS: "+json.dumps({
        "technical":"PASS",
        "up_steps":2,"down_steps":2,
        "rollback_injections":4,
        "preserved_v21_rows":120,
        "protected_populated_v24_rows":134,
        "unsafe_downgrades_denied":2,
        "source_files_unchanged":True,
        "human_review":"PENDING",
        "v20_signoff":"BLOCKED",
        "production_migration_authorized":False,
    },sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (V23EvidenceRejected,migration.MigrationRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            sqlite3.Error, OSError, UnicodeError,
            ValueError, KeyError, TypeError):
        print("V23_UP_DOWN_MIGRATIONS_FAILED: migration_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
