"""V24.1: independent proof V23 migrations now initialize V24 temp persistence.

The V24.1 integration is synthetic-only; it does not grant source access,
sign historical approvals, certify crash durability, or change the V9 runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Callable

import entity_v21
import gate_v20
import lineage_v16
import migrate_v23
import persist_v24
import verify_v10
import verify_v21

PROJECT = Path(__file__).resolve().parents[1]
CONTRACT = PROJECT / "docs/data/MIGRATION_INTEGRATION_V24_1.json"
OUTPUT = PROJECT / "evidence/V24_1"
REPORT = OUTPUT / "migration_persistence_integration.json"
SCENARIOS = OUTPUT / "bootstrap_and_recovery_matrix.json"
REVIEW = OUTPUT / "unsigned_v24_1_review.json"


class V241Rejected(ValueError):
    """A fixed diagnostic, never arbitrary user or database content."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise V241Rejected(code)


def policy() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V241Rejected("v241_contract_unavailable") from None
    require(type(value) is dict, "v241_contract_not_object")
    return value


def validate_policy(value: dict[str, Any]) -> None:
    require(type(value) is dict and
            value.get("schema_version") == "1.0.0" and
            value.get("increment") == "V24.1" and
            value.get("objective") ==
            "Integrate V23 schema migrator into V24 temporary persistence initialization without changing V9 runtime, customer access, or synthetic dataset" and
            value.get("required_proof") ==
            "Combined migration + transaction regression, rollback/reopen evidence, and unsigned human review packet" and
            value.get("status") ==
            "SYNTHETIC_INTEGRATION_TECHNICALLY_TESTABLE_HUMAN_REVIEW_PENDING" and
            value.get("branch_base") ==
            "feature/reliability-intelligence-v22" and
            value.get("migration_engine") == "scripts/migrate_v23.py" and
            value.get("bootstrap_engine") == "scripts/persist_v24.py:bootstrap" and
            value.get("schema_marker") == "PRAGMA user_version = 2" and
            value.get("historical_contract_is_superseded_for_bootstrap_only") is True,
            "v241_policy_identity_drift")
    require(value.get("historical_v24_contract") ==
            "docs/data/PERSISTENCE_CONTRACT_V24.json" and
            value.get("allowlisted_test_temp_file") ==
            "mavenu-v24-*/v24_synthetic.sqlite3",
            "v241_sources_or_path_changed")
    starts = value.get("startup_policies")
    require(type(starts) is dict and len(starts) == 7 and
            starts.get("v0_empty") ==
            "upgrade 0→1 then 1→2 (two separately committed adjacent migrations)" and
            starts.get("v1_empty") ==
            "resume 1→2 (single adjacent migration)" and
            starts.get("v1_with_any_data") ==
            "reject without modifying data or version" and
            starts.get("v2_existing") ==
            "reject bootstrap; use existing commit/replay path without schema mutation" and
            starts.get("corrupted_or_unknown_schema") ==
            "reject before any migration" and
            starts.get("non_temp_file") == "reject" and
            "whole request NOT atomic" in starts.get("migration_failure", ""),
            "v241_startup_safety_rule_drift")
    require(value.get("expected") == {
        "version_after_bootstrap":2,"base_tables":10,"ledger_tables":3,
        "triggers":6,"expected_storage_rows":134,
        "expected_source_rows":120,"expected_events":12,
        "expected_receipts":1,"expected_batches":1,
        "existing_v23_up_down_steps":4,
        "existing_v23_fault_injections":4,
        "existing_v24_transaction_scenarios":3,
        "existing_v24_rollback_injections":2,
        "added_integration_scenarios":8,"replay_duplicate_rows":0,
    }, "v241_evidence_counts_drift")
    bounds = value.get("boundaries")
    require(type(bounds) is dict, "v241_boundaries_missing")
    for key in ("sqlite_only","disposable_files_only","fixture_data_only"):
        require(bounds.get(key) is True,"v241_synthetic_scope_reduced")
    for key in ("customer_data_authorized","production_database_authorized",
                "tenant_authentication_implemented","real_power_loss_verified",
                "durable_migration_backup_proven","live_cmms_erp_ot_writes",
                "v10_human_promotion_approved","v20_data_quality_signed",
                "v21_entity_reviewed","v22_identity_reviewed",
                "v23_migration_reviewed","v24_storage_reviewed",
                "v24_1_integration_reviewed"):
        require(bounds.get(key) is False,
                "v241_fabricated_production_or_human_authorization")
    for key in ("review_owner","independent_reviewer",
                "reviewed_at_utc","signature"):
        require(bounds.get(key) is None, "v241_fake_signoff")
    require(type(value.get("risks")) is list and len(value["risks"]) >= 5,
            "v241_risk_inventory_incomplete")


def _run_in_file(fn: Callable[[sqlite3.Connection, Path], dict[str, Any]]
                 ) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as directory:
        path = Path(directory) / persist_v24.NAME
        db = persist_v24.connect(path)
        try:
            result = fn(db, path)
            require(path.exists(), "temporary_sqlite_file_not_created")
        finally:
            db.close()
    require(not path.exists(), "temporary_db_survived_cleanup")
    return result


def _final(db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    state = migrate_v23.validate_version(db, 2)
    persisted = persist_v24.commit_snapshot(db)
    expected = persisted["integrity"]
    require(expected["total_rows"] == 134 and
            expected["records"] == 120 and
            expected["events"] == 12 and
            persisted["write_result"] == "COMMITTED",
            "migrated_persistence_commit_invalid")
    db2 = persist_v24.connect(path)
    try:
        reopened = persist_v24.verify_integrity(
            db2, expected_manifest=expected["source_manifest_sha256"])
        replay = persist_v24.commit_snapshot(db2)
        require(replay["write_result"] == "ALREADY_COMMITTED" and
                replay["added_rows"] == 0 and
                reopened["receipt_sha256"] == expected["receipt_sha256"] and
                migrate_v23.validate_version(db2, 2)["schema_sha256"] ==
                state["schema_sha256"],
                "migrated_db_reopen_or_idempotency_failed")
    finally:
        db2.close()
    return {
        "version":2,"tables":state["tables"],
        "triggers":state["triggers"],
        "schema_sha256":state["schema_sha256"],
        "committed_rows":expected["total_rows"],
        "receipt_sha256":expected["receipt_sha256"],
        "reopen_receipt_matches":True,
        "replay_additional_rows":0,
        "no_customer_data":True,
    }


def scenario_clean_v0(db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    require(migrate_v23.validate_version(db, 0)["tables"] == 0,
            "not_a_clean_v0_database")
    persist_v24.bootstrap(db)
    return {"scenario":"clean_v0_to_v2","result":"PASS",
            "migration_steps":2,**_final(db, path)}


def scenario_empty_v1(db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    migrate_v23.migrate_step(db, 1)
    persist_v24.bootstrap(db)
    return {"scenario":"empty_v1_resumes_to_v2","result":"PASS",
            "migration_steps":1,**_final(db, path)}


def scenario_failed_upgrade_then_resume(
        db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    migrate_v23.migrate_step(db, 1)
    before = migrate_v23.validate_version(db, 1)
    try:
        migrate_v23.migrate_step(
            db, 2, inject_failure="up_v2_after_1_ledger")
    except migrate_v23.MigrationRejected as error:
        require(str(error) ==
                "injected_migration_rollback_up_v2_after_1_ledger",
                "unexpected_migration_failure")
    else:
        raise V241Rejected("injected_upgrade_not_rejected")
    require(migrate_v23.validate_version(db, 1)["schema_sha256"] ==
            before["schema_sha256"],"migration_failure_partial_schema")
    db2 = persist_v24.connect(path)
    try:
        require(migrate_v23.validate_version(db2, 1)["schema_sha256"] ==
                before["schema_sha256"],
                "migration_failure_partial_schema_after_reopen")
    finally:
        db2.close()
    persist_v24.bootstrap(db)
    return {"scenario":"failed_v1_to_v2_upgrade_then_resume",
            "result":"PASS","migration_steps":1,
            "interrupted_upgrade_rolled_back":True,**_final(db,path)}


def scenario_populated_v1_refusal(
        db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    migrate_v23.migrate_step(db, 1)
    staged = entity_v21.load_synthetic_preview(
        db, entity_v21.load_model())
    require(staged["total_rows"] == 120,
            "populated_v1_source_inventory_invalid")
    before = migrate_v23.validate_version(db, 1)
    before_digest = persist_v24.records_sha(db)
    try:
        persist_v24.bootstrap(db)
    except persist_v24.PersistenceRejected as error:
        require(str(error) == "nonempty_v1_bootstrap_denied",
                "populated_v1_rejection_incorrect")
    else:
        raise V241Rejected("populated_v1_bootstrap_was_allowed")
    require(migrate_v23.validate_version(db, 1)["schema_sha256"] ==
            before["schema_sha256"] and
            persist_v24.records_sha(db) == before_digest,
            "refused_bootstrap_modified_source_data")
    return {"scenario":"populated_v1_refused_without_data_loss",
            "result":"PASS","retained_rows":120,
            "migrated":False,"schema_version":1}


def scenario_existing_v2_refusal(
        db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    migrate_v23.migrate_to(db,2)
    before = migrate_v23.validate_version(db,2)
    try:
        persist_v24.bootstrap(db)
    except persist_v24.PersistenceRejected as error:
        require(str(error)=="existing_schema_bootstrap_denied",
                "existing_v2_rejection_incorrect")
    else:
        raise V241Rejected("existing_v2_bootstrap_allowed")
    require(migrate_v23.validate_version(db,2)["schema_sha256"] ==
            before["schema_sha256"],
            "existing_v2_changed_on_refusal")
    return {"scenario":"existing_v2_rejects_bootstrap",
            "result":"PASS","schema_version":2,**_final(db,path)}


def scenario_unknown_version_refusal(
        db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    db.execute("PRAGMA user_version=99")
    try:
        persist_v24.bootstrap(db)
    except migrate_v23.MigrationRejected as error:
        require(str(error)=="unknown_schema_version",
                "unknown_version_rejection_incorrect")
    else:
        raise V241Rejected("unknown_version_bootstrap_allowed")
    require(db.execute("PRAGMA user_version").fetchone()[0]==99,
            "unknown_version_changed_by_denial")
    return {"scenario":"unknown_version_rejected",
            "result":"PASS","unknown_version_unchanged":True}


def scenario_unknown_schema_refusal(
        db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    db.execute("CREATE TABLE unknown_table (id INTEGER)")
    before = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    try:
        persist_v24.bootstrap(db)
    except migrate_v23.MigrationRejected as error:
        require(str(error)=="unexpected_physical_schema",
                "unknown_schema_rejection_incorrect")
    else:
        raise V241Rejected("unknown_schema_bootstrap_allowed")
    require(before==db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0],"unknown_schema_changed")
    return {"scenario":"unexpected_schema_rejected",
            "result":"PASS","unexpected_table_retained":True}


def scenario_existing_populated_v2_refusal(
        db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    persist_v24.bootstrap(db)
    written = persist_v24.commit_snapshot(db)
    before = migrate_v23.validate_version(db,2)
    try:
        persist_v24.bootstrap(db)
    except persist_v24.PersistenceRejected as error:
        require(str(error)=="existing_schema_bootstrap_denied",
                "populated_v2_rejection_incorrect")
    else:
        raise V241Rejected("populated_v2_reinitialized")
    receipt = persist_v24.verify_integrity(db)
    require(receipt["receipt_sha256"] ==
            written["integrity"]["receipt_sha256"] and
            migrate_v23.validate_version(db,2)["schema_sha256"] ==
            before["schema_sha256"],
            "populated_v2_data_or_schema_modified")
    return {"scenario":"populated_v2_refuses_rebootstrap",
            "result":"PASS","retained_rows":134,
            "receipt_preserved":True}


CASES = (
    scenario_clean_v0,scenario_empty_v1,
    scenario_failed_upgrade_then_resume,
    scenario_populated_v1_refusal,
    scenario_existing_v2_refusal,
    scenario_unknown_version_refusal,
    scenario_unknown_schema_refusal,
    scenario_existing_populated_v2_refusal,
)


def generate(*, require_prior_reports: bool = False) -> dict[str, Any]:
    cfg = policy()
    validate_policy(cfg)
    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE))
    require(frozen["frozen_files_verified"]==18,"v10_frozen_source_drift")
    approvals = verify_v21.source_approvals(
        require_v20_report=require_prior_reports)
    require(approvals["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF",
            "data_quality_signoff_falsely_claimed")
    if require_prior_reports:
        for label, path in (
            ("V23","evidence/V23/up_down_migration_report.json"),
            ("V24","evidence/V24/transactional_integrity_report.json"),
        ):
            try:
                evidence = json.loads(
                    (PROJECT/path).read_text(encoding="utf-8"))
            except (OSError,UnicodeError,json.JSONDecodeError):
                raise V241Rejected("prior_migration_persistence_report_missing") from None
            require(evidence.get("increment")==label and
                    evidence.get("technical_evidence")=="PASS",
                    "prior_technical_report_not_passed")
            if label=="V23":
                require(evidence.get("up_steps_verified")==2 and
                        evidence.get("down_steps_verified")==2 and
                        evidence.get("fault_injections_rolled_back")==4 and
                        evidence.get("v23_human_migration_review")=="PENDING",
                        "v23_migration_baseline_mismatch")
            else:
                require(evidence.get("scenario_count")==3 and
                        evidence.get("committed_fabricated_records")==120 and
                        evidence.get("committed_fabricated_events")==12 and
                        evidence.get("duplicate_replay_additional_rows")==0,
                        "v24_transaction_baseline_mismatch")
    _, source_hashes = lineage_v16.load_source_documents()
    original_hashes = {
        k:hashlib.sha256((PROJECT/k).read_bytes()).hexdigest()
        for k in source_hashes
    }
    require(original_hashes==source_hashes,"preexisting_source_digest_change")
    findings = [_run_in_file(s) for s in CASES]
    final_hashes = {
        k:hashlib.sha256((PROJECT/k).read_bytes()).hexdigest()
        for k in source_hashes
    }
    require(original_hashes==final_hashes and
            len(findings)==cfg["expected"]["added_integration_scenarios"] and
            all(x["result"]=="PASS" for x in findings),
            "integration_scenario_mismatch")
    committed = [x for x in findings if x.get("committed_rows")==134]
    require(len(committed)==4 and
            len({x["receipt_sha256"] for x in committed})==1 and
            all(x.get("replay_additional_rows")==0 for x in committed),
            "integration_migrated_replay_drift")
    return {
        "increment":"V24.1",
        "objective":cfg["objective"],
        "required_proof":cfg["required_proof"],
        "result":"v23_migration_integrated_into_v24_synthetic_bootstrap",
        "technical_evidence":"PASS",
        "schema_version":2,
        "migration_engine":"scripts/migrate_v23.py",
        "v24_bootstrap_uses_v23_runner":True,
        "integration_scenarios":len(findings),
        "reopen_committed_scenarios":len(committed),
        "expected_v21_entity_tables":10,
        "expected_v24_ledger_tables":3,
        "expected_v24_immutable_triggers":6,
        "migration_preserves_populated_v1_on_refusal":True,
        "migrated_v24_receipt_identical_across_scenarios":True,
        "duplicate_replay_additional_rows":0,
        "v10_frozen_files":18,
        "source_fixtures_unchanged":True,
        "source_file_sha256":original_hashes,
        "findings":findings,
        "v23_and_v24_formal_human_review":"PENDING",
        "v20_formal_signoff":"BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v24_1_signoff_obtained":False,
        "customer_data_authorized":False,
        "production_migration_authorized":False,
        "actual_power_loss_tested":False,
        "github_sha":os.environ.get("GITHUB_SHA","not_provided"),
        "risks":cfg["risks"],
    }


def main() -> int:
    report = generate(require_prior_reports=True)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps({
        k:v for k,v in report.items() if k!="findings"
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    SCENARIOS.write_text(json.dumps({
        "increment":"V24.1",
        "scenario_count":len(report["findings"]),
        "scenarios":report["findings"],
        "all_passed":True,
        "human_review":"PENDING",
        "customer_data_used":False,
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    REVIEW.write_text(json.dumps({
        "increment":"V24.1",
        "technical_result":"PASS",
        "status":"UNSIGNED_INTEGRATION_REVIEW_REQUEST",
        "signoff":False,
        "named_architect":None,
        "named_database_administrator":None,
        "reviewed_at_utc":None,
        "signature":None,
        "v20_formal_signoff":"BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v23_migration_approved":False,
        "v24_storage_approved":False,
        "v24_1_formal_approval":False,
        "customer_data_authorized":False,
        "production_migration_authorized":False,
        "risks":report["risks"],
    },indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("V24_1_MIGRATION_INTEGRATION: "+json.dumps({
        "technical":"PASS",
        "scenarios":report["integration_scenarios"],
        "committed_scenarios":report["reopen_committed_scenarios"],
        "schema_version":report["schema_version"],
        "replay_added_rows":report["duplicate_replay_additional_rows"],
        "v23_runtime_integrated":True,
        "human_review":"PENDING",
        "v20_signoff":"BLOCKED",
        "production_authorized":False,
    },sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (V241Rejected,persist_v24.PersistenceRejected,
            migrate_v23.MigrationRejected,
            verify_v10.DecisionEvidenceError,
            verify_v21.V21EvidenceRejected,
            OSError,UnicodeError,KeyError,TypeError,
            ValueError,sqlite3.Error):
        print("V24_1_MIGRATION_INTEGRATION_FAILED: migration_or_approval_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
