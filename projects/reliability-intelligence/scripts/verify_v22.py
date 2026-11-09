"""V22 identity and reference-data candidate verifier; NO human approval.

Architecture: Define identity and reference-data rules.
Required proof: Uniqueness and link tests.

Replays the V21 synthetic relational model in sqlite3 :memory:, verifies V10
freeze and V20/V21 governance gates, rejects 25 adverse identity variants and
emits a review-ready but unsigned technical evidence packet.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import entity_v21
import gate_v20
import identity_v22 as identity
import lineage_v16
import verify_v10
import verify_v21

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V22"
REPORT = EVIDENCE / "identity_reference_validation.json"
MATRIX = EVIDENCE / "uniqueness_link_matrix.json"
PACKET = EVIDENCE / "unsigned_identity_review.json"


class V22EvidenceError(ValueError):
    """Generic error category, never raw source content."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V22EvidenceError(code)


def generate(*, require_prior_report: bool = False) -> dict[str, Any]:
    cfg = identity.policy()
    identity.validate_policy(cfg)

    # Do not treat CI technical status as approval.
    prev = verify_v21.source_approvals(
        require_v20_report=require_prior_report
    )
    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"] == 18 and
            prev["v20_data_quality_human_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            prev["v21_formal_phase_03_authorized"] is False,
            "prior_phase_authorization_misrepresented")
    if require_prior_report:
        try:
            v21 = json.loads(
                (PROJECT / "evidence/V21/schema_review_validation.json")
                .read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V22EvidenceError("missing_v21_technical_evidence") from None
        require(v21.get("increment") == "V21" and
                v21.get("result") ==
                "candidate_entity_schema_technically_validated_human_review_pending" and
                v21.get("review_status") ==
                "CANDIDATE_TECHNICALLY_CHECKABLE_HUMAN_REVIEW_PENDING" and
                v21.get("source_context", {}).get(
                    "v21_formal_phase_03_authorized") is False,
                "v21_review_state_misrepresented")

    documents, file_sha = lineage_v16.load_source_documents()
    original_sha = {
        path: hashlib.sha256((PROJECT / path).read_bytes()).hexdigest()
        for path in identity.REFERENCE["source_fixture"]
    }
    require(original_sha == file_sha,
            "source_file_digest_changed_before")
    refs = identity.validate_sources(documents)

    db = entity_v21.create_memory_schema()
    try:
        schema = entity_v21.validate_catalog(db, entity_v21.load_model())
        preview = entity_v21.load_synthetic_preview(
            db, entity_v21.load_model()
        )
        checked = identity.validate_sql_keys(db)
        require(preview["total_rows"] == 120 and
                preview["foreign_key_violations"] == 0 and
                checked["uniqueness_views_checked"] == 13 and
                checked["foreign_key_links_checked"] == 9 and
                checked["uniqueness_violations"] == 0 and
                checked["unresolved_links"] == 0,
                "relational_identity_not_verified")
        # All source-specific identity and reference values are explicitly
        # checked in validate_sources; the physical FK/unique view mirrors them.
        require(db.execute("PRAGMA database_list").fetchall()[0][2] == "",
                "unexpected_disk_database")
    finally:
        db.close()
    adverse = identity.exercise_cases(cfg, documents)
    require(adverse["adverse_cases_rejected"] == 25 and
            adverse["source_documents_unchanged"] is True and
            refs["cases"] == 12 and refs["assets"] == 6 and
            refs["evidence_references"] == 11 and
            refs["scripted_review_keys"] == 4 and
            refs["authored_label_keys"] == 12,
            "identity_case_or_source_coverage_missing")
    require({
        path: hashlib.sha256((PROJECT / path).read_bytes()).hexdigest()
        for path in original_sha
    } == original_sha, "fixture_modified_during_review")
    return {
        "increment": "V22",
        "objective": "Define identity and reference-data rules",
        "required_proof": "Uniqueness and link tests",
        "result": "synthetic_identity_links_verified_owner_review_pending",
        "review_status": cfg["review_status"],
        "data_provenance": "three committed fabricated fixture files only",
        "v10_frozen_source_files_verified": 18,
        "source_files_sha256": original_sha,
        "policy_sha256": gate_v20.canonical_sha256(cfg),
        "source_identity": refs,
        "catalog_validation": schema,
        "physical_identity_check": checked,
        "reference_categories": sorted(identity.REFERENCE),
        "reference_category_count": len(identity.REFERENCE),
        "canonical_identifier_patterns_checked": len(identity.PATTERNS),
        "uniqueness_scopes_checked": len(identity.UNIQUE),
        "scoped_links_checked": len(identity.LINKS),
        "adversarial_comparisons": adverse,
        "v21_synthetic_preview_rows": preview["total_rows"],
        "v21_provenance_row_count": preview["counts"]["record_origin"],
        "v20_signoff": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "v21_human_entity_review": "PENDING",
        "v22_human_identity_review": "PENDING",
        "v23_formal_migration_approved": False,
        "customer_data_authorized": False,
        "production_database_approved": False,
        "tenant_authorization_implemented": False,
        "original_source_unchanged": True,
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "limitations": cfg["limitations"],
    }


def main() -> int:
    report = generate(require_prior_report=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {k: v for k, v in report.items()
             if k != "adversarial_comparisons"},
            indent=2, sort_keys=True,
        ) + "\n", encoding="utf-8"
    )
    MATRIX.write_text(
        json.dumps({
            "increment": "V22",
            "required_proof": report["required_proof"],
            "uniqueness": report["physical_identity_check"],
            "source_reference_counts": report["source_identity"],
            "negative_cases": report["adversarial_comparisons"],
            "non_synthetic_source_approved": False,
            "human_review_complete": False,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    PACKET.write_text(
        json.dumps({
            "increment": "V22",
            "objective": report["objective"],
            "required_proof": report["required_proof"],
            "review_state": "UNSIGNED_CANDIDATE",
            "technical_validation": "PASS",
            "human_identity_review": "PENDING",
            "reviewers": [],
            "approved_at_utc": None,
            "signature": None,
            "v10_promotion": "BLOCKED",
            "v20_signoff": report["v20_signoff"],
            "v21_review": report["v21_human_entity_review"],
            "v22_formal_release_approved": False,
            "v23_approved": False,
            "customer_data_access": False,
            "production_persistence": False,
            "no_real_tenant_authentication": True,
            "source_policy_sha256": report["policy_sha256"],
            "unresolved_risks": report["limitations"],
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("V22_IDENTITY_LINKS: " + json.dumps({
        "technical": "PASS",
        "identity_patterns": report["canonical_identifier_patterns_checked"],
        "reference_data_categories": report["reference_category_count"],
        "unique_scopes": report["uniqueness_scopes_checked"],
        "link_checks": report["scoped_links_checked"],
        "reference_errors": 0,
        "negative_cases_rejected":
        report["adversarial_comparisons"]["adverse_cases_rejected"],
        "source_unchanged": report["original_source_unchanged"],
        "human_review": "PENDING",
        "v20_signoff": "BLOCKED",
        "v23_approved": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V22EvidenceError, identity.IdentityRejected,
            entity_v21.EntitySchemaRejected, gate_v20.QualityGateRejected,
            verify_v10.DecisionEvidenceError, verify_v21.V21EvidenceRejected,
            OSError, UnicodeError, TypeError, ValueError, KeyError,
            sqlite3.Error):
        print("V22_IDENTITY_LINKS_FAILED: reference_or_governance_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
