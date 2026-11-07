# Reliability Intelligence API v1 — V4 technical contract

**Contract ID:** reliability-intelligence.api.v1
**Approval:** Technical candidate for local evaluation only. Customer data and external deployment prohibited.

## Separation of concerns

1. product_charter.json and charter.py define and fail-closed validate V2 problem and safety boundaries.
2. services.py exposes pure read-only functions: status, scope and cases; no network calls, database, machine inference or file writes.
3. api_v1.py composes versioned envelopes and the machine-readable required-field manifest without knowing HTTP.
4. web.py implements local WSGI GET/HEAD routing, no CORS grant, no mutation and structured errors.
5. tests/test_api_contract.py proves contract shapes and negative cases; earlier V2/V3 tests still run.

The word status means prototype software readiness, not physical equipment condition.

## Version and data contract

- API namespace: /api/v1. Other versions return 404, not a silent alias.
- Media type: application/json; charset=utf-8.
- Success envelope: api_version (v1), schema_version (1.0.0), resource, data.
- API routes: /api/v1/status, /api/v1/scope, /api/v1/cases, /api/v1/contract.
- Methods: GET and HEAD; HEAD has no entity body, preserves GET representation length.
- Required data fields are exposed at /api/v1/contract and validated by automated tests.
- JSON is deterministic; unknown query strings do not activate additional capabilities or data.
- No authentication claims, CORS grant, public interface, persistent storage, production telemetry or customer access.
- Future incompatible contracts require an explicit new major version and additional tests.

## Status representation (illustrative)

~~~~json
{
  "api_version": "v1",
  "schema_version": "1.0.0",
  "resource": "status",
  "data": {
    "product": "Mavenu Reliability Intelligence",
    "increment": "V4",
    "business_approval": "pending",
    "validated_customer_problem": false,
    "mode": "synthetic_only",
    "production_ready": false,
    "operational_data_loaded": false,
    "model_present": false,
    "external_integrations_enabled": false,
    "ot_or_cmms_writes_enabled": false,
    "measured_effectiveness": false
  }
}
~~~~

Actual JSON is compact with sorted keys. Scope identifies only unconfirmed personas and an unmeasured proposed benefit. The cases response has an empty array and population_status=not_implemented. Zero loaded cases must never be interpreted as zero actual equipment failures.

## Negative paths

| Condition | HTTP | Error |
|---|---|---|
| Unknown API version or endpoint | 404 | not_found |
| POST, PUT, PATCH, DELETE, OPTIONS | 405 | method_not_allowed |
| Missing or invalid local candidate charter | 503 | charter_invalid |
| Internal service violates required response fields | 503 | contract_failure |

The error envelope contains api_version and error.code/error.message. It never includes a stack trace or charter parsing details.

## Readiness and change control

V4 is a local transport/service contract, not operational software. Live customer access, per-tenant authorization, logging, provenance, secure secrets, isolation, rate limiting, data correctness, safety case and pilot evaluation belong to later independently approved increments. Never expose V4 publicly. A signed technical release decision remains necessary after CI and reviewer smoke evidence.
