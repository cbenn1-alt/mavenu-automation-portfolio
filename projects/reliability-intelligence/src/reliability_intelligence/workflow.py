"""V6 deterministic synthetic-only intake -> flags -> scripted review -> export trace.

This is a rehearsal of a human workflow, NOT an actual human approval, a
maintenance recommendation, a predictive system or a durable audit ledger.
It performs no writes and has no OT, CMMS, ERP, network or production access.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from .charter import validate_charter
from .fixtures import InvalidFixture, load_demo_review_script, load_fixture_set

DEMO_RUN_ID = "SYN-RI-V6-DEMO-001"
RULE_VERSION = "v6.0"
REPEAT_WINDOW_DAYS = 30


def _canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def run_demo(charter: dict[str, Any]) -> dict[str, Any]:
    """Replay a complete, deterministic, in-memory fictional maintenance workflow.

    Checks repeat history using *only earlier events* from the same asset/failure
    within 30 elapsed days; does not inspect V5 reference_labels.json. Such a
    flag is a transparent illustrative rule, NOT a diagnosis or risk score.
    """
    validate_charter(charter)
    fixture_set = load_fixture_set()
    scripted_reviews = load_demo_review_script()
    if scripted_reviews["fixture_set_id"] != fixture_set["fixture_set_id"]:
        raise InvalidFixture("Demo script and cases use different fixture sets")
    review_by_case = {row["case_id"]: row for row in scripted_reviews["entries"]}

    records = sorted(
        fixture_set["records"],
        key=lambda record: (record["occurred_at_utc"], record["case_id"]),
    )
    seen: dict[tuple[str, str], list[tuple[datetime, str]]] = {}
    events: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    synthetic_flag_counts = {"missing_evidence_reference": 0, "repeat_within_30_days": 0}

    def emit(case_id: str, stage: str, detail: dict[str, Any]) -> None:
        events.append({
            "sequence": len(events) + 1,
            "case_id": case_id,
            "stage": stage,
            "detail": detail,
        })

    for record in records:
        cid = record["case_id"]
        when = datetime.strptime(record["occurred_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
        key = (record["asset_id"], record["failure_code"])
        emit(cid, "intake", {
            "fixture_set_id": fixture_set["fixture_set_id"],
            "work_order_ref": record["work_order_ref"],
            "synthetic": True,
        })
        refs = list(record["evidence_refs"])
        emit(cid, "evidence_check", {
            "synthetic_evidence_refs": refs,
            "reference_count": len(refs),
            "evidence_documents_present": False,
        })

        prior = [
            prior_cid for earlier, prior_cid in seen.get(key, [])
            if timedelta(0) <= when - earlier <= timedelta(days=REPEAT_WINDOW_DAYS)
        ]
        # Record the current event only after examining previous events.
        seen.setdefault(key, []).append((when, cid))
        flags: list[str] = []
        if not refs:
            flags.append("missing_evidence_reference")
        if prior:
            flags.append("repeat_within_30_days")
        for flag in flags:
            synthetic_flag_counts[flag] += 1
        emit(cid, "rules_review", {
            "rule_version": RULE_VERSION,
            "synthetic_flags": flags,
            "preceding_matching_case_ids": prior,
            "not_maintenance_priority": True,
        })

        script = review_by_case.get(cid)
        disposition = None
        if script is not None:
            if script["disposition"] == "request_evidence" and "missing_evidence_reference" not in flags:
                raise InvalidFixture("Script asks for missing reference without corresponding fixture flag")
            if script["disposition"] == "investigate_history" and "repeat_within_30_days" not in flags:
                raise InvalidFixture("Script asks for repeat history without corresponding fixture flag")
            if script["disposition"] == "acknowledge" and flags:
                raise InvalidFixture("Routine scripted acknowledgement cannot conceal flagged case")
            disposition = {
                "value": script["disposition"],
                "reason_code": script["reason_code"],
                "reviewer_id": script["reviewer_id"],
                "scripted_synthetic": True,
                "performed_by_real_human": False,
                "operational_approval": False,
            }
            emit(cid, "simulated_reviewer_disposition", disposition)
            emit(cid, "in_memory_export", {
                "export_type": "synthetic_demo_trace_only",
                "persistent_file_created": False,
                "external_action_executed": False,
            })
            workflow_state = "scripted_disposition_exported"
        else:
            emit(cid, "awaiting_demo_review", {
                "state": "not_dispositioned",
                "not_a_work_order_queue": True,
            })
            workflow_state = "not_dispositioned"

        outputs.append({
            "case_id": cid,
            "asset_id": record["asset_id"],
            "occurred_at_utc": record["occurred_at_utc"],
            "synthetic_evidence_refs": refs,
            "synthetic_flags": flags,
            "preceding_matching_case_ids": prior,
            "workflow_state": workflow_state,
            "simulated_disposition": disposition,
        })

    if len(outputs) != 12 or len(review_by_case) != 4:
        raise InvalidFixture("Unexpected end-to-end demo scope")
    digest = hashlib.sha256(_canonical(events)).hexdigest()
    return {
        "run_id": DEMO_RUN_ID,
        "fixture_set_id": fixture_set["fixture_set_id"],
        "rule_version": RULE_VERSION,
        "mode": "deterministic_synthetic_replay",
        "case_count": len(outputs),
        "scripted_disposition_count": len(review_by_case),
        "not_dispositioned_count": len(outputs) - len(review_by_case),
        "synthetic_flag_counts": synthetic_flag_counts,
        "cases": outputs,
        "events": events,
        "event_count": len(events),
        "trace_sha256": digest,
        "trace_checksum_kind": "reproducibility_checksum_not_cryptographic_attestation",
        "trace_persisted": False,
        "real_human_review_performed": False,
        "actual_customer_data_used": False,
        "operational_approval_granted": False,
        "real_work_orders_written": False,
        "external_actions_executed": False,
        "measured_business_outcome": False,
        "explanation": (
            "Fabricated events, rules and reviewer-role dispositions. "
            "This is a reproducible in-memory demonstration, not real human sign-off, "
            "an operational maintenance workflow, or an immutable production audit."
        ),
    }
