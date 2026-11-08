"""V7 safe, structured, allowlist-only failure diagnostics.

Events are emitted as compact JSON through Python logging to process stderr.
They carry *only* static code/stage/surface metadata. Never record exceptions,
request paths, queries, headers, tokens, user input, customer data or stack traces.

A diagnostic ID is a deterministic category fingerprint, NOT a request ID,
transaction ID, durable log identifier, signature or observability service.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

DIAGNOSTIC_SCHEMA_VERSION = "1.0.0"
LOGGER = logging.getLogger("mavenu.reliability.diagnostics")

# Code -> (response/exit status, severity, public text); no caller-supplied text.
CATALOG: dict[str, tuple[int, str, str]] = {
    "not_found": (404, "warning", "Unknown API resource or version."),
    "method_not_allowed": (405, "warning", "GET or HEAD only."),
    "charter_invalid": (503, "error", "Requirements contract unavailable."),
    "fixture_invalid": (503, "error", "Synthetic fixture unavailable."),
    "contract_failure": (503, "error", "Versioned response unavailable."),
    "stylesheet_unavailable": (503, "error", "Stylesheet unavailable."),
    "internal_failure": (500, "error", "Prototype request failed safely."),
    "ui_route_not_found": (404, "warning", "Not found."),
    "ui_method_not_allowed": (405, "warning", "Read-only interface. GET or HEAD only."),
    "cli_demo_invalid": (2, "error", "Synthetic demo inputs invalid; replay stopped."),
    "cli_charter_invalid": (2, "error", "Requirements contract invalid; command stopped."),
}
STAGES = frozenset(("routing", "authorization", "charter", "fixture", "contract", "render", "cli"))
SURFACES = frozenset(("api", "ui", "static", "cli"))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def event(code: str, *, stage: str, surface: str, simulated: bool = False) -> dict[str, Any]:
    """Produce a rigid, deterministic diagnostic with NO free-form fields."""
    if code not in CATALOG or stage not in STAGES or surface not in SURFACES:
        raise ValueError("Unknown allowlisted diagnostic code/stage/surface")
    if type(simulated) is not bool:
        raise ValueError("Simulated flag must be boolean")
    status, level, message = CATALOG[code]
    # FINGERPRINT of a category; repeating the same error yields same value.
    fingerprint = hashlib.sha256(_canonical({
        "code": code, "stage": stage, "surface": surface,
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
    })).hexdigest()[:16]
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_id": f"SYN-DIAG-{fingerprint}",
        "id_semantics": "stable_error_category_fingerprint_not_unique_occurrence",
        "code": code,
        "level": level,
        "stage": stage,
        "surface": surface,
        "status": status,
        "message": message,
        "synthetic_only": True,
        "simulated_injection": simulated,
        "exception_details_recorded": False,
        "request_contents_recorded": False,
        "persistent_log_storage": False,
    }


def emit(code: str, *, stage: str, surface: str) -> dict[str, Any]:
    """Send one sanitized JSON-line event to process-local Python logging."""
    payload = event(code, stage=stage, surface=surface)
    severity = logging.ERROR if payload["level"] == "error" else logging.WARNING
    # Do NOT use logger.exception(), exc_info, traceback or user-derived strings.
    LOGGER.log(severity, _canonical(payload).decode("ascii"))
    return payload


def diagnostic_demo() -> dict[str, Any]:
    """Generate intentionally simulated negative-path examples; no I/O."""
    samples = [
        event("not_found", stage="routing", surface="api", simulated=True),
        event("method_not_allowed", stage="routing", surface="api", simulated=True),
        event("charter_invalid", stage="charter", surface="api", simulated=True),
        event("fixture_invalid", stage="fixture", surface="api", simulated=True),
        event("contract_failure", stage="contract", surface="api", simulated=True),
        event("internal_failure", stage="render", surface="ui", simulated=True),
    ]
    return {
        "increment": "V7",
        "mode": "synthetic_negative_path_catalog",
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "simulated": True,
        "sample_count": len(samples),
        "samples": samples,
        "persistent_log_created": False,
        "customer_data_used": False,
        "actual_incidents_observed": False,
        "explanation": (
            "Fixed fictional failure examples only. Diagnostic IDs are "
            "category fingerprints, not unique occurrences or production traces."
        ),
    }
