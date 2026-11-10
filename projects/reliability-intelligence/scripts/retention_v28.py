"""V28 — synthetic retention/archive/purge and legal-hold reference engine.

Architecture V4 p43: Enforce retention, deletion and archives.
Required proof: Retention-policy tests.

This sidecar is a disposable SQLite TEST store, not a V23 schema change or a
production retention service. V26 source data and V27 backups are untouched.
Holds and reviewers are synthetic; DB DELETE is not certified secure erasure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import isolation_v26
import migrate_v23
import persist_v24

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/data/RETENTION_POLICY_V28.json"
NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
NOW_TXT = "2026-11-10T12:00:00Z"
FILE = "v28_lifecycle.sqlite3"
CLASSES = ("case_summary", "evidence_reference")
RETENTION = {"case_summary":(30,90), "evidence_reference":(14,90)}
AGES = {"001":5, "002":40, "003":120}
REVIEWER = "SYN-REVIEWER-LEGAL-001"
KEYS = ("tenant_id","site_id","case_id","data_class")
HOLD_TARGETS = (
    ("SYN-TENANT-001","SYN-SITE-001","SYN-CASE-003","case_summary"),
    ("SYN-TENANT-002","SYN-SITE-002","SYN-CASE-003","evidence_reference"),
)
SCHEMA = """
CREATE TABLE active_record (
 tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, case_id TEXT NOT NULL,
 data_class TEXT NOT NULL CHECK(data_class IN ('case_summary','evidence_reference')),
 event_at_utc TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 PRIMARY KEY(tenant_id,site_id,case_id,data_class)
);
CREATE TABLE archive_record (
 tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, case_id TEXT NOT NULL,
 data_class TEXT NOT NULL CHECK(data_class IN ('case_summary','evidence_reference')),
 event_at_utc TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 archived_at_utc TEXT NOT NULL,
 PRIMARY KEY(tenant_id,site_id,case_id,data_class)
);
CREATE TABLE legal_hold (
 tenant_id TEXT NOT NULL, site_id TEXT NOT NULL, case_id TEXT NOT NULL,
 data_class TEXT NOT NULL, reason_code TEXT NOT NULL,
 placed_at_utc TEXT NOT NULL,
 PRIMARY KEY(tenant_id,site_id,case_id,data_class)
);
CREATE TABLE purge_tombstone (
 object_sha256 TEXT NOT NULL PRIMARY KEY,
 data_class TEXT NOT NULL, purged_at_utc TEXT NOT NULL
);
CREATE TABLE audit_event (
 sequence INTEGER PRIMARY KEY, action TEXT NOT NULL, object_sha256 TEXT NOT NULL,
 occurred_at_utc TEXT NOT NULL, previous_sha256 TEXT NOT NULL,
 event_sha256 TEXT NOT NULL
);
CREATE TRIGGER v28_audit_no_update BEFORE UPDATE ON audit_event
 BEGIN SELECT RAISE(ABORT,'audit_append_only'); END;
CREATE TRIGGER v28_audit_no_delete BEFORE DELETE ON audit_event
 BEGIN SELECT RAISE(ABORT,'audit_append_only'); END;
"""
TABLES = {"active_record","archive_record","legal_hold",
          "purge_tombstone","audit_event"}
TRIGGERS = {"v28_audit_no_update","v28_audit_no_delete"}


class RetentionRejected(ValueError):
    """Fixed diagnostic. No user-controlled contents in error messages."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise RetentionRejected(code)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",",":"), ensure_ascii=True
    ).encode("ascii")).hexdigest()


def policy() -> dict[str, Any]:
    try:
        p = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError):
        raise RetentionRejected("v28_contract_unavailable") from None
    require(type(p) is dict,"v28_contract_not_object")
    return p


def validate_policy(p: dict[str, Any]) -> None:
    require(type(p) is dict and p.get("schema_version")=="1.0.0" and
            p.get("increment")=="V28" and
            p.get("objective")=="Enforce retention, deletion and archives" and
            p.get("required_proof")=="Retention-policy tests" and
            p.get("state")==
            "SYNTHETIC_LIFECYCLE_PROTOTYPE_HUMAN_REVIEW_PENDING" and
            p.get("branch_base")==
            "feature/reliability-intelligence-v22",
            "v28_objective_or_status_drift")
    d=p.get("storage_design")
    require(type(d) is dict and
            d.get("source") ==
            "V26 38-row invented tenant/site relational fixture in temporary V23/V24.1 schema version 2" and
            d.get("lifecycle") ==
            "isolated disposable SQLite file mavenu-v28-*/v28_lifecycle.sqlite3, NOT a V23 schema upgrade or production archive" and
            d.get("reference_timestamp_utc")==NOW_TXT and
            d.get("retention_clock")==
            "synthetic lifecycle age assigned by case suffix; source occurred_at_utc is NOT treated as observed real-world history" and
            d.get("categories") == [
                {"data_class":"case_summary","archive_after_days":30,
                 "purge_after_days":90},
                {"data_class":"evidence_reference","archive_after_days":14,
                 "purge_after_days":90}
            ] and d.get("age_cohorts")==[
                {"case_suffix":"001","age_days":5},
                {"case_suffix":"002","age_days":40},
                {"case_suffix":"003","age_days":120}
            ] and d.get("fake_tenants")==2 and
            d.get("sites_per_tenant")==2 and
            d.get("cases_per_scope")==3 and
            d.get("classes_per_case")==2 and
            d.get("synthetic_records")==24 and
            d.get("hold_reviewer")==REVIEWER+" (NOT AUTHENTICATED)" and
            d.get("hold_targets")==[
                dict(zip(KEYS,key)) for key in HOLD_TARGETS
            ] and d.get("failure_injections")==[
                "after_first_transition","after_first_purge"] and
            d.get("immutable_audit_chain") is True and
            d.get("delete_tombstones_sha256_only") is True and
            d.get("no_real_backup_deletion") is True and
            d.get("no_customer_records") is True and
            d.get("no_source_db_mutation") is True and
            d.get("no_real_schedule") is True and
            d.get("host_migration_version_unchanged") is True and
            d.get("audit_is_not_externally_signed") is True and
            d.get("secure_erase_of_old_db_pages_unverified") is True,
            "v28_storage_or_lifecycle_scope_drift")
    require(d.get("expected_after_enforcement")=={
        "active":10,"archived":8,"purged":6,
        "active_held":2,"holds":2,"events":16
    } and d.get("expected_after_authorized_simulated_hold_release")=={
        "active":8,"archived":8,"purged":8,"holds":0,"events":20
    },"v28_expected_counts_drift")
    gov=p.get("decision")
    require(type(gov) is dict and
            gov.get("proposed_only") is True,
            "v28_governance_missing")
    for name in (
        "customer_data_owner_approved","retention_period_approved",
        "legal_hold_authority_approved","deletion_or_export_rights_approved",
        "backup_retention_approved","production_data_lifecycle_authorized",
        "authenticated_reviewer_implemented","customer_access_authorized",
        "independent_v28_review_approved","v10_formal_promotion",
        "v20_data_quality_signoff","v21_v27_human_reviews_complete"
    ):
        require(gov.get(name) is False,"v28_false_human_or_legal_approval")
    for name in (
        "owner","security_reviewer","legal_reviewer",
        "approved_at_utc","signature"
    ):
        require(gov.get(name) is None,"v28_fabricated_signature")
    require(type(p.get("risks")) is list and len(p["risks"])>=6 and
            type(p.get("human_readiness_gates")) is list and
            len(p["human_readiness_gates"])>=6,
            "v28_review_requirements_missing")


def connect_lifecycle(path: Path) -> sqlite3.Connection:
    require(isinstance(path,Path) and path.name==FILE and
            path.parent.is_dir() and not path.is_symlink() and
            path.parent.resolve().parent ==
                Path(tempfile.gettempdir()).resolve() and
            path.parent.name.startswith("mavenu-v28-"),
            "unapproved_lifecycle_storage_path")
    db=sqlite3.connect(str(path.resolve()),isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA secure_delete=ON")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0]==1 and
            db.execute("PRAGMA synchronous").fetchone()[0]==2,
            "lifecycle_sqlite_pragmas_missing")
    return db


def _validate_location(db: sqlite3.Connection) -> None:
    require(isinstance(db,sqlite3.Connection),
            "not_a_sqlite_lifecycle_connection")
    main=[x[2] for x in db.execute("PRAGMA database_list") if x[1]=="main"]
    require(len(main)==1 and main[0] and
            Path(main[0]).name==FILE and
            Path(main[0]).parent.resolve().parent ==
                Path(tempfile.gettempdir()).resolve() and
            Path(main[0]).parent.name.startswith("mavenu-v28-"),
            "non_disposable_lifecycle_connection")


def initialize(db: sqlite3.Connection) -> None:
    _validate_location(db)
    found=db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    require(found==0,"lifecycle_store_not_empty")
    db.executescript(SCHEMA)
    check(db)


def check(db: sqlite3.Connection) -> dict[str, Any]:
    _validate_location(db)
    tables={x[0] for x in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    triggers={x[0] for x in db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}
    require(tables==TABLES and triggers==TRIGGERS,
            "unexpected_lifecycle_schema")
    require(db.execute("PRAGMA foreign_keys").fetchone()[0]==1 and
            db.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
            "lifecycle_sqlite_integrity_failed")
    assert_chain(db)
    return {"tables":len(tables),"triggers":len(triggers),
            "audit_chain":"VALID","integrity":"ok"}


def object_hash(key: tuple[str,str,str,str]) -> str:
    require(type(key) is tuple and len(key)==4 and
            all(type(x) is str for x in key) and
            re.fullmatch(r"SYN-TENANT-[0-9]{3}",key[0]) and
            re.fullmatch(r"SYN-SITE-[0-9]{3}",key[1]) and
            re.fullmatch(r"SYN-CASE-[0-9]{3}",key[2]) and
            key[3] in CLASSES,
            "invalid_lifecycle_object_key")
    return digest(list(key))


def _audit(db: sqlite3.Connection,action: str,
           key: tuple[str,str,str,str],at: str) -> None:
    require(action in (
        "HOLD_PLACED","ARCHIVED","PURGED","HOLD_RELEASED"
    ),"invalid_audit_action")
    prev=db.execute(
        "SELECT sequence,event_sha256 FROM audit_event "
        "ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    seq=1 if prev is None else prev[0]+1
    prior="0"*64 if prev is None else prev[1]
    opaque=object_hash(key)
    record={"sequence":seq,"action":action,"object_sha256":opaque,
            "occurred_at_utc":at,"previous_sha256":prior}
    db.execute(
        "INSERT INTO audit_event VALUES (?,?,?,?,?,?)",
        (seq,action,opaque,at,prior,digest(record))
    )


def assert_chain(db: sqlite3.Connection) -> int:
    prior="0"*64
    count=0
    for seq,action,opaque,at,prev_hash,event_hash in db.execute(
            "SELECT sequence,action,object_sha256,occurred_at_utc,"
            "previous_sha256,event_sha256 "
            "FROM audit_event ORDER BY sequence"):
        count+=1
        require(seq==count and prev_hash==prior,
                "lifecycle_audit_link_broken")
        require(event_hash==digest({
            "sequence":seq,"action":action,"object_sha256":opaque,
            "occurred_at_utc":at,"previous_sha256":prior
        }),"lifecycle_audit_hash_invalid")
        prior=event_hash
    return count


def _rows(db:sqlite3.Connection, table:str) -> list[tuple[Any,...]]:
    require(table in ("active_record","archive_record"),
            "invalid_lifecycle_table")
    return db.execute(
        "SELECT tenant_id,site_id,case_id,data_class,"
        "event_at_utc,payload_sha256 FROM "+table+
        " ORDER BY tenant_id,site_id,case_id,data_class"
    ).fetchall()


def state(db:sqlite3.Connection) -> dict[str,Any]:
    result={name:db.execute("SELECT COUNT(*) FROM "+name).fetchone()[0]
            for name in TABLES}
    held=db.execute(
        "SELECT COUNT(*) FROM legal_hold h JOIN active_record a "
        "ON a.tenant_id=h.tenant_id AND a.site_id=h.site_id "
        "AND a.case_id=h.case_id AND a.data_class=h.data_class"
    ).fetchone()[0]
    require(result["legal_hold"]==held,
            "held_record_not_in_active_storage")
    require(result["active_record"]+result["archive_record"]+
            result["purge_tombstone"]==24,
            "record_lifecycle_inventory_inconsistent")
    assert_chain(db)
    return {
        "active":result["active_record"],
        "archived":result["archive_record"],
        "purged":result["purge_tombstone"],
        "holds":result["legal_hold"],
        "active_held":held,
        "events":result["audit_event"],
    }


def _event_at_for_case(case_id:str) -> str:
    require(case_id.startswith("SYN-CASE-") and
            case_id[-3:] in AGES,"unknown_synthetic_cohort")
    return (NOW-timedelta(days=AGES[case_id[-3:]])).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def seed_from_v26(db:sqlite3.Connection, source:sqlite3.Connection) -> None:
    """Read the V26 fixture; copy only synthetic hashes into sidecar."""
    _validate_location(db)
    migrate_v23.validate_version(source,2)
    require(all(
        db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] == 0
        for table in TABLES
    ), "lifecycle_source_not_empty")
    cases=source.execute(
        "SELECT tenant_id,site_id,case_id,asset_id,work_order_ref "
        "FROM maintenance_case ORDER BY tenant_id,site_id,case_id"
    ).fetchall()
    evid=source.execute(
        "SELECT tenant_id,site_id,case_id,evidence_ref "
        "FROM evidence_reference ORDER BY tenant_id,site_id,case_id"
    ).fetchall()
    require(len(cases)==12 and len(evid)==12,
            "v26_synthetic_source_not_populated")
    entries=[]
    for tenant,site,case,asset,wo in cases:
        entries.append((tenant,site,case,CLASSES[0],
                        _event_at_for_case(case),
                        digest([tenant,site,case,asset,wo])))
    for tenant,site,case,evidence in evid:
        entries.append((tenant,site,case,CLASSES[1],
                        _event_at_for_case(case),
                        digest([tenant,site,case,evidence])))
    require(len(entries)==24 and
            len({entry[:4] for entry in entries})==24,
            "source_lifecycle_record_collision")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany(
            "INSERT INTO active_record VALUES (?,?,?,?,?,?)",
            entries)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def place_hold(db:sqlite3.Connection,key:tuple[str,str,str,str],
               *,reviewer:str=REVIEWER) -> None:
    require(reviewer==REVIEWER,"not_a_simulated_hold_reviewer")
    object_hash(key)
    found=db.execute(
        "SELECT COUNT(*) FROM active_record WHERE "
        "tenant_id=? AND site_id=? AND case_id=? AND data_class=?",key
    ).fetchone()[0]
    require(found==1,"hold_target_not_in_scoped_active_store")
    require(not db.in_transaction,"nested_lifecycle_transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "INSERT INTO legal_hold VALUES (?,?,?,?,?,?)",
            (*key,"SYN-LEGAL-PRESERVATION",NOW_TXT)
        )
        _audit(db,"HOLD_PLACED",key,NOW_TXT)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def release_hold(db:sqlite3.Connection,key:tuple[str,str,str,str],
                 *,reviewer:str=REVIEWER) -> None:
    require(reviewer==REVIEWER,"not_a_simulated_hold_reviewer")
    object_hash(key)
    require(db.execute(
        "SELECT COUNT(*) FROM legal_hold WHERE "
        "tenant_id=? AND site_id=? AND case_id=? AND data_class=?",key
    ).fetchone()[0]==1,"hold_not_found_in_scope")
    require(not db.in_transaction,"nested_lifecycle_transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "DELETE FROM legal_hold WHERE tenant_id=? AND site_id=? "
            "AND case_id=? AND data_class=?",key)
        _audit(db,"HOLD_RELEASED",key,NOW_TXT)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def enforce(db:sqlite3.Connection, *,
            as_of:str=NOW_TXT,
            inject_failure:str|None=None) -> dict[str,Any]:
    require(as_of==NOW_TXT,"unreviewed_retention_as_of")
    require(inject_failure in (
        None,"after_first_transition","after_first_purge"
    ),"unknown_retention_injection")
    require(not db.in_transaction,"nested_lifecycle_transaction")
    check(db)
    before=state(db)
    actions={"archived":0,"purged":0,"held_skipped":0,
             "not_due":0,"already_archived":0}
    records=(
        [(row,"active") for row in _rows(db,"active_record")]+
        [(row,"archive") for row in _rows(db,"archive_record")]
    )
    records.sort(key=lambda x:x[0][:4])
    db.execute("BEGIN IMMEDIATE")
    transitions=0
    try:
        for (tenant,site,case,cls,created,payload),tier in records:
            key=(tenant,site,case,cls)
            if db.execute(
                "SELECT COUNT(*) FROM legal_hold WHERE tenant_id=? "
                "AND site_id=? AND case_id=? AND data_class=?", key
            ).fetchone()[0]:
                actions["held_skipped"]+=1
                continue
            days=(NOW-datetime.strptime(
                created,"%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)).days
            archive_days,purge_days=RETENTION[cls]
            if days>=purge_days:
                table="active_record" if tier=="active" else "archive_record"
                db.execute(
                    "DELETE FROM "+table+" WHERE tenant_id=? AND "
                    "site_id=? AND case_id=? AND data_class=?",key)
                db.execute(
                    "INSERT INTO purge_tombstone VALUES (?,?,?)",
                    (object_hash(key),cls,NOW_TXT))
                _audit(db,"PURGED",key,NOW_TXT)
                actions["purged"]+=1
                transitions+=1
                if inject_failure=="after_first_purge":
                    raise RetentionRejected("injected_purge_rollback")
            elif days>=archive_days and tier=="active":
                db.execute(
                    "INSERT INTO archive_record VALUES (?,?,?,?,?,?,?)",
                    (tenant,site,case,cls,created,payload,NOW_TXT))
                db.execute(
                    "DELETE FROM active_record WHERE tenant_id=? "
                    "AND site_id=? AND case_id=? AND data_class=?",key)
                _audit(db,"ARCHIVED",key,NOW_TXT)
                actions["archived"]+=1
                transitions+=1
            elif tier=="archive":
                actions["already_archived"]+=1
            else:
                actions["not_due"]+=1
            if inject_failure=="after_first_transition" and transitions==1:
                raise RetentionRejected("injected_transition_rollback")
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        require(state(db)==before,
                "failed_lifecycle_batch_was_not_rolled_back")
        raise
    result=state(db)
    require(result["active"]+result["archived"]+result["purged"]==24,
            "post_enforcement_count_drift")
    return {
        "operations":actions,
        "before":before,
        "after":result,
        "source_rows_modified":False,
        "real_customer_data_deleted":False,
        "physical_erasure_of_disk_proven":False,
    }


def _source_hash(db:sqlite3.Connection)->str:
    rows=db.execute(
        "SELECT tenant_id,site_id,case_id,asset_id,work_order_ref "
        "FROM maintenance_case ORDER BY tenant_id,site_id,case_id"
    ).fetchall()
    return digest(rows)


def run_scenarios()->dict[str,Any]:
    validate_policy(policy())
    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as source_dir:
        srcpath=Path(source_dir)/persist_v24.NAME
        source=persist_v24.connect(srcpath)
        try:
            persist_v24.bootstrap(source)
            original=isolation_v26.seed_isolated_fixture(source)
            require(original["total_rows"]==38,
                    "v26_source_fixture_count_drift")
            initial_src_digest=_source_hash(source)
            with tempfile.TemporaryDirectory(prefix="mavenu-v28-") as directory:
                path=Path(directory)/FILE
                db=connect_lifecycle(path)
                try:
                    initialize(db)
                    seed_from_v26(db,source)
                    require(state(db)=={
                        "active":24,"archived":0,"purged":0,
                        "holds":0,"active_held":0,"events":0
                    },"initial_active_inventory_invalid")
                    for key in HOLD_TARGETS:
                        place_hold(db,key)
                    held_before=state(db)
                    require(held_before["holds"]==2 and
                            held_before["events"]==2,
                            "preenforcement_holds_missing")
                    faults=[]
                    for inject in (
                        "after_first_transition","after_first_purge"
                    ):
                        try:
                            enforce(db,inject_failure=inject)
                        except RetentionRejected as exc:
                            require(str(exc) in (
                                "injected_transition_rollback",
                                "injected_purge_rollback"),
                                "unexpected_lifecycle_fault")
                            faults.append({
                                "injection":inject,"rolled_back":True,
                                "pre_state_recovered":state(db)==held_before
                            })
                        else:
                            raise RetentionRejected("injected_lifecycle_fault_missing")
                    require(all(x["pre_state_recovered"] for x in faults),
                            "lifecycle_rollback_incomplete")
                    pass_one=enforce(db)
                    expected_one=policy()["storage_design"]["expected_after_enforcement"]
                    require(pass_one["after"]==expected_one and
                            pass_one["operations"]["archived"]==8 and
                            pass_one["operations"]["purged"]==6 and
                            pass_one["operations"]["held_skipped"]==2,
                            "retention_transition_counts_unexpected")
                    again=enforce(db)
                    require(again["after"]==expected_one and
                            again["operations"]["archived"]==0 and
                            again["operations"]["purged"]==0,
                            "lifecycle_replay_not_idempotent")
                    # A fake reviewer trying to release the wrong
                    # tenant/site legal hold is rejected.
                    bad_key=("SYN-TENANT-002","SYN-SITE-001",
                             "SYN-CASE-003","case_summary")
                    try:
                        release_hold(db,bad_key)
                    except RetentionRejected as exc:
                        require(str(exc)=="hold_not_found_in_scope",
                                "wrong_scope_hold_error")
                    else:
                        raise RetentionRejected("wrong_scope_hold_released")
                    for key in HOLD_TARGETS:
                        release_hold(db,key)
                    pass_two=enforce(db)
                    expected_two=policy()["storage_design"][
                        "expected_after_authorized_simulated_hold_release"]
                    require(pass_two["after"]==expected_two and
                            pass_two["operations"]["purged"]==2 and
                            pass_two["operations"]["archived"]==0,
                            "released_holds_not_purged")
                    # Audited events cannot be updated/deleted using
                    # normal SQL statements on the sidecar.
                    for sql in (
                        "UPDATE audit_event SET action='FAKE' WHERE sequence=1",
                        "DELETE FROM audit_event WHERE sequence=1",
                    ):
                        try:
                            db.execute(sql)
                        except sqlite3.IntegrityError:
                            pass
                        else:
                            raise RetentionRejected("audit_immutability_bypassed")
                    check(db)
                    require(_source_hash(source)==initial_src_digest,
                            "v26_source_database_modified")
                    output={
                        "increment":"V28",
                        "technical_evidence":"PASS",
                        "source_fixture_rows":38,
                        "lifecycle_records":24,
                        "initial_legal_holds":held_before["holds"],
                        "injection_recoveries":faults,
                        "first_policy_application":pass_one,
                        "idempotent_replay":again,
                        "after_simulated_hold_release":pass_two,
                        "blocked_cross_tenant_hold_release":True,
                        "source_record_digest_sha256":initial_src_digest,
                        "source_not_mutated":True,
                        "sqlite_audit_chain_verified":True,
                        "audit_updates_and_deletes_denied":True,
                        "schema_version_of_source":migrate_v23.validate_version(source,2)["version"],
                        "secure_disk_erasure_verified":False,
                        "customer_data_used":False,
                        "production_retention_authorized":False
                    }
                finally:
                    db.close()
            require(not path.exists(),"retention_sidecar_not_deleted")
            output["sidecar_file_deleted"]=True
        finally:
            source.close()
    require(not srcpath.exists(),"retention_source_file_not_deleted")
    output["source_file_deleted"]=True
    return output
