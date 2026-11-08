# Mavenu Reliability Intelligence — V5

**State:** Synthetic-only sample maintenance records in a local-only read-only UI and versioned API. No customer data, client engagement, predictions, production authorization or measured operational effects.

## Increment register (Mavenu Development Architecture V4, p.42)

| Version | Objective | Evidence | Human approval |
|---|---|---|---|
| V1 | Repository/CI/environment | Separate local package | Git history not imported |
| V2 | User, pain point and outcome | Candidate problem charter | Pending |
| V3 | Minimal user interface/navigation | Four-page shell and smoke tests | Pending |
| V4 | Versioned API/service boundary | API v1 contract tests | Pending |
| **V5** | **Representative synthetic fixtures** | **Provenance manifest, 12 fabricated cases, checksums, negative-case tests** | **Pending** |
| V6 | End-to-end workflow | Not implemented | Pending |

G1/V30 and G2/V60 are not passed.

## Start (Python 3.11+, standard library only)

~~~~bash
cd projects/reliability-intelligence
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

Browse http://127.0.0.1:8765/ on the same machine. The server binds ONLY to 127.0.0.1 and must not be exposed to the internet.

UI: / (Overview), /workbench (12 fabricated maintenance records), /evaluation (unmeasured design), /governance (safety restrictions).

API: /api/v1/status, /api/v1/scope, /api/v1/cases, /api/v1/contract. GET and HEAD only. Additive schema version **1.1.0**; no new write routes.

~~~~bash
curl -i http://127.0.0.1:8765/api/v1/cases
curl -i http://127.0.0.1:8765/api/v1/contract
~~~~

## Provenance and testing

- fixtures/cases.json — six invented assets and twelve fabricated work-order-like events.
- fixtures/reference_labels.json — seeded **illustrative** annotation for internal tests only; never sent in UI or API.
- fixtures/manifest.json — authorship, date, methods, counts, synthetic-only declarations and Git blob SHA-1 content identifiers.
- fixtures/README.md — detailed provenance/fields/limits; fixtures.py — integrity and schema validation.
- tests/test_fixtures.py — 23 new tests for integrity, references, negative cases, and non-disclosure.

Expected aggregate tests: **71** = 12 (V2) + 19 (V3) + 17 (V4) + 23 (V5). Confirm actual CI result before claiming verification.

Git blob SHA-1 identifiers are Git object checksums, not signed attestations. Fixtures are hand authored, are **not statistically representative**, have not undergone independent domain review, and support no savings or reliability inference.

**No live data, personal information, Dynamics 365, Levridge, CMMS/ERP, PLC/SCADA or OT connections; no model, work-order writes, autonomous ranking or production readiness.**

See docs/DEMO_V5.md, docs/releases/V5.md and docs/API_CONTRACT_V1.md. V6 next: end-to-end synthetic review trace, not a production integration.
