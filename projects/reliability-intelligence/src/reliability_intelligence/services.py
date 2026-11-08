"""V8 regression-verified read-only services and synthetic replay.

No customer connectors, operational data, inference, network calls, mutations,
or operational decisions. Fixed repository fixtures are validated on read.
"""

from __future__ import annotations

from typing import Any

from .fixtures import load_fixture_set, load_demo_review_script
from .workflow import run_demo

SERVICE_VERSION = "0.7.0"


def status(charter: dict[str, Any]) -> dict[str, Any]:
    """Return non-sensitive, declarative capabilities, not plant health."""
    load_fixture_set()  # Fail closed if fixture integrity is invalid.
    load_demo_review_script()  # Fail closed if scripted inputs are invalid.
    return {
        "product": charter["product"],
        "increment": "V8",
        "business_approval": "pending",
        "validated_customer_problem": False,
        "mode": "synthetic_only",
        "production_ready": False,
        "operational_data_loaded": False,
        "synthetic_fixtures_available": True,
        "synthetic_workflow_replay_available": True,
        "structured_failure_diagnostics_available": True,
        "model_present": False,
        "external_integrations_enabled": False,
        "ot_or_cmms_writes_enabled": False,
        "measured_effectiveness": False,
    }


def scope(charter: dict[str, Any]) -> dict[str, Any]:
    """Read-only presentation of the candidate scope and measurement plan."""
    metric = charter["primary_metric"]
    return {
        "customer_partner_authorized": False,
        "user_role_hypothesis": charter["primary_user_role"],
        "buyer_role_hypothesis": charter["buyer_role"],
        "problem_hypothesis": charter["problem"]["statement"],
        "cohort": charter["cohort"],
        "evaluation": {
            "metric": metric["name"],
            "unit": metric["unit"],
            "direction": metric["direction"],
            "relative_improvement_target_pct": metric["proposed_relative_improvement_pct"],
            "baseline": None,
            "result": "not_measured",
        },
        "boundary": {
            "data_mode": "synthetic_only",
            "customer_data": "not_authorized",
            "external_connections": "disabled",
            "work_order_writes": "disabled",
            "ot_control": "disabled",
        },
    }


def cases(charter: dict[str, Any]) -> dict[str, Any]:
    """Expose only version-checked synthetic case records. Not decisions."""
    if charter["data_and_safety"]["data_mode"] != "SYNTHETIC_ONLY":
        raise ValueError("Synthetic-only charter required")
    dataset = load_fixture_set()
    records = [dict(row) for row in dataset["records"]]
    return {
        "items": records,
        "count": len(records),
        "population_status": "synthetic_fixtures_loaded",
        "explanation": "Illustrative fabricated cases only; not real failures, measurements, predictions, or operator decisions.",
        "source": "versioned_local_synthetic_fixture",
        "human_review_enabled": False,
    }


def demo(charter: dict[str, Any]) -> dict[str, Any]:
    """Run V6 in-memory replay, never a plant action or actual approval."""
    return run_demo(charter)
