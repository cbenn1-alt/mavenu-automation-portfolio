# V7 — negative-path verification and reviewer replay

**Exact proof:** Negative-path verification (Mavenu Development Architecture V4, p.42).

## 1. Clean test and fixed synthetic diagnostic catalog

On the feature/reliability-intelligence-v7 branch, from projects/reliability-intelligence:

~~~~bash
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m reliability_intelligence diagnose --json
PYTHONPATH=src python -m reliability_intelligence demo --json
~~~~

Expected total: **125 tests** (98 previous + 27 V7 diagnostic tests). Compare with GitHub Actions actual output. The diagnose report must say simulated=true, customer_data_used=false and actual_incidents_observed=false. Repeating the call should yield the same category fingerprints.

## 2. Local WSGI negative paths

~~~~bash
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

On the same device, inspect the running pages and use:

~~~~bash
curl -i http://127.0.0.1:8765/api/v9/status
curl -i -X POST http://127.0.0.1:8765/api/v1/demo
curl -I http://127.0.0.1:8765/api/v9/status
curl -i http://127.0.0.1:8765/unknown-page
curl -i http://127.0.0.1:8765/api/v1/status
~~~~

Expected HTTP outcomes: 404, 405, 404 (HEAD with no body), 404, and 200. Failure responses expose X-Diagnostic-Code and X-Diagnostic-ID, but successful responses do not. Error bodies must not reveal internals or customer data. The process logger emits a compact allowlisted JSON line for each failure. The existing WSGI access log is a separate source, not sanitized by diagnostics.py.

## 3. Injected exceptions in tests

Automated negative cases simulate corrupt synthetic input, malformed product charter, a service contract exception, an unexpected runtime exception, and stylesheet read failure. Confirm the API returns 503/500, never a Python traceback; confirm no fake request authorization, customer email, token or filesystem path appears in captured diagnostic JSON. No actual data or third-party system is accessed.

## 4. Release decision

Record exact commit, CI job URL, the schema/event assertions passed, reviewer, date, exceptions and named owner decision. See docs/releases/V7.md. A passing negative-path suite does not satisfy pending business approval or industrial safety controls.
