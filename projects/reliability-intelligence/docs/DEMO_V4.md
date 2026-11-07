# V4 contract smoke test

**Exact requirement:** Create versioned API/service boundaries. **Evidence:** Contract smoke test (Mavenu Development Architecture V4, p. 42).

## Step 1 — clean local validation

Use Python 3.11+, on feature/reliability-intelligence-v4, in the projects/reliability-intelligence directory.

~~~~bash
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
~~~~

Expected 12 V2 + 19 V3 + 17 V4 = 48 automated tests. Record actual CI outcome before declaring technical verification.

## Step 2 — local transport

~~~~bash
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

The process binds only to 127.0.0.1. Confirm that the V3 four-page UI remains navigable.

## Step 3 — v1 success/negative-path proof

~~~~bash
curl -i http://127.0.0.1:8765/api/v1/status
curl -i http://127.0.0.1:8765/api/v1/scope
curl -i http://127.0.0.1:8765/api/v1/cases
curl -i http://127.0.0.1:8765/api/v1/contract
curl -I http://127.0.0.1:8765/api/v1/status
curl -i http://127.0.0.1:8765/api/v2/status
curl -i -X POST http://127.0.0.1:8765/api/v1/cases
~~~~

Proof to record: four 200 results; stable schema_version 1.0.0; HEAD has no body; v2 version returns 404; POST returns 405 and Allow GET, HEAD; no CORS grant; restrictive CSP, no-store and nosniff; explicit cases not_implemented. There must be no real or synthetic work orders in V4.

## Step 4 — release decision

Review docs/releases/V4.md. Independent reviewer smoke and named owner signature are still required. V2 customer problem approval remains unresolved. Tests are neither a customer agreement nor an industrial-safety demonstration.
