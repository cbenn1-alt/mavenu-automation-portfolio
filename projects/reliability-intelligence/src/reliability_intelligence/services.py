"""V4 pure read-only service boundary.

No customer connectors, data access, inference, external calls, mutations, or
operational decisions are implemented. This module consumes a validated V2
candidate charter and emits only synthetic-prototype metadata.
"""

from __future__ import annotations

from typing import Any

SERVICE_VERSION = "0.4.0"


def status(charter: dict[str, Any]) -> dict[str, Any]:
    """Return non-sensitive, declarative capabilities, not plant health."""
    return {
        "product": charter["product"],
        "increment": "V4",
        "business_approval": "pending",
        "validated_customer_problem": False,
        "mode": "synthetic_only",
        "production_ready": False,
        "operational_data_loaded": False,
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
    """An explicitly *unpopulated* case collection, not a no-failures claim.

    V5 will add representative synthetic fixtures. No repository data is
    accessed here, and the function never emits real or fake work orders.
    """
    _ = charter
    return {
        "items": [],
        "count": 0,
        "population_status": "not_implemented",
        "explanation": "Synthetic case fixtures are planned for V5; zero items is not evidence of zero failures.",
        "source": "none",
        "human_review_enabled": False,
    }
