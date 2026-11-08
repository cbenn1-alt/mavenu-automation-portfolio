"""V20 synthetic data quality sign-off *packet*, not actual human approval.

The completed checks demonstrate the V11-V19 artifacts are consistently
reproduced in the same isolated Git archive. They cannot sign off real source
semantics, authorize customer access, or override the blocked V10 decision.

To run: PYTHONPATH=src python scripts/verify_v20.py
Requires the V8-V19 verifier commands to have generated their local evidence.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import gate_v20 as gate
import verify_v10
import verify_v11
import verify_v12

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "evidence" / "V20"
REPORT = OUTPUT / "verification.json"
MANIFEST = OUTPUT / "evidence_manifest.json"
PACKET = OUTPUT / "data_quality_signoff_packet.json"


class V20EvidenceError(ValueError):
    """Fixed code only, never raw evidence or personal data."""


def require(ok: Any, code: str) -> None:
    if not ok:
        raise V20EvidenceError(code)


def load_evidence(register: dict[str, Any]) -> tuple[
    dict[str, dict[str, Any]], list[dict[str, Any]]
]:
    reports: dict[str, dict[str, Any]] = {}
    inventory: list[dict[str, Any]] = []
    entries = (register["evidence_policy"]["supporting_evidence"] +
               register["evidence_policy"]["required_stages"])
    for entry in entries:
        path = entry["evidence_path"]
        # Only allowlisted repo-relative evidence locations can be read.
        require(path.startswith("evidence/") and
                ".." not in Path(path).parts and
                path.endswith(".json"), "unexpected_evidence_path")
        file = PROJECT / path
        try:
            raw = file.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise V20EvidenceError("missing_or_malformed_stage_evidence") from None
        require(type(value) is dict, "stage_evidence_not_object")
        reports[path] = value
        inventory.append({
            "increment": entry["increment"],
            "path": path,
            "sha256_exact_report_bytes": gate.sha256(raw),
            "sha256_canonical_json": gate.canonical_sha256(value),
            "bytes": len(raw),
        })
    return reports, inventory


def generate() -> dict[str, Any]:
    register, blank = gate.baseline(), gate.signoff()
    gate.validate_baseline(register, blank)
    upstream = gate.validate_source_approvals()
    frozen = verify_v10.verify_freeze(
        verify_v10.read_json(verify_v10.BASELINE)
    )
    require(frozen["frozen_files_verified"] == 18,
            "frozen_source_integrity_invalid")
    v11 = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    verify_v11.validate_dictionary(v11)
    v12 = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    verify_v12.validate_contract(v12, v11)
    reports, inventory = load_evidence(register)
    v8 = reports["evidence/V8/verification.json"]
    need_tests = v8.get("test_count")
    need_coverage = v8.get("coverage_total_percent")
    outcome = gate.evaluate_quality_gate(
        register, blank, reports, need_coverage, need_tests
    )
    require(outcome["evidence"]["reports_verified"] == 11 and
            outcome["evidence"]["v11_v19_reports_verified"] == 9 and
            outcome["blockers_unresolved"] == 8 and
            outcome["human_data_quality_signoff"] ==
            "BLOCKED_PENDING_HUMAN_SIGNOFF" and
            outcome["future_phase_v21_authorized"] is False,
            "data_quality_signoff_improperly_claimed")
    # The report's SHA-256 fingerprint is an evidence reproducibility aid,
    # not a digital signature or proof of independent human acceptance.
    immutable = {
        "V10_unmodified_source_paths": frozen["frozen_files_verified"],
        "V11_source_dictionary": upstream["v11_dictionary"],
        "V12_schema": upstream["v12_schema"],
        "evidence_manifest_sha256": gate.canonical_sha256(inventory),
        "baseline_contract_sha256": gate.canonical_sha256(register),
        "unsigned_signoff_template_sha256": gate.canonical_sha256(blank),
    }
    return {
        "increment": "V20",
        "objective": "Approve data correctness test baseline",
        "required_proof": "Data quality sign-off",
        "result": "synthetic_baseline_verified_formal_signoff_blocked",
        "technical": outcome,
        "governance": upstream,
        "frozen_integrity": immutable,
        "evidence_manifest": inventory,
        "decision": {
            "recommendation": "DO_NOT_PROMOTE",
            "status": "BLOCKED_PENDING_HUMAN_SIGNOFF",
            "signed": False,
            "phase_02_formally_accepted": False,
            "phase_03_v21_authorized": False,
            "customer_data_authorized": False,
            "production_deployment_authorized": False,
            "human_signatures_produced_by_ci": False,
            "blocking_items": register["gate_policy"]["blocking_items"],
            "required_owner_roles": sorted({b["owner_role"]
                                            for b in register["gate_policy"]["blocking_items"]}),
        },
        "github_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "notes": [
            "This packet is an UNSIGNED data-quality decision request, not an actual data-quality sign-off.",
            "V10 formal phase approval remains blocked; V11 and V12 source contracts are unapproved.",
            "The green synthetic CI baseline does not establish independent domain truth or customer rights.",
            "This version does not change V9 runtime, read-only API, or production integrations.",
        ],
    }


def main() -> int:
    data = generate()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        key: value for key, value in data.items()
        if key not in ("evidence_manifest", "decision")
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps({
        "increment": "V20",
        "provenance": "same synthetic CI checkout only",
        "signed": False,
        "reports": data["evidence_manifest"],
        "manifest_sha256": data["frozen_integrity"]["evidence_manifest_sha256"],
        "customer_data": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PACKET.write_text(json.dumps({
        "increment": "V20",
        "required_proof": "Data quality sign-off",
        "technical_verification": data["technical"]["technical_evidence"],
        "signoff_provided": False,
        "status": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "signoff_template": gate.signoff(),
        "decision": data["decision"],
        "technical_evidence_digest": data["frozen_integrity"]["evidence_manifest_sha256"],
        "formal_v10_phase_gate": data["governance"]["v10_formal_promotion"],
        "v11_source_dictionary": data["governance"]["v11_dictionary"],
        "v12_schema": data["governance"]["v12_schema"],
        "customer_data": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("V20_DATA_QUALITY_GATE: " + json.dumps({
        "technical": "PASS",
        "signoff": "BLOCKED_PENDING_HUMAN_SIGNOFF",
        "evidence_reports": len(data["evidence_manifest"]),
        "data_correctness_stages": data["technical"]["evidence"]["v11_v19_reports_verified"],
        "automated_tests": data["technical"]["tests_verified"],
        "coverage_percent": data["technical"]["source_coverage_percent"],
        "frozen_paths": data["frozen_integrity"]["V10_unmodified_source_paths"],
        "unresolved_blockers": data["technical"]["blockers_unresolved"],
        "phase_v21_authorized": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (V20EvidenceError, gate.QualityGateRejected,
            verify_v10.DecisionEvidenceError, verify_v11.FieldDictionaryError,
            verify_v12.SchemaContractError, TypeError, ValueError,
            KeyError, OSError):
        print("V20_DATA_QUALITY_GATE_FAILED: evidence_or_approval_invariant",
              file=sys.stderr)
        raise SystemExit(1) from None
