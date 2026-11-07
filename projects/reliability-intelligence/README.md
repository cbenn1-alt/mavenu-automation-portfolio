# Mavenu Reliability Intelligence — V4

**Engineering state:** Read-only, synthetic-only versioned API and local UI implemented. The user/problem charter is not approved. No Minn-Dak authorization, operational data, AI model or production deployment is claimed.

## Increment register (Development Architecture V4, page 42)

| Increment | Requirement | Evidence | Approval |
|---|---|---|---|
| V1 | Repository, CI and environment | Original separate local package | V1 history not yet imported to GitHub |
| V2 | User, problem, measurable outcome | Candidate charter and tests | Business sign-off pending |
| V3 | Minimal UI and navigation | Four-page local shell, smoke tests | Human sign-off pending |
| **V4** | **Versioned API/service boundaries** | **Contract smoke suite and GitHub CI** | Human sign-off pending |
| V5 | Synthetic fixtures | Future work | Not started |
| V6 | End-to-end workflow | Future work | Not started |

Readiness gates G1/V30 and G2/V60 have not been passed.

## Start locally (Python 3.11+, zero runtime dependencies)

~~~~bash
cd projects/reliability-intelligence
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

Open http://127.0.0.1:8765/ on the same computer. The server only binds to 127.0.0.1. Do not host publicly.

V3 UI pages: Overview (/), Case workspace (/workbench), Evaluation (/evaluation), Boundaries (/governance).

V4 API endpoints (GET and HEAD only):

| Path | Contract |
|---|---|
| /api/v1/status | Non-production capabilities and pending authorization |
| /api/v1/scope | Candidate problem, buyer/user hypotheses and unmeasured KPI |
| /api/v1/cases | Unpopulated collection; no synthetic fixtures until V5 |
| /api/v1/contract | Machine-readable API version, methods and required fields |

All successful API responses contain api_version, schema_version, resource, data. Unknown versions return 404. POST, PUT, PATCH and DELETE return 405. No write endpoints exist.

## Review and test

~~~~bash
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m reliability_intelligence status --json
PYTHONPATH=src python -m unittest discover -s tests -v
curl -i http://127.0.0.1:8765/api/v1/status
curl -i http://127.0.0.1:8765/api/v1/contract
~~~~

Read docs/API_CONTRACT_V1.md, docs/DEMO_V4.md and docs/releases/V4.md. Green tests prove only bounded, deterministic API contracts and UI smoke checks—not physical equipment reliability, cybersecurity certification, operational savings or predictive accuracy.

## Non-negotiable boundaries

- Local read-only metadata and no customer records, external connections, databases or production credentials.
- No Dynamics 365, Levridge, CMMS, ERP, Power BI, historian, PLC/SCADA or other OT integrations.
- No work-order mutation, equipment control, autonomous maintenance ranking, model, actual fault data, savings or ROI assertion.
- Existing-vendor configure/buy/no-build path must remain available.
- The original local V1 Git repository has not been imported; GitHub implements the separate V2–V4 development chain.

**Next:** V5 representative synthetic fixtures, separately labeled and provenance documented. No live data without written authorization and later gating.
