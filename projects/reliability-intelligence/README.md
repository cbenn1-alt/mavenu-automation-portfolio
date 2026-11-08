# Mavenu Reliability Intelligence — V8

**State:** Local, synthetic-only prototype with a reproducible unit/smoke regression and baseline source coverage. Not a customer-authorized industrial application or a validated reliability prediction.

**Standard (Architecture V4, page 42):** V8 = Create initial unit and smoke regression. Proof = CI result and baseline coverage.

## Clean checkout verification (Python 3.11+)

The product remains Python standard-library only. V8 adds one pinned *development-only* coverage tool.

~~~~bash
cd projects/reliability-intelligence
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
~~~~

The runner checks test inventory, executes the full unit/smoke suite with branch-aware coverage.py, writes evidence/V8/coverage.json and evidence/V8/verification.json, and enforces a checked-in coverage floor once established. GitHub Actions uploads these files as an artifact retained for 30 days.

Expected inventory: **140 tests**, comprising 125 V2–V7 regressions and 15 new V8 cross-layer smoke tests, subject to actual CI verification. Coverage is a software execution metric, not an industrial safety or business value measure.

## Application smoke

~~~~bash
PYTHONPATH=src python -m reliability_intelligence status --json
PYTHONPATH=src python -m reliability_intelligence demo --json
PYTHONPATH=src python -m reliability_intelligence diagnose --json
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

On the same machine, open http://127.0.0.1:8765/. The server binds to 127.0.0.1 only; do not publicly host it.

Five read-only UI routes: /, /workbench, /workflow, /evaluation, /governance.
Five GET/HEAD API routes: /api/v1/status, /api/v1/scope, /api/v1/cases, /api/v1/demo, /api/v1/contract.
V8 changes no API contract fields, so schema remains **1.3.0**. It adds no external integrations or writes.

## Evidence and controls

- tests/test_regression_v8.py — end-to-end synthetic smoke, API/UI navigation, invalid method/versions, replay repeatability, safe error handling, explicit nonproduction flags.
- scripts/verify_v8.py — coverage runner, test inventory evidence and baseline regression gate.
- .coveragerc and requirements-dev.txt — source scope, branch measurement and pinned coverage tool.
- docs/BASELINE_V8.md — baseline methodology, approval conditions and gaps.
- docs/DEMO_V8.md — reviewer reproduction and independent evidence review.
- docs/releases/V8.md — six-part release packet.

All case data and reviewer roles are invented. No real Minn-Dak data, industrial measurements, plant writes, training, operators, predictions or savings are implied.

**V9 next:** clean setup and independent reviewer replay documentation. Separate original V1 history and human acceptance of V2–V7 remain unresolved. G1/V30 and G2/V60 not passed.
