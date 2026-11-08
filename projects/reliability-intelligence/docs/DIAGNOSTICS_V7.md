# V7 structured failure and diagnostic specification

**Development standard:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**V7 objective:** Add structured failures and diagnostic logs.
**Primary proof:** Negative-path verification.

## Boundary

src/reliability_intelligence/diagnostics.py defines the only diagnostic event constructor. A caller may supply only one catalog error code, one allowlisted stage and one allowlisted surface. Unknown codes, surfaces or stages are rejected before emission. No user-provided error text is allowed.

### Event JSON (illustrative fields)

- schema_version: fixed diagnostic schema 1.0.0
- diagnostic_id: SYN-DIAG- plus first 16 SHA-256 hex characters of the code/stage/surface/schema tuple
- id_semantics: stable_error_category_fingerprint_not_unique_occurrence
- code: allowlisted diagnostic category
- level: warning for method/path rejection, error for unavailable/failed behavior
- stage: routing, charter, fixture, contract, render or cli
- surface: api, ui, static or cli
- status: fixed HTTP status or CLI exit code from the catalog
- message: predefined public explanation, never source exception text
- synthetic_only: true; simulated_injection: false for actual prototype failures
- exception_details_recorded: false
- request_contents_recorded: false
- persistent_log_storage: false

The deterministic fingerprint identifies **an error category**, not a distinct request or end-to-end incident. Two identical category/stage/surface failures share a fingerprint. Neither a unique request identifier nor operational audit correlation has been implemented.

### Error catalog

| Code | Status | Behavior |
|---|---:|---|
| not_found | 404 | Unknown API path/version |
| method_not_allowed | 405 | API requires GET or HEAD |
| charter_invalid | 503 | Invalid candidate product charter |
| fixture_invalid | 503 | Modified/unavailable synthetic input |
| contract_failure | 503 | Versioned API service contract failure |
| stylesheet_unavailable | 503 | Missing local CSS asset |
| internal_failure | 500 | Unexpected API/UI exception, no details leaked |
| ui_route_not_found | 404 | Unknown static UI page |
| ui_method_not_allowed | 405 | Unsafe HTML page method |
| cli_demo_invalid | exit 2 | Invalid scripted synthetic replay |
| cli_charter_invalid | exit 2 | CLI charter check fails |

The API response JSON preserves the pre-V7 error envelope. Header values X-Diagnostic-Code and X-Diagnostic-ID are added for failures only. HEAD returns the same response headers and hypothetical body length, but no entity bytes.

### Logging design and limitations

The module emits compact JSON through a named Python logger. There is **no persistence, timestamp, retention policy, per-request identifier, external correlation, alert integration, telemetry exporter, authentication, or production security certification**. A host process may configure Python handlers differently; the intended development use is console/stderr emission without application-managed files.

The V7 logger never receives raw WSGI request paths, query strings, headers, request bodies, exception messages or tracebacks, which restricts accidental disclosure. Python's surrounding WSGI server may generate independent access logs; those are **not covered by this allowlist guarantee**. Do not attach any live customer data to this prototype.

All failures should stop safely; an unexpected API or page rendering exception produces HTTP 500 and a non-sensitive message rather than propagating the Python error to the browser. Expected fixture or charter failures retain HTTP 503. No automatic retry is performed.

### Diagnostic demonstration and evidence

The diagnose CLI returns six fixed synthetic error examples with simulated_injection=true. These are test inputs, not real production incidents. V7 tests exercise HTTP 404/405/500/503, malformed inputs, CLI/JSON output, deterministic fingerprints, redaction, HEAD behavior, safe success paths and unchanged OT restrictions.

Prior V6 trace_sha256 is not modified by diagnostics. The trace checksum is for reproducibility only, and is independent of the transient diagnostic events.

## Acceptance criteria

- Hosted tests pass on the exact V7 commit.
- Independent engineer replays the negative paths from docs/DEMO_V7.md.
- Security reviewer checks that no request/exception/secret text reaches the V7 logger or client.
- Engineering/product owner signs a bounded V7 increment decision.
- Upstream V2–V6 acceptance and V1 Git continuity remain open dependencies.

This is not a plant safety case, production observability design, audit log, incident-response service or authorized integration.
