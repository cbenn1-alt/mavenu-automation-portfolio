# Mavenu Reliability Intelligence — V9

**State:** Local synthetic-only prototype with setup, demo and exclusions documented for a clean-checkout independent reviewer. Automated local-socket replay is implemented, but independent HUMAN acceptance has not occurred. No production or customer authorization is implied.

**Standard (Architecture V4, page 42):** V9 = Document setup, demo steps and exclusions. Proof = Independent reviewer replay. V8 source-coverage regression remains enforced.

## Clean checkout verification (Python 3.11+)

The product remains Python standard-library only. V8 adds one pinned *development-only* coverage tool.

~~~~bash
cd projects/reliability-intelligence
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
PYTHONPATH=src python scripts/replay_v9.py
~~~~

The runner checks test inventory, executes the full unit/smoke suite with branch-aware coverage.py, writes evidence/V8/coverage.json and evidence/V8/verification.json, and enforces the checked-in 84.5% combined coverage floor and 140-test minimum. GitHub Actions uploads these files as an artifact retained for 30 days.

V8's measured initial baseline: **140/140 passing tests**, **84.951% combined statement/branch coverage**, **9 production source modules**. V9 adds **13 new reviewer/replay tests**, bringing the expected count to at least **153**. The observed V9 count and coverage are established by its hosted CI. First successful GitHub Actions run: 42486809082, source commit c75254e. The reviewable policy floor is **84.5%**, with at least 140 tests and per-module minima. This is software execution evidence, not an industrial safety or business value measure.

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


## V9 reviewer replay and source limitations

- docs/SETUP_V9.md — fresh source checkout, test-only dependencies and local launch.
- docs/DEMO_V9.md — concise synthetic-only replay commands and expected behavior.
- docs/REVIEWER_REPLAY_V9.md — independent HUMAN review protocol, keyboard/browser checks and required evidence.
- docs/EXCLUSIONS_V9.md — customer, industrial control, integration, safety, business, data and production exclusions.
- docs/V9_REVIEWER_RECORD_TEMPLATE.json — intentionally unsigned private-review template with no invented approver.
- scripts/replay_v9.py — a new, standard-library automated local-socket check with 12 high-level checkpoints; produces evidence/V9/replay.json.
- tests/test_reviewer_v9.py — 13 additional V9 harness/document checks.

GitHub Actions runs the regression suite and the new socket replay from a clean Git-archived source snapshot and uploads temporary evidence. This is a technical demonstration, NOT the required independent human reviewer sign-off. A reviewer must personally execute the documented instructions, inspect the actual pages and record the result before V9 formal acceptance.

Earlier V2–V8 owner approvals, original V1 Git history consolidation and customer/industrial permissions remain outstanding. V10 baseline decision is the next scheduled increment once prerequisites are reviewed. No real personnel/customer records, financial results, system writes, OT access or actual AI predictive model are involved.
