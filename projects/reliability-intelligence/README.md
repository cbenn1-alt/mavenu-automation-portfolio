# Mavenu Reliability Intelligence — V11 (exploratory synthetic data correctness)

**State:** V11 introduces a drafted, machine-checked 21-field dictionary for fabricated data. **Formal Phase 02 promotion is still BLOCKED/PENDING human decision** at V10; the required V11 approved source/field dictionary does not yet have actual owner signatures. No customer/plant authorization or production capability is implied.

**Standard (Architecture V4, page 42):** V11 = Declare data types, meaning, and ownership. Proof = Approved source/field dictionary. V11 implements a candidate technical dictionary only; sign-off remains outstanding. The frozen V9 runtime remains 0.9.0 with API contract v1/schema 1.3.0.

## Clean checkout verification (Python 3.11+)

The product remains Python standard-library only. V8 adds one pinned *development-only* coverage tool.

~~~~bash
cd projects/reliability-intelligence
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
PYTHONPATH=src python scripts/replay_v9.py
PYTHONPATH=src python scripts/verify_v10.py
PYTHONPATH=src python scripts/verify_v11.py
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


## V10 frozen source and decision gate

The V10 codebase deliberately keeps the **V9 application runtime unchanged**. The governed V10 increment is the evidence set and decision control, not new API/industrial functionality.

- docs/releases/V10_BASELINE.json: 18 checked-in Git blob IDs pinning V9 Python source, CSS, synthetic fixtures, charter, test dependency, V9 demo and V8 coverage baseline.
- docs/RISK_REGISTER_V10.json: 11 OPEN risks (two critical), proposed but unassigned owner roles and null remediation dates.
- docs/releases/V10_DECISION.json: DRAFT_UNAPPROVED decision, promotion recommendation BLOCKED, formal decision PENDING_HUMAN_SIGNOFF, no invented approver.
- scripts/verify_v10.py: integrity and governance invariant checker; writes evidence/V10/verification.json on successful local inspection.
- tests/test_decision_v10.py: 23 negative and baseline integrity checks.
- docs/DECISION_V10.md, docs/RISK_REGISTER_V10.md, docs/DEMO_V10.md and docs/releases/V10.md: rationale, review procedure, technical limits and six-part evidence packet.

GitHub Actions executes the inherited V8 regression, V9 local-socket replay and V10 decision integrity check from an isolated clean source snapshot. The V8 84.5% combined coverage floor stays enforced. The V10 suite is expected to contain 176 tests, subject to actual CI verification.

### Result interpretation

**Technical source freeze:** machine-verifiable after CI. **Human approval:** not established. Earlier V2 requirements approval, V3–V8 releases and V9 independent reviewer acceptance remain open. The separately held V1 Git history has not been imported. Formal V10-to-V11 phase promotion remains blocked, while **exploratory synthetic-only V11 data correctness work** can be drafted as explicitly non-promoted R&D.

No customer/Minn-Dak data, real maintenance orders, OT/PLC/SCADA controls, models, measured ROI, tenant security or production pilot is available or authorized.


## V11 synthetic source and field dictionary

- docs/data/SOURCE_FIELD_DICTIONARY_V11.json — exactly four fixture datasets, 21 fields, documented logical types, meaning, units, nullability, keys, enums, synthetic provenance and proposed owner roles.
- docs/data/SOURCE_FIELD_DICTIONARY_V11.md — readable schema/ownership tables and the specific external business/data/maintenance/financial approval requirements.
- scripts/verify_v11.py — checks the 18-file V10 source freeze and blocked phase decision, then validates exact fields, types, numeric bounds, canonical UTC, uniqueness, foreign keys and non-disclosure of customer data.
- tests/test_dictionary_v11.py — 34 negative/governance regression tests using in-memory copies only.
- docs/DEMO_V11.md, docs/releases/V11.md and docs/CHANGELOG_V11.md — reviewer replay and evidence packet.

No client data, genuine system of record, employee ID, authenticated reviewer, equipment diagnosis, financial benefit or industrial control connection exists in this prototype. Data roles are proposed but not assigned. The V10 blocked promotion decision is carried forward unchanged; exploratory V11 work is not a formally accepted Phase 02 release.

Expected test count: **210** (176 from V10 plus 34 V11); verify exact GitHub Actions output and existing 84.5% combined coverage floor. The CI workflow uploads V8–V11 evidence for 30 days.

**V12 next:** Identify source priorities, quality concerns and authoritative ownership with a human-reviewed source inventory; until authorized, use hypothetical/synthetic-only references and do not infer customer system access.
