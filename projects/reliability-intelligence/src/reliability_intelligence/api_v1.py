"""V5 HTTP-independent v1 API contract and response composition.

The transport is owned by web.py; services.py is pure business-facing metadata.
Any non-v1 path must be rejected rather than silently accepting it.
"""

from __future__ import annotations

import json
from typing import Any

from . import services

API_VERSION = "v1"
API_SCHEMA_VERSION = "1.1.0"
API_MEDIA_TYPE = "application/json; charset=utf-8"

ROUTE_DESCRIPTIONS = {
    "/api/v1/status": "Prototype readiness disclosure, not plant uptime.",
    "/api/v1/scope": "Proposed, unapproved maintenance-review scope and evaluation.",
    "/api/v1/cases": "Validated local synthetic cases only; no real equipment records.",
    "/api/v1/contract": "Machine-readable v1 endpoint and field contract.",
}

REQUIRED_FIELDS = {
    "status": (
        "product", "increment", "business_approval", "validated_customer_problem",
        "mode", "production_ready", "operational_data_loaded",
        "synthetic_fixtures_available", "model_present",
        "external_integrations_enabled", "ot_or_cmms_writes_enabled",
        "measured_effectiveness",
    ),
    "scope": (
        "customer_partner_authorized", "user_role_hypothesis",
        "buyer_role_hypothesis", "problem_hypothesis", "cohort",
        "evaluation", "boundary",
    ),
    "cases": (
        "items", "count", "population_status", "explanation", "source",
        "human_review_enabled",
    ),
}
RESOURCES = {
    "/api/v1/status": ("status", services.status),
    "/api/v1/scope": ("scope", services.scope),
    "/api/v1/cases": ("cases", services.cases),
}


def contract() -> dict[str, Any]:
    """Describe implemented endpoints and the additive V5 fixture population."""
    return {
        "api_version": API_VERSION,
        "schema_version": API_SCHEMA_VERSION,
        "transport": "local_loopback_http",
        "allowed_methods": ["GET", "HEAD"],
        "response_envelope": ["api_version", "schema_version", "resource", "data"],
        "routes": {
            path: {
                "methods": ["GET", "HEAD"],
                "description": description,
                "read_only": True,
                "implemented": True,
            }
            for path, description in ROUTE_DESCRIPTIONS.items()
        },
        "required_data_fields": {name: list(fields) for name, fields in REQUIRED_FIELDS.items()},
        "error_envelope": {
            "api_version": API_VERSION,
            "error": {"code": "snake_case", "message": "non-sensitive explanation"},
        },
        "limits": {
            "customer_data_supported": False,
            "write_endpoints": False,
            "case_fixtures_loaded": True,
            "public_network_hosting": False,
        },
    }


def data_for_path(path: str, charter: dict[str, Any]) -> dict[str, Any]:
    """Build a stable v1 response without any transport or side effects."""
    if path == "/api/v1/contract":
        resource = "contract"
        payload = contract()
    else:
        try:
            resource, service = RESOURCES[path]
        except KeyError:
            raise KeyError("unrecognized API path") from None
        payload = service(charter)
        if not isinstance(payload, dict) or any(key not in payload for key in REQUIRED_FIELDS[resource]):
            raise ValueError("API response violates required v1 fields")
    return {
        "api_version": API_VERSION,
        "schema_version": API_SCHEMA_VERSION,
        "resource": resource,
        "data": payload,
    }


def error(code: str, message: str) -> dict[str, Any]:
    """Uniform and non-sensitive error contract; no internal exception details."""
    return {"api_version": API_VERSION, "error": {"code": code, "message": message}}


def serialize(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
