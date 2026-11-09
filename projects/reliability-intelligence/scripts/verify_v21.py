"""V21 canonical entity schema candidate verification and unsigned review pack.

Architecture V4 Appendix: V21 Design canonical entities and relationships;
proof Reviewed entity schema. This produces a *schema review request* and
machine-checked in-memory SQLite simulation. Human review is NOT performed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import sqlite3
from typing import Any

import entity_v21 as entity
import gate_v20
import verify_v10
import verify_v11
import verify_v12

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V21"
REPORT = EVIDENCE / "schema_review_validation.json"
CATALOG = EVIDENCE / "entity_relationship_catalog.json"
PACKET = EVIDENCE / "unsigned_entity_schema_review.json"


class V21EvidenceRejected(ValueError):
    """Stable error category; never echo arbitrary row content."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise V21EvidenceRejected(code)


def source_approvals(*, require_v20_report: bool = False) -> dict[str, Any]:
    v20_register = gate_v20.baseline()
    v20_signoff = gate_v20.signoff()
    gate_v20.validate_baseline(v20_register, v20_signoff)
    upstream = gate_v20.validate_source_approvals()
    if require_v20_report:
        report_path = PROJECT / "evidence" / "V20" / "verification.json"
        try:
            observed = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V21EvidenceRejected("missing_v20_technical_report") from None
        require(observed.get("increment") == "V20" and
                observed.get("result") ==
                "synthetic_baseline_verified_formal_signoff_blocked",
                "v20_technical_state_inconsistent")
        status = observed.get("technical")
        require(type(status) is dict and
                status.get("technical_evidence") == "PASS" and
                status.get("human_data_quality_signoff") ==
                "BLOCKED_PENDING_HUMAN_SIGNOFF" and
                status.get("future_phase_v21_authorized") is False and
                status.get("formal_phase_02_approval") is False and
                status.get("blockers_unresolved") == 8,
                "v20_phase_gate_misrepresented")
    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE))
    require(frozen["frozen_files_verified"] == 18,
            "v10_source_freeze_drift")
    v11 = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    verify_v11.validate_dictionary(v11)
    v12 = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    verify_v12.validate_contract(v12, v11)
    return {
        "v10_frozen_files": frozen["frozen_files_verified"],
        "v20_technical_evidence": "PASS",
        "v20_data_quality_human_signoff": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_formal_phase_03_authorized": False,
        "v11_source_dictionary": upstream["v11_dictionary"],
        "v12_schema": upstream["v12_schema"],
        "customer_data_permission": False,
    }


def generate(*, require_v20_report: bool = False) -> dict[str, Any]:
    previous = source_approvals(require_v20_report=require_v20_report)
    model = entity.load_model()
    entity.validate_model(model)
    ddl_raw = entity.DDL_PATH.read_bytes()
    db = entity.create_memory_schema()
    try:
        catalog = entity.validate_catalog(db, model)
        preview = entity.load_synthetic_preview(db, model)
        # Check all relational keys, counts and totals once more post-populate.
        entity.validate_catalog(db, model)
        require(preview["total_rows"] == 120 and
                preview["counts"] == entity.EXPECTED_COUNTS and
                preview["foreign_key_violations"] == 0 and
                preview["synthetic_duration_seconds"] == 163800 and
                preview["synthetic_cost_cents"] == 1273500 and
                preview["v16_reconstructed_origin_count"] == 34 and
                preview["v16_conversion_steps"] == 36,
                "entity_schema_preview_mismatch")
        databases = db.execute("PRAGMA database_list").fetchall()
        require(any(item[1] == "main" for item in databases) and
                all(item[2] == "" for item in databases),
                "unapproved_persistent_storage_used")
    finally:
        db.close()
    return {
        "increment": "V21",
        "objective": "Design canonical entities and relationships",
        "required_proof": "Reviewed entity schema",
        "result": "candidate_entity_schema_technically_validated_human_review_pending",
        "review_status": model["review_status"],
        "source_fixture_set_id": model["source_fixture_set_id"],
        "schema_design_file_sha256": hashlib.sha256(ddl_raw).hexdigest(),
        "entity_model_canonical_sha256": gate_v20.canonical_sha256(model),
        "source_context": previous,
        "catalog": catalog,
        "synthetic_preview": preview,
        "candidate_model": model,
        "review_decision": {
            "technical_validation": "PASS",
            "human_schema_review": "PENDING",
            "human_reviewer_assigned": False,
            "signed_schema_review_exists": False,
            "v20_human_signoff": False,
            "v21_phase_formally_authorized": False,
            "future_v22_authorized": False,
            "production_persistence_authorized": False,
            "customer_data_authorized": False,
            "ot_or_cmms_write_authorized": False,
            "recommended_decision": "DO_NOT_PROMOTE",
            "unresolved_design_decisions": model["unresolved_design_decisions"],
        },
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": [
            "SQLite schema created only in memory then closed; no durable records or backup/restore.",
            "Tenancy composite foreign keys are NOT production authorization or row-level security.",
            "The reviewer has not validated entity identity, relationship semantics, site ownership or lineage authority.",
            "V22 canonical identity rules and V23 reversible migrations are not implemented by V21.",
            "V10 formal phase approval and V20 human data-quality sign-off are blocked.",
            "No customer data, plant telemetry, actual maintenance work order, production API, OT/SCADA/CMMS writes or financial outcomes.",
        ],
    }


def main() -> int:
    record = generate(require_v20_report=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        key: value for key, value in record.items()
        if key not in ("candidate_model", "review_decision")
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    CATALOG.write_text(json.dumps({
        "increment": "V21",
        "entity_count": record["catalog"]["entities_verified"],
        "foreign_key_relationship_count": record["catalog"]["relationships_verified"],
        "ddl_sha256": record["schema_design_file_sha256"],
        "entities": record["candidate_model"]["entities"],
        "synthetic_namespace": record["candidate_model"]["synthetic_namespace"],
        "fixture_record_counts": record["synthetic_preview"]["counts"],
        "in_memory_only": True,
        "signed_or_approved": False,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    PACKET.write_text(json.dumps({
        "increment": "V21",
        "required_proof": "Reviewed entity schema",
        "artifact_status": "UNSIGNED_REVIEW_REQUEST",
        "human_review_completed": False,
        "decision": record["review_decision"],
        "candidate_ddl_sha256": record["schema_design_file_sha256"],
        "candidate_model_sha256": record["entity_model_canonical_sha256"],
        "schematic_relations_verified": record["catalog"]["relationships_verified"],
        "synthetic_records_tested": record["synthetic_preview"]["total_rows"],
        "named_reviewers": [],
        "reviewed_at_utc": None,
        "signature": None,
        "customer_data": False,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V21_ENTITY_SCHEMA: " + json.dumps({
        "technical": "PASS",
        "entities": record["catalog"]["entities_verified"],
        "relationships": record["catalog"]["relationships_verified"],
        "preview_rows": record["synthetic_preview"]["total_rows"],
        "foreign_key_violations": record["synthetic_preview"]["foreign_key_violations"],
        "v20_signoff": "BLOCKED",
        "human_schema_review": "PENDING",
        "phase_v22_authorized": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V21EvidenceRejected, entity.EntitySchemaRejected,
            gate_v20.QualityGateRejected, verify_v10.DecisionEvidenceError,
            verify_v11.FieldDictionaryError, verify_v12.SchemaContractError,
            OSError, UnicodeError, KeyError, TypeError, ValueError,
            ArithmeticError, sqlite3.Error):
        # The error class is intentionally not emitted because raw source values
        # and remote database details must not leak in production-style logs.
        print("V21_ENTITY_SCHEMA_FAILED: model_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
