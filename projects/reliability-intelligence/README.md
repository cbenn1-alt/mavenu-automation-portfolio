# Mavenu Reliability Intelligence — V6

**State:** a reproducible, read-only, *synthetic-only* maintenance-review workflow replay. No customer, Minn-Dak, real operator, production, or predictive-maintenance readiness is claimed.

**Standard:** Mavenu AI SaaS Platform Development Architecture V4, p.42. V6 objective = implement end-to-end business workflow; proof = reproducible demo trace.

The separate V1 Git history is not imported. V2–V5 human acceptance and G1/V30, G2/V60 remain pending.

## Local use

Python 3.11+; no third-party runtime dependencies. From the repository root:

~~~~bash
cd projects/reliability-intelligence
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m reliability_intelligence demo --json
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

Open http://127.0.0.1:8765/ on the same device. The local server binds only 127.0.0.1 and must not be publicly hosted.

## Synthetic workflow

1. Load the 12 verified V5 fabricated case records (six fictional assets).
2. Check existence of made-up evidence-reference IDs (not actual evidence documents).
3. Apply transparent, chronological rules: absent reference ID; same asset/failure event within preceding 30 elapsed days. A flag is not an equipment diagnosis or maintenance priority.
4. Apply four fabricated reviewer-role dispositions from pinned demo_review_script.json; eight cases remain without dispositions. No real person approves or reviews anything.
5. Emit a deterministic in-memory trace, ordered events and SHA-256 checksum. No file write, database transaction, control command or external work order.

The trace hash demonstrates deterministic reproducibility for fixed code and inputs, not cryptographic signing or an immutable audit history. Reference labels in reference_labels.json are kept separate from workflow code and never exposed through HTTP; this is not a true blinded evaluation.

## UI and API

Local UI paths: /, /workbench, **/workflow**, /evaluation, /governance.

Read-only GET/HEAD endpoints:
- /api/v1/status — software readiness only, not machine health
- /api/v1/scope — unapproved buyer/problem/outcome hypothesis
- /api/v1/cases — 12 fabricated maintenance records
- **/api/v1/demo** — ordered synthetic intake/evidence/rules/scripted disposition/export trace
- /api/v1/contract — API version and required fields

Schema version 1.2.0. Unknown versions reject with 404; mutating methods reject with 405; invalid pinned inputs fail closed with sanitized 503. No customer/industrial interface exists.

## Verification and evidence

- src/reliability_intelligence/workflow.py — deterministic, side-effect-free replay and trace checksum
- fixtures/demo_review_script.json + updated manifest — pinned, invented dispositions; no real user actions
- tests/test_workflow.py — 27 V6 tests, including temporal rules, deterministic trace, invalid scripts, API/CLI/UI behavior
- docs/WORKFLOW_V6.md — functional contract and non-goals
- docs/DEMO_V6.md — reviewer reproduction
- docs/releases/V6.md — six-part release packet

Expected suite: 98 tests (71 earlier plus 27 new). Verify actual GitHub Actions results before asserting passage.

No real maintenance records, payroll data, Dynamics 365/Levridge/Power BI/CMMS/ERP/historian, PLC/SCADA/OT, trained AI, real human sign-off, write-back, downtime measurement, value attribution, ROI or customer authorization.

**V7 next:** structured failure and diagnostic logging, subject to review and release controls.
