"""V22 canonical identity and reference-data candidate for synthetic fixtures.

Architecture V4 V22: Define identity and reference-data rules.
Proof: Uniqueness and link tests.

STRICTLY DESIGN/TEST ONLY. This module does not import actual users, resolve
customer aliases, access a persistent database, change V9 runtime, or grant
V20/V21/V22 human approvals. V21's DB, if used, is always SQLite :memory:.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import entity_v21
import lineage_v16

PROJECT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT / "docs/data/IDENTITY_REFERENCE_POLICY_V22.json"
FIXTURE_ID = "SYN-RI-V5-20261107-A"
SOURCE_COMMIT = "704123eca45628bf504594af39a66036cc0451c5"

PATTERNS = {
    "tenant_id": r"SYN-TENANT-[0-9]{3}",
    "site_id": r"SYN-SITE-[0-9]{3}",
    "asset_id": r"SYN-ASSET-[0-9]{3}",
    "case_id": r"SYN-CASE-[0-9]{3}",
    "work_order_ref": r"SYN-WO-[0-9]{3}",
    "evidence_ref": r"SYN-EV-[0-9]{3}",
    "reviewer_id": r"SYN-REVIEWER-[0-9]{3}",
    "source_document_id": r"SYN-DOC-[0-9]{3}",
    "trace_id": (
        r"SYN-LINEAGE-(asset_records|case_records|scripted_review_entries|"
        r"seeded_reference_labels)-SYN-(ASSET|CASE)-[0-9]{3}"
    ),
}
REFERENCE = {
    "asset_class": ["bearing_drive", "belt_conveyor", "control_valve",
                    "electric_motor", "sensor_module", "transfer_pump"],
    "cohort": ["Assembly Test Line", "Mock Workshop", "Utility Test Zone"],
    "failure_code": ["bearing_wear", "belt_slip", "motor_trip",
                     "seal_leak", "sensor_fault", "valve_stick"],
    "review_state": ["fixture_only"],
    "disposition": ["acknowledge", "defer", "investigate_history",
                    "request_evidence"],
    "reason_code": ["further_demo_review", "missing_evidence_reference",
                    "repeat_history_flag", "routine_synthetic_review"],
    "expected_review_label": ["missing_evidence",
                              "repeat_history_candidate", "single_event"],
    "source_dataset": ["asset_records", "case_records",
                       "scripted_review_entries", "seeded_reference_labels"],
    "source_fixture": list(entity_v21.SOURCE_IDS),
    "transform_rule": ["V15_HOURS_EXACT", "V15_USD_EXACT_CENTS",
                       "V15_UTC_EXPLICIT"],
}
UNIQUE = {
    "tenant": ("tenant", ("tenant_id",)),
    "site": ("site", ("tenant_id", "site_id")),
    "asset": ("asset", ("tenant_id", "site_id", "asset_id")),
    "maintenance_case": ("maintenance_case", ("tenant_id", "site_id", "case_id")),
    "work_order_ref": ("maintenance_case",
                       ("tenant_id", "site_id", "work_order_ref")),
    "evidence_reference": (
        "evidence_reference",
        ("tenant_id", "site_id", "case_id", "evidence_ref")),
    "scripted_review": (
        "scripted_review",
        ("tenant_id", "site_id", "case_id", "reviewer_id")),
    "reference_label": (
        "reference_label", ("tenant_id", "site_id", "case_id")),
    "source_document": (
        "source_document", ("tenant_id", "site_id", "source_document_id")),
    "source_document_path": (
        "source_document", ("tenant_id", "site_id", "fixture_path")),
    "record_origin": (
        "record_origin", ("tenant_id", "site_id", "trace_id")),
    "origin_source_tuple": (
        "record_origin", ("tenant_id", "site_id", "source_document_id",
                          "source_dataset", "source_record_id")),
    "transform_step": (
        "transform_step", ("tenant_id", "site_id", "trace_id", "step_ordinal")),
}
LINKS = {
    "site": ("tenant", ("tenant_id",)),
    "asset": ("site", ("tenant_id", "site_id")),
    "maintenance_case": ("asset", ("tenant_id", "site_id", "asset_id")),
    "evidence_reference": (
        "maintenance_case", ("tenant_id", "site_id", "case_id")),
    "scripted_review": ("maintenance_case",
                        ("tenant_id", "site_id", "case_id")),
    "reference_label": ("maintenance_case",
                        ("tenant_id", "site_id", "case_id")),
    "source_document": ("site", ("tenant_id", "site_id")),
    "record_origin": ("source_document",
                      ("tenant_id", "site_id", "source_document_id")),
    "transform_step": ("record_origin",
                       ("tenant_id", "site_id", "trace_id")),
}
MUTATIONS = {
    "duplicate_asset_id": "duplicate_asset_identifier",
    "duplicate_case_id": "duplicate_case_identifier",
    "duplicate_work_order": "duplicate_work_order_reference",
    "missing_case_asset": "orphan_case_asset",
    "missing_review_case": "orphan_scripted_review",
    "missing_label_case": "orphan_reference_label",
    "duplicate_scripted_review": "duplicate_scripted_review_key",
    "duplicate_label": "duplicate_reference_label",
    "duplicate_evidence_ref": "duplicate_case_evidence_reference",
    "invalid_evidence_ref": "noncanonical_evidence_ref",
    "unknown_failure_code": "unknown_failure_code",
    "unknown_asset_class": "unknown_asset_class",
    "unknown_cohort": "unknown_cohort",
    "unknown_label_enum": "unknown_reference_label",
    "unknown_disposition": "unknown_review_disposition",
    "unknown_reason_code": "unknown_review_reason",
    "mixed_case_case_id": "noncanonical_case_id",
    "whitespace_case_id": "noncanonical_case_id",
    "unicode_case_id": "noncanonical_case_id",
    "invalid_work_order": "noncanonical_work_order_ref",
    "invalid_asset_id": "noncanonical_asset_id",
    "non_synthetic_flag": "non_synthetic_case",
    "unapproved_source_system": "unauthorized_source_system",
    "unexpected_source_doc": "unauthorized_source_document",
    "undeclared_case_field": "unknown_case_field",
}
ASSET_FIELDS = {"asset_id", "asset_class", "cohort", "synthetic"}
CASE_FIELDS = {
    "case_id", "asset_id", "work_order_ref", "occurred_at_utc", "failure_code",
    "downtime_hours", "repair_cost_usd", "evidence_refs", "synthetic",
    "review_state",
}
REVIEW_FIELDS = {"case_id", "reviewer_id", "disposition", "reason_code"}
LABEL_FIELDS = {"case_id", "expected_review_label", "synthetic"}


class IdentityRejected(ValueError):
    """Fixed diagnostic category; never expose arbitrary source values."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise IdentityRejected(code)


def policy() -> dict[str, Any]:
    try:
        data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IdentityRejected("identity_policy_missing") from None
    require(type(data) is dict, "identity_policy_not_object")
    return data


def canonical(kind: str, value: Any) -> str:
    """Reject ambiguous Unicode, casefolding, trimming and invalid token."""
    require(kind in PATTERNS, "unknown_identity_kind")
    require(type(value) is str and
            re.fullmatch(PATTERNS[kind], value, flags=re.ASCII) is not None,
            "noncanonical_" + kind)
    return value


def reference(kind: str, value: Any, error: str | None = None) -> str:
    require(kind in REFERENCE, "unknown_reference_kind")
    require(type(value) is str and value in REFERENCE[kind],
            error or "unknown_reference_" + kind)
    return value


def validate_policy(p: dict[str, Any]) -> None:
    require(type(p) is dict and p.get("schema_version") == "1.0.0" and
            p.get("increment") == "V22" and
            p.get("objective") ==
            "Define identity and reference-data rules" and
            p.get("required_proof") == "Uniqueness and link tests",
            "identity_policy_objective_drift")
    require(p.get("review_status") ==
            "CANDIDATE_IDENTITY_POLICY_HUMAN_REVIEW_PENDING" and
            p.get("source_fixture_set_id") == FIXTURE_ID and
            p.get("source_commit") == SOURCE_COMMIT and
            p.get("parent_schema") == "docs/data/ENTITY_MODEL_V21.json" and
            p.get("identity_strategy") ==
            "strict ASCII case-sensitive exact-token, no silent trim/casefold/alias merge or external identity resolution",
            "identity_policy_scope_or_approval_drift")
    ns = p.get("scope")
    require(type(ns) is dict and
            ns.get("tenant_id") == entity_v21.TENANT and
            ns.get("site_id") == entity_v21.SITE,
            "invalid_synthetic_tenant_context")
    for field in ("persisted_database", "authorization_enforced",
                  "real_customer_identities"):
        require(ns.get(field) is False, "false_identity_security_claim")
    require(p.get("id_patterns") == PATTERNS and
            p.get("reference_values") == REFERENCE,
            "identity_or_reference_definition_drift")
    uniqueness = p.get("uniqueness_keys")
    require(type(uniqueness) is list and
            [x.get("name") for x in uniqueness if type(x) is dict] ==
            list(UNIQUE), "identity_uniqueness_inventory_drift")
    for x in uniqueness:
        need_table, need_fields = UNIQUE[x["name"]]
        require(x.get("fields") == list(need_fields) and
                type(x.get("meaning")) is str and len(x["meaning"]) > 15,
                "identity_unique_scope_drift")
    foreign = p.get("foreign_key_links")
    require(type(foreign) is list and len(foreign) == len(LINKS),
            "identity_link_inventory_drift")
    for link, (child, target) in zip(foreign, LINKS.items()):
        parent, fields = target
        require(type(link) is dict and link.get("child") == child and
                link.get("parent") == parent and
                link.get("scope") == list(fields) and
                link.get("test") == "foreign_key",
                "identity_link_scope_drift")
    require(p.get("expected") == {
        "entities": 10, "relationships": 9, "synthetic_rows": 120,
        "source_records": 34, "transform_steps": 36,
        "unmatched_parent_links": 0, "source_files": 3,
        "case_rows": 12, "asset_rows": 6, "review_rows": 4,
        "label_rows": 12, "example_evidence_refs": 11,
        "mutation_cases": 25,
    }, "identity_expected_inventory_drift")
    cases = p.get("adverse_cases")
    require(type(cases) is list and len(cases) == len(MUTATIONS) and
            [(c.get("id"), c.get("expected_error"))
             for c in cases if type(c) is dict] ==
            list(MUTATIONS.items()), "identity_negative_case_drift")
    approvals = p.get("approvals")
    require(type(approvals) is dict, "identity_review_record_missing")
    for flag in ("v10_formal_promotion", "v20_data_quality_signoff",
                 "v21_schema_review", "v22_identity_review",
                 "customer_data_authorized", "production_storage_authorized",
                 "v23_migration_approved", "tenant_access_control_authorized",
                 "ot_or_cmms_write_permitted"):
        require(approvals.get(flag) is False, "identity_false_approval_" + flag)
    for key in ("named_data_architect", "named_data_steward",
                "named_security_reviewer", "review_date_utc", "signature"):
        require(approvals.get(key) is None, "identity_fabricated_reviewer")
    require(type(p.get("limitations")) is list and
            len(p["limitations"]) >= 4, "identity_unreviewed_risk_missing")


def _rows(document: dict[str, Any], key: str, count: int,
          fields: set[str], code: str) -> list[dict[str, Any]]:
    require(type(document) is dict and
            type(document.get(key)) is list and
            len(document[key]) == count,
            code + "_inventory")
    rows = document[key]
    require(all(type(x) is dict and set(x) == fields for x in rows),
            code + "_field_shape")
    return rows


def validate_sources(documents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Verify identity references in deep-copyable synthetic source documents."""
    require(type(documents) is dict and
            set(documents) == set(entity_v21.SOURCE_IDS),
            "unauthorized_source_document")
    cases_file = documents["fixtures/cases.json"]
    script = documents["fixtures/demo_review_script.json"]
    labels_file = documents["fixtures/reference_labels.json"]
    require(cases_file.get("fixture_set_id") == FIXTURE_ID and
            cases_file.get("synthetic_only") is True and
            cases_file.get("source_system") == "NONE" and
            script.get("fixture_set_id") == FIXTURE_ID and
            script.get("scripted_only") is True and
            script.get("human_execution") is False and
            labels_file.get("fixture_set_id") == FIXTURE_ID and
            labels_file.get("synthetic_only") is True and
            labels_file.get("independently_validated") is False,
            "unauthorized_source_system")
    assets = _rows(cases_file, "assets", 6, ASSET_FIELDS, "asset")
    source_cases = cases_file.get("records")
    if type(source_cases) is list:
        for candidate in source_cases:
            if type(candidate) is dict:
                require(set(candidate).issubset(CASE_FIELDS),
                        "unknown_case_field")
    cases = _rows(cases_file, "records", 12, CASE_FIELDS, "unknown_case")
    scripts = _rows(script, "entries", 4, REVIEW_FIELDS, "scripted_review")
    labels = _rows(labels_file, "records", 12, LABEL_FIELDS, "reference_label")
    asset_ids: set[str] = set()
    for row in assets:
        canonical("asset_id", row.get("asset_id"))
        require(row["asset_id"] not in asset_ids,
                "duplicate_asset_identifier")
        asset_ids.add(row["asset_id"])
        reference("asset_class", row.get("asset_class"),
                  "unknown_asset_class")
        reference("cohort", row.get("cohort"), "unknown_cohort")
        require(row.get("synthetic") is True, "non_synthetic_asset")
    case_ids: set[str] = set()
    work_refs: set[str] = set()
    evidence_count = 0
    for row in cases:
        canonical("case_id", row.get("case_id"))
        canonical("asset_id", row.get("asset_id"))
        canonical("work_order_ref", row.get("work_order_ref"))
        require(row["case_id"] not in case_ids,
                "duplicate_case_identifier")
        case_ids.add(row["case_id"])
        require(row["work_order_ref"] not in work_refs,
                "duplicate_work_order_reference")
        work_refs.add(row["work_order_ref"])
        require(row["asset_id"] in asset_ids, "orphan_case_asset")
        reference("failure_code", row.get("failure_code"),
                  "unknown_failure_code")
        reference("review_state", row.get("review_state"),
                  "unknown_review_state")
        require(row.get("synthetic") is True, "non_synthetic_case")
        refs = row.get("evidence_refs")
        require(type(refs) is list and len(refs) <= 3,
                "noncanonical_evidence_ref")
        seen: set[str] = set()
        for code in refs:
            canonical("evidence_ref", code)
            require(code not in seen, "duplicate_case_evidence_reference")
            seen.add(code)
            evidence_count += 1
    review_keys: set[tuple[str, str]] = set()
    for row in scripts:
        canonical("case_id", row.get("case_id"))
        canonical("reviewer_id", row.get("reviewer_id"))
        require(row["case_id"] in case_ids, "orphan_scripted_review")
        key = (row["case_id"], row["reviewer_id"])
        require(key not in review_keys, "duplicate_scripted_review_key")
        review_keys.add(key)
        reference("disposition", row.get("disposition"),
                  "unknown_review_disposition")
        reference("reason_code", row.get("reason_code"),
                  "unknown_review_reason")
    label_ids: set[str] = set()
    for row in labels:
        canonical("case_id", row.get("case_id"))
        require(row["case_id"] in case_ids, "orphan_reference_label")
        require(row["case_id"] not in label_ids, "duplicate_reference_label")
        label_ids.add(row["case_id"])
        reference("expected_review_label", row.get("expected_review_label"),
                  "unknown_reference_label")
        require(row.get("synthetic") is True, "non_synthetic_label")
    return {
        "assets": len(asset_ids), "cases": len(case_ids),
        "unique_work_order_refs": len(work_refs),
        "evidence_references": evidence_count,
        "scripted_review_keys": len(review_keys),
        "authored_label_keys": len(label_ids),
        "case_asset_links": len(cases),
        "script_case_links": len(scripts),
        "label_case_links": len(labels),
        "unresolved_source_links": 0,
        "source_documents": len(documents),
        "real_customer_identity_resolved": False,
    }


def validate_sql_keys(db: sqlite3.Connection) -> dict[str, Any]:
    """Check all 13 key views and all 9 scoped relations in V21 :memory:."""
    result: dict[str, int] = {}
    for name, (table, columns) in UNIQUE.items():
        by = ", ".join('"' + col + '"' for col in columns)
        query = (
            'SELECT COUNT(*) FROM (SELECT ' + by +
            ', COUNT(*) AS n FROM "' + table +
            '" GROUP BY ' + by + ' HAVING n>1)'
        )
        duplicates = db.execute(query).fetchone()[0]
        require(duplicates == 0, "sql_identity_duplicate_" + name)
        result[name] = duplicates
    relationships: dict[str, int] = {}
    for child, (parent, columns) in LINKS.items():
        clauses = " AND ".join(
            'p."' + col + '"=c."' + col + '"' for col in columns
        )
        query = ('SELECT COUNT(*) FROM "' + child +
                 '" AS c WHERE NOT EXISTS (SELECT 1 FROM "' + parent +
                 '" AS p WHERE ' + clauses + ')')
        unlinked = db.execute(query).fetchone()[0]
        require(unlinked == 0, "sql_unresolved_link_" + child)
        relationships[child] = unlinked
    require(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "sql_foreign_keys_disabled")
    require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
            "sql_foreign_key_check_failed")
    return {
        "uniqueness_views_checked": len(result),
        "foreign_key_links_checked": len(relationships),
        "uniqueness_violations": sum(result.values()),
        "unresolved_links": sum(relationships.values()),
        "duplicates_by_key": result,
        "unresolved_by_child": relationships,
        "database_is_ephemeral": True,
        "tenant_authentication_implemented": False,
    }


def _mutate(name: str, docs: dict[str, Any]) -> None:
    f = docs["fixtures/cases.json"]
    cases = f["records"]
    assets = f["assets"]
    reviews = docs["fixtures/demo_review_script.json"]["entries"]
    labels = docs["fixtures/reference_labels.json"]["records"]
    if name == "duplicate_asset_id":
        assets[1]["asset_id"] = assets[0]["asset_id"]
    elif name == "duplicate_case_id":
        cases[1]["case_id"] = cases[0]["case_id"]
    elif name == "duplicate_work_order":
        cases[1]["work_order_ref"] = cases[0]["work_order_ref"]
    elif name == "missing_case_asset":
        cases[0]["asset_id"] = "SYN-ASSET-999"
    elif name == "missing_review_case":
        reviews[0]["case_id"] = "SYN-CASE-999"
    elif name == "missing_label_case":
        labels[0]["case_id"] = "SYN-CASE-999"
    elif name == "duplicate_scripted_review":
        reviews[1]["case_id"] = reviews[0]["case_id"]
    elif name == "duplicate_label":
        labels[1]["case_id"] = labels[0]["case_id"]
    elif name == "duplicate_evidence_ref":
        cases[0]["evidence_refs"].append(cases[0]["evidence_refs"][0])
    elif name == "invalid_evidence_ref":
        cases[0]["evidence_refs"] = ["SYN-EV-ABC"]
    elif name == "unknown_failure_code":
        cases[0]["failure_code"] = "unknown_failure"
    elif name == "unknown_asset_class":
        assets[0]["asset_class"] = "unapproved_equipment"
    elif name == "unknown_cohort":
        assets[0]["cohort"] = "Real Facility"
    elif name == "unknown_label_enum":
        labels[0]["expected_review_label"] = "customer_verified"
    elif name == "unknown_disposition":
        reviews[0]["disposition"] = "actually_approved"
    elif name == "unknown_reason_code":
        reviews[0]["reason_code"] = "real_operator_reason"
    elif name == "mixed_case_case_id":
        cases[0]["case_id"] = "syn-case-001"
    elif name == "whitespace_case_id":
        cases[0]["case_id"] = "SYN-CASE-001 "
    elif name == "unicode_case_id":
        cases[0]["case_id"] = "SYN-CASE-０01"
    elif name == "invalid_work_order":
        cases[0]["work_order_ref"] = "SYN-WO-ABC"
    elif name == "invalid_asset_id":
        assets[0]["asset_id"] = "SYN-ASSET-ABC"
    elif name == "non_synthetic_flag":
        cases[0]["synthetic"] = False
    elif name == "unapproved_source_system":
        f["source_system"] = "REAL_CUSTOMER_CMMS"
    elif name == "unexpected_source_doc":
        docs["fixtures/customer_export.json"] = {"case_id": "REAL-001"}
    elif name == "undeclared_case_field":
        cases[0]["operator_email"] = "placeholder@example.invalid"
    else:
        raise IdentityRejected("unknown_adverse_case")


def exercise_cases(p: dict[str, Any],
                   documents: dict[str, Any]) -> dict[str, Any]:
    """One expected failure per fixed malformed copy; no source mutation."""
    validate_policy(p)
    baseline = validate_sources(documents)
    starting = json.dumps(documents, sort_keys=True, separators=(",", ":"))
    results = []
    for item in p["adverse_cases"]:
        changed = copy.deepcopy(documents)
        _mutate(item["id"], changed)
        try:
            validate_sources(changed)
        except IdentityRejected as exc:
            require(str(exc) == item["expected_error"],
                    "unexpected_negative_test_code")
        else:
            raise IdentityRejected("unrejected_negative_identity_case")
        results.append({
            "case": item["id"],
            "fixed_error": item["expected_error"],
            "result": "REJECTED_AS_EXPECTED",
        })
    require(starting == json.dumps(documents, sort_keys=True, separators=(",", ":")),
            "synthetic_fixture_mutated")
    return {
        "source_identity_results": baseline,
        "adverse_cases": len(results),
        "adverse_cases_rejected": len(results),
        "case_results": results,
        "source_documents_unchanged": True,
        "customer_data": False,
        "human_identity_review": False,
    }
