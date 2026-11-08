"""V2 machine-readable product charter contract; no operational analytics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CHARTER = Path(__file__).resolve().parents[2] / "product_charter.json"


class InvalidCharter(ValueError):
    """The problem/outcome contract is missing or crosses an operating boundary."""


def validate_charter(data: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on claims of approvals, customer access, or ambiguous outcomes."""
    try:
        problem = data["problem"]
        metric = data["primary_metric"]
        controls = data["data_and_safety"]
        approval = data["approval"]
        required_texts = (
            data["product"], data["primary_user_role"],
            data["buyer_role"], problem["statement"],
            data["proposed_workflow"], data["cohort"],
            metric["name"], metric["unit"], metric["evaluation_method"],
        )
        if any(not isinstance(value, str) or not value.strip() for value in required_texts):
            raise InvalidCharter("Missing a required role, problem, cohort, workflow, or metric")
        if data["increment"] != "V2" or data["state"] != "CANDIDATE_NOT_APPROVED":
            raise InvalidCharter("V2 must remain a candidate pending owner approval")
        if problem["customer_validation"] != "NOT_OBTAINED" or problem["incumbent_capability_check"] != "NOT_PERFORMED":
            raise InvalidCharter("Customer or current-system validation cannot be asserted at V2")
        if problem["baseline_observed"] is not False or metric["baseline_minutes_per_case"] is not None:
            raise InvalidCharter("No real customer baseline has been measured")
        pct = metric["proposed_relative_improvement_pct"]
        if type(pct) not in (int, float) or not 0 < pct <= 100:
            raise InvalidCharter("Improvement target must be a bounded percentage")
        if metric["direction"] != "decrease" or metric["measurement_status"] != "NOT_MEASURED":
            raise InvalidCharter("Metric must be directional and explicitly unmeasured")
        if controls["data_mode"] != "SYNTHETIC_ONLY":
            raise InvalidCharter("Only synthetic data are permitted")
        banned_switches = (
            "customer_data_authorized", "external_integrations_enabled",
            "plc_scada_ot_writes_enabled", "maintenance_order_writes_enabled",
            "production_deployment_allowed", "ai_model_trained",
        )
        if any(controls[switch] is not False for switch in banned_switches):
            raise InvalidCharter("Unsafe data, integration, deployment, or inference capability declared")
        if approval["status"] != "PENDING" or approval["release_gate_passed"] is not False:
            raise InvalidCharter("Only an accountable human may approve promotion")
        if any(approval[key] is not None for key in (
            "internal_product_owner", "customer_sponsor", "isnt_security_approver", "approved_at_utc"
        )):
            raise InvalidCharter("Unverified approvers/signatures must remain empty")
        if data["economics"]["cost_savings_claimed"] is not False:
            raise InvalidCharter("No savings or ROI have been demonstrated")
    except (KeyError, TypeError) as error:
        raise InvalidCharter("Charter is structurally incomplete") from error
    return data


def load_charter(path: str | Path = DEFAULT_CHARTER) -> dict[str, Any]:
    """Load and validate a locally stored, inert JSON requirements artifact."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidCharter("Unable to read charter JSON") from error
    if not isinstance(data, dict):
        raise InvalidCharter("Charter must be a JSON object")
    return validate_charter(data)
