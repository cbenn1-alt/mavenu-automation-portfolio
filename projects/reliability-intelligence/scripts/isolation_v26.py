"""V26 proposed tenant boundaries and data rights — synthetic-only reference harness.

Architecture V4 p43: Document tenant boundaries and data rights.
Required proof: Isolation design decision.

This is NOT production authentication, authorization, database row-level
security, actual legal rights, or a customer tenant system. All actor IDs,
grant mappings and rows are fabricated. Anyone holding the raw SQLite
connection can bypass application query guards. No OT/CMMS or source writes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import migrate_v23
import persist_v24

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs/data/ISOLATION_DECISION_V26.json"
TENANTS = ("SYN-TENANT-001", "SYN-TENANT-002")
SITES = ("SYN-SITE-001", "SYN-SITE-002")
TENANT_SITE = tuple((t, s) for t in TENANTS for s in SITES)
OPERATIONS = ("read_case_summary", "read_evidence_reference")
DENIED_OPERATIONS = ("write_case", "export_case", "delete_case",
                     "read_source_document", "send_ot_command")
# Fixed grants shipped as code, not read from caller/request-owned fields.
# Still synthetic: actor IDs are not authenticated identities.
GRANTS = {
    "SYN-ACTOR-001": ("site_viewer", {
        (TENANTS[0], SITES[0]): ("read_case_summary",),
    }),
    "SYN-ACTOR-002": ("evidence_reviewer", {
        (TENANTS[0], SITES[1]): OPERATIONS,
    }),
    "SYN-ACTOR-003": ("evidence_reviewer", {
        (TENANTS[1], SITES[0]): OPERATIONS,
    }),
    "SYN-ACTOR-004": ("site_viewer", {
        (TENANTS[1], SITES[1]): ("read_case_summary",),
    }),
    "SYN-ACTOR-005": ("dual_site_viewer", {
        (TENANTS[0], SITES[0]): ("read_case_summary",),
        (TENANTS[0], SITES[1]): ("read_case_summary",),
    }),
    "SYN-ACTOR-006": ("unassigned", {}),
}
SCOPED_QUERIES = {
    "read_case_summary": (
        "SELECT tenant_id, site_id, case_id, asset_id, work_order_ref "
        "FROM maintenance_case WHERE tenant_id=? AND site_id=? "
        "ORDER BY case_id",
        ("tenant_id", "site_id", "case_id", "asset_id", "work_order_ref"),
    ),
    "read_evidence_reference": (
        "SELECT tenant_id, site_id, case_id, evidence_ref "
        "FROM evidence_reference WHERE tenant_id=? AND site_id=? "
        "ORDER BY case_id, evidence_ref",
        ("tenant_id", "site_id", "case_id", "evidence_ref"),
    ),
}
EXPECTED_COUNTS = {
    "tenant": 2, "site": 4, "asset": 8,
    "maintenance_case": 12, "evidence_reference": 12,
}
TOTAL_ROWS = 38


class ScopeDenied(PermissionError):
    """Uniform response to missing/invalid actor, operation or tenant scope."""


class V26InvariantError(ValueError):
    """Invalid design or test-data invariant, never customer data."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V26InvariantError(code)


def load_policy() -> dict[str, Any]:
    try:
        obj = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V26InvariantError("isolation_decision_missing") from None
    require(type(obj) is dict, "isolation_policy_not_object")
    return obj


def _actor_catalog() -> list[dict[str, Any]]:
    rows = []
    for actor_id, (role, grants) in GRANTS.items():
        rows.append({
            "id": actor_id, "role": role,
            "grants": [
                {"tenant_id": tenant, "site_id": site,
                 "operations": list(operations)}
                for (tenant, site), operations in grants.items()
            ],
        })
    return rows


def validate_policy(policy: dict[str, Any]) -> None:
    require(type(policy) is dict and
            policy.get("schema_version") == "1.0.0" and
            policy.get("increment") == "V26" and
            policy.get("objective") ==
            "Document tenant boundaries and data rights" and
            policy.get("required_proof") == "Isolation design decision" and
            policy.get("design_state") == "PROPOSED_NOT_RATIFIED" and
            policy.get("selected_for_synthetic_prototype") ==
            "logical_tenant_site_scoping" and
            policy.get("production_choice") ==
            "UNDECIDED_PENDING_CUSTOMER_AND_SECURITY_REVIEW" and
            policy.get("evidence_scope") ==
            "artificial actors and fabricated SQLite source rows only",
            "v26_objective_or_decision_drift")
    options = policy.get("design_options")
    require(type(options) is list and len(options) == 3 and
            [x.get("key") for x in options if type(x) is dict] ==
            ["logical_tenant_site_scoping", "database_per_tenant",
             "schema_per_tenant"] and
            [x.get("decision") for x in options] ==
            ["PROPOSED_SYNTHETIC_ONLY", "UNSELECTED_OPTION",
             "UNSELECTED_OPTION"] and
            all(len(x.get("benefits", [])) >= 2 and
                len(x.get("risks", [])) >= 3 for x in options),
            "v26_isolation_options_incomplete")
    trust = policy.get("trust_boundaries")
    require(type(trust) is dict and
            trust.get("external_actor_authentication") ==
            "NOT_IMPLEMENTED" and
            trust.get("caller_identity_provider") == "NONE" and
            trust.get("principal_context_origin") ==
            "SYNTHETIC_SERVER_SIDE_TEST_FIXTURE_ONLY" and
            trust.get("row_level_security") == "NOT_IMPLEMENTED" and
            trust.get("unauthorized_response") ==
            "fixed scope_denied error, without existence disclosure" and
            trust.get("production_safety_claim") == "NONE",
            "v26_false_security_assertion")
    inventory = policy.get("inventory")
    require(inventory == {
        "tenants": 2, "sites_per_tenant": 2,
        "assets_per_site": 2, "cases_per_site": 3,
        "evidence_refs_per_case": 1,
        "synthetic_rows": TOTAL_ROWS, "case_rows": 12,
        "evidence_rows": 12, "actors": 6,
        "granted_actor_scopes": 6,
        "case_read_grants": 6, "evidence_read_grants": 2,
        "allowed_operations": list(OPERATIONS),
        "denied_operations": list(DENIED_OPERATIONS),
        "baseline_schema_version": 2,
        "source_files_unchanged": True,
    }, "v26_synthetic_scope_inventory_drift")
    require(policy.get("synthetic_actors") == _actor_catalog(),
            "v26_actor_grants_not_server_owned")
    classes = policy.get("data_classes")
    require(type(classes) is list and len(classes) == 4 and
            [x.get("key") for x in classes] ==
            ["case_summary", "evidence_reference",
             "raw_source_documents", "scripted_reviews"] and
            all(x.get("customer_ownership") == "UNDETERMINED" and
                x.get("owner") == "synthetic_test_team" for x in classes),
            "v26_data_class_rights_drift")
    rights = policy.get("rights_position")
    require(type(rights) is dict and
            rights.get("proposed_controller") ==
            "customer_provided_legal_entity_only_if_contract_signed" and
            rights.get("proposed_processor") ==
            "Mavenu only if permitted by executed agreement",
            "v26_customer_rights_assumption_drift")
    rights_not_granted = (
        "actual_controller_identified", "actual_data_license_executed",
        "purpose_limitation_approved", "retention_period_approved",
        "cross_border_transfer_approved", "deletion_method_approved",
        "individual_access_rights_workflow_approved",
        "subprocessor_rights_approved", "export_policy_approved",
        "actual_customer_data_access",
    )
    require(all(rights.get(k) is False for k in rights_not_granted) and
            type(rights.get("required_contracts")) is list and
            len(rights["required_contracts"]) == 5,
            "v26_data_rights_fabricated")
    tests = policy.get("tests_required")
    require(type(tests) is dict and len(tests) == 12 and
            all(x is True for x in tests.values()),
            "v26_adversarial_test_scope_reduced")
    decision = policy.get("human_decision")
    require(type(decision) is dict and
            decision.get("recommended_action") == "REVIEW_ONLY" and
            decision.get("production_architecture_selected") is False,
            "v26_false_design_ratification")
    for field in ("owner", "security_reviewer", "data_steward",
                  "legal_reviewer", "approved_at_utc", "signature"):
        require(decision.get(field) is None,
                "v26_fabricated_human_signature")
    gates = decision.get("gate_status")
    require(type(gates) is dict and len(gates) == 10 and
            all(v is False for v in gates.values()),
            "v26_false_phase_gate")
    require(type(decision.get("required_evidence")) is list and
            len(decision["required_evidence"]) >= 7 and
            type(policy.get("limitations")) is list and
            len(policy["limitations"]) >= 5,
            "v26_open_design_risks_missing")


def _authorized(actor_id: Any, tenant_id: Any,
                site_id: Any, operation: Any) -> None:
    """Uniform deny; call-site values do not grant their own scope."""
    if (type(actor_id) is not str or
        type(tenant_id) is not str or
        type(site_id) is not str or
        type(operation) is not str or
        re.fullmatch(r"SYN-ACTOR-[0-9]{3}", actor_id,
                     flags=re.ASCII) is None or
        re.fullmatch(r"SYN-TENANT-[0-9]{3}", tenant_id,
                     flags=re.ASCII) is None or
        re.fullmatch(r"SYN-SITE-[0-9]{3}", site_id,
                     flags=re.ASCII) is None or
        operation not in OPERATIONS):
        raise ScopeDenied("scope_denied")
    grants = GRANTS.get(actor_id)
    if (grants is None or
        operation not in grants[1].get((tenant_id, site_id), ())):
        raise ScopeDenied("scope_denied")


def read_scope(db: sqlite3.Connection, *,
               actor_id: str, tenant_id: str, site_id: str,
               operation: str) -> list[dict[str, str]]:
    """Test reference guard; caller is NOT actually authenticated.

    Neither tenant_id nor actor_id is a verified principal from an external
    identity provider. In production the database connection itself would
    also require least-privilege rights/RLS or equivalent isolation controls.
    """
    _authorized(actor_id, tenant_id, site_id, operation)
    state = migrate_v23.validate_version(db, 2)
    require(state["tables"] == 13, "invalid_isolation_test_db_version")
    query, columns = SCOPED_QUERIES[operation]
    rows = db.execute(query, (tenant_id, site_id)).fetchall()
    require(all(row[0] == tenant_id and row[1] == site_id
                for row in rows), "out_of_scope_result_returned")
    return [dict(zip(columns, row)) for row in rows]


def seed_isolated_fixture(db: sqlite3.Connection) -> dict[str, Any]:
    migrate_v23.validate_version(db, 2)
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "foreign_keys_disabled")
    for table in ("tenant", "site", "asset", "maintenance_case",
                  "evidence_reference"):
        require(db.execute(
            'SELECT COUNT(*) FROM "' + table + '"').fetchone()[0] == 0,
            "synthetic_isolation_seed_not_empty")
    tenants = [(t, "Fictional Owner " + t[-3:], "synthetic_only")
               for t in TENANTS]
    sites = [(t, s, "Fictional Site " + t[-3:] + "/" + s[-3:], 1)
             for t, s in TENANT_SITE]
    assets, cases, evidence = [], [], []
    for t, s in TENANT_SITE:
        for a in (1, 2):
            assets.append((
                t, s, "SYN-ASSET-" + str(a).zfill(3),
                "bearing_drive" if a == 1 else "sensor_module",
                "Mock Workshop", 1
            ))
        for c in (1, 2, 3):
            case_id = "SYN-CASE-" + str(c).zfill(3)
            asset_id = "SYN-ASSET-" + str(1+(c-1)%2).zfill(3)
            cases.append((
                t, s, case_id, asset_id,
                "SYN-WO-" + str(c).zfill(3),
                "2026-03-" + str(c+1).zfill(2) + "T12:00:00Z",
                "bearing_wear", 3600*c, 1000*c,
                "fixture_only", 1
            ))
            evidence.append((
                t, s, case_id, "SYN-EV-" + str(100+c).zfill(3), 0
            ))
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany("INSERT INTO tenant VALUES (?,?,?)", tenants)
        db.executemany("INSERT INTO site VALUES (?,?,?,?)", sites)
        db.executemany("INSERT INTO asset VALUES (?,?,?,?,?,?)", assets)
        db.executemany(
            "INSERT INTO maintenance_case VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            cases
        )
        db.executemany(
            "INSERT INTO evidence_reference VALUES (?,?,?,?,?)", evidence
        )
        require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                "synthetic_scopes_invalid_foreign_key")
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    actual = {
        k: db.execute('SELECT COUNT(*) FROM "'+k+'"').fetchone()[0]
        for k in EXPECTED_COUNTS
    }
    require(actual == EXPECTED_COUNTS and sum(actual.values()) == TOTAL_ROWS,
            "isolation_fixture_counts_incorrect")
    # Duplicated IDs across all four sites deliberately require composite
    # tenant+site constraints on every query.
    reuse = db.execute(
        "SELECT COUNT(*) FROM maintenance_case WHERE case_id='SYN-CASE-001'"
    ).fetchone()[0]
    require(reuse == 4, "no_cross_tenant_identity_collision_exercised")
    return {
        "table_counts": actual, "total_rows": TOTAL_ROWS,
        "tenant_site_scopes": len(TENANT_SITE),
        "duplicate_case_001_count": reuse,
        "real_customer_data": False,
        "authn_or_database_rls_implemented": False,
        "sqlite_user_version": 2,
    }


def evaluate_matrix(db: sqlite3.Connection) -> dict[str, Any]:
    """Exhaustively test 6 actors x 4 scopes x 2 fixed read operations."""
    allow, deny = [], []
    for actor_id in GRANTS:
        for tenant, site in TENANT_SITE:
            for operation in OPERATIONS:
                try:
                    result = read_scope(
                        db, actor_id=actor_id, tenant_id=tenant,
                        site_id=site, operation=operation
                    )
                except ScopeDenied as exc:
                    require(str(exc) == "scope_denied",
                            "unexpected_isolation_denial")
                    deny.append((actor_id, tenant, site, operation))
                    continue
                require(len(result) == 3 and
                        all(row["tenant_id"] == tenant and
                            row["site_id"] == site for row in result),
                        "granted_result_breached_scope")
                allow.append({
                    "actor_id": actor_id,
                    "tenant_id": tenant, "site_id": site,
                    "operation": operation, "row_count": len(result),
                    "row_ids": [r["case_id"] for r in result],
                })
    require(len(allow) == 8 and len(deny) == 40,
            "authorization_matrix_counts_drift")
    # Uniformly reject caller-chosen IDs, untrusted operations, and a role
    # with no grants; response does not say if a tenant/row exists.
    invalid = [
        ("SYN-ACTOR-999", TENANTS[0], SITES[0], OPERATIONS[0]),
        ("SYN-ACTOR-001", "SYN-TENANT-999", SITES[0], OPERATIONS[0]),
        ("SYN-ACTOR-001", "SYN-TENANT-001 OR 1=1",
         SITES[0], OPERATIONS[0]),
        ("SYN-ACTOR-001", TENANTS[0], "SYN-SITE-001' OR 'x'='x",
         OPERATIONS[0]),
        ("SYN-ACTOR-001", TENANTS[0], SITES[0], "export_case"),
        ("SYN-ACTOR-001", TENANTS[0], SITES[0], "send_ot_command"),
        ("SYN-ACTOR-006", TENANTS[0], SITES[0], OPERATIONS[0]),
        ("SYN-ACTOR-001 ", TENANTS[0], SITES[0], OPERATIONS[0]),
        (None, TENANTS[0], SITES[0], OPERATIONS[0]),
        ("SYN-ACTOR-001", None, SITES[0], OPERATIONS[0]),
    ]
    for actor_id, tenant, site, op in invalid:
        try:
            read_scope(db, actor_id=actor_id, tenant_id=tenant,
                       site_id=site, operation=op)
        except ScopeDenied as exc:
            require(str(exc) == "scope_denied",
                    "malformed_scope_response_drift")
        else:
            raise V26InvariantError("malformed_scope_was_authorized")
    return {
        "attempted_grant_combinations":48,
        "allowed_reads":len(allow),
        "denied_reads":len(deny),
        "malformed_or_unsupported_probes_denied":len(invalid),
        "same_case_id_across_all_scopes_verified":True,
        "allowed_results":allow,
        "forbidden_combination_count":len(deny),
        "cross_tenant_or_site_leak_found":False,
        "production_authentication_verified":False,
        "database_row_security_verified":False,
    }


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False
    ).encode("ascii")).hexdigest()


def run_isolation_replay() -> dict[str, Any]:
    policy = load_policy()
    validate_policy(policy)
    with tempfile.TemporaryDirectory(prefix="mavenu-v24-") as directory:
        path = Path(directory)/persist_v24.NAME
        db = persist_v24.connect(path)
        try:
            persist_v24.bootstrap(db)
            seed = seed_isolated_fixture(db)
            before = digest(db.execute(
                "SELECT tenant_id,site_id,case_id,asset_id,work_order_ref "
                "FROM maintenance_case ORDER BY tenant_id,site_id,case_id"
            ).fetchall())
            permissions = evaluate_matrix(db)
            require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                    "fk_failed_after_isolation_queries")
            after = digest(db.execute(
                "SELECT tenant_id,site_id,case_id,asset_id,work_order_ref "
                "FROM maintenance_case ORDER BY tenant_id,site_id,case_id"
            ).fetchall())
            require(before == after,
                    "isolation_read_mutated_source_rows")
            schema = migrate_v23.validate_version(db, 2)
            return_result = {
                "increment":"V26",
                "objective":"Document tenant boundaries and data rights",
                "required_proof":"Isolation design decision",
                "decision_state":"PROPOSED_NOT_RATIFIED",
                "database_schema_version":schema["version"],
                "entity_row_counts":seed,
                "matrix":permissions,
                "synthetic_case_rows_unchanged":True,
                "synthetic_case_digest_sha256":before,
                "database_fk_integrity":"PASS",
                "principal_authentication":"NOT_IMPLEMENTED",
                "database_row_level_security":"NOT_IMPLEMENTED",
                "legal_customer_data_rights":"NOT_ESTABLISHED",
                "human_design_approval":"PENDING",
                "customer_data_used":False,
                "production_access_authorized":False
            }
        finally:
            db.close()
    require(not path.exists(),"v26_temporary_database_not_removed")
    return_result["temporary_database_deleted"] = True
    return return_result
