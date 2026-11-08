# Reliability Intelligence API v1 — V7 structured diagnostic addition

**Contract ID:** reliability-intelligence.api.v1
**Approval:** Technical candidate for local evaluation only. Customer data and external deployment prohibited.

## Separation of concerns

1. product_charter.json and charter.py define and fail-closed validate V2 problem and safety boundaries.
2. services.py provides read-only status, scope and cases; V5 reads only pinned, fabricated local JSON; no network calls, databases, inference or writes.
3. api_v1.py composes versioned envelopes and the machine-readable required-field manifest without knowing HTTP.
4. web.py implements local WSGI GET/HEAD routing, no CORS grant, no mutation and structured errors.
5. tests/test_api_contract.py proves contract shapes and negative cases; earlier V2/V3 tests still run.

The word status means prototype software readiness, not physical equipment condition.

## Version and data contract

- API namespace: /api/v1. Other versions return 404, not a silent alias.
- Media type: application/json; charset=utf-8.
- Success envelope: api_version (v1), schema_version (1.1.0), resource, data.
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

Actual JSON is compact with sorted keys. Scope identifies only unconfirmed personas and an unmeasured proposed benefit. V5 cases contain 12 fabricated records and population_status=synthetic_fixtures_loaded. They are not actual machine failures. Separately authored reference labels are never returned in the API.

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


## V5 additive contract revision — schema 1.1.0

The API route list and GET/HEAD methods remain unchanged. The versioned cases collection now contains twelve records with SYN- identifiers, synthetic=true and review_state=fixture_only. The top-level cases response fields remain the same. Consumers must not treat a nonempty synthetic collection as actual customer failures.

Status adds synthetic_fixtures_available=true while retaining operational_data_loaded=false, model_present=false and production_ready=false. The v1 contract limits set case_fixtures_loaded=true. Fixture integrity errors return 503 with error.code=fixture_invalid and a non-sensitive message. This is an additive v1 schema update, not a new endpoint or authorization to ingest production data.

The reference_labels.json file is never loaded into user-facing service methods and is not exposed in HTTP responses or the workbench. See fixtures/README.md for file fields, limitations and provenance. No autonomous decision or work-order mutation exists.


## V6 additive contract revision — schema 1.2.0

New read-only GET/HEAD /api/v1/demo endpoint returns the deterministic, wholly fictional synthetic workflow trace with resource=demo; the existing endpoints keep their routes and representation envelopes. Software status adds synthetic_workflow_replay_available=true while operational_data_loaded=false and production_ready=false stay unchanged.

The demo response includes run_id, fixture_set_id, rule_version, case_count, scripted_disposition_count, not_dispositioned_count, synthetic_flag_counts, cases, events, event_count, trace_sha256, trace_checksum_kind, trace_persisted=false, real_human_review_performed=false, actual_customer_data_used=false, operational_approval_granted=false, real_work_orders_written=false, external_actions_executed=false, measured_business_outcome=false, and explanation.

The checksum is for repeatability of canonical in-memory event JSON only. The four scripted dispositions are not human decisions and eight cases remain undispositioned. Missing/bad fixture or script yields sanitized HTTP 503 with error.code=fixture_invalid; POST and other unsafe verbs still return 405. No production case actions or external writes are available. Future clients must not treat this synthetic replay as an operational event log.


## V7 compatible diagnostic revision — schema 1.3.0

GET/HEAD endpoints and their success envelope remain unchanged. Service status adds structured_failure_diagnostics_available=true. API schema version advances to 1.3.0. The documented limits now include structured_failure_diagnostics_available=true and diagnostic_logs_persistent=false.

For failing API requests, the existing error.code/message JSON structure remains compatible. The HTTP response now adds X-Diagnostic-Code and X-Diagnostic-ID headers with allowlisted values. The diagnostic ID is a **stable category fingerprint**, not a unique request correlation ID, and its reuse must not be interpreted as multiple calls to the same incident.

Expected 404, 405 and 503 responses are preserved. An unexpected internal API error returns a sanitized 500 instead of propagating raw Python error details to clients. The V7 logger emits one compact JSON event, without raw exceptions, headers, paths, queries or payloads. It does not manage the surrounding WSGI server access log, which can record requests separately and requires a later security review.

All requests remain loopback-only; no write routes, customer data, production credentials or external integration are introduced. See docs/DIAGNOSTICS_V7.md for catalog, schema and limitations.
