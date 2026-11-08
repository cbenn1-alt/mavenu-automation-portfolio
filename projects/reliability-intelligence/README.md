# Mavenu Reliability Intelligence — V16 (exploratory source and transform lineage)

**State:** V16 reconstructs source-file/record and V15 transformation lineage for fabricated data. **No actual customer ingest event was observed.** V10 formal phase promotion remains BLOCKED/PENDING human sign-off and V11/V12 source approvals remain unsigned. No production or plant integration is authorized.

**Standard (Architecture V4, page 42):** V16 = Capture ingestion origin and transform lineage. Proof = Record-level trace sample. The V9 runtime remains frozen at 0.9.0; API v1/schema 1.3.0.

## Clean checkout verification (Python 3.11+)

The product remains Python standard-library only. V8 adds one pinned *development-only* coverage tool.

~~~~bash
cd projects/reliability-intelligence
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
PYTHONPATH=src python scripts/replay_v9.py
PYTHONPATH=src python scripts/verify_v10.py
PYTHONPATH=src python scripts/verify_v11.py
PYTHONPATH=src python scripts/verify_v12.py
PYTHONPATH=src python scripts/verify_v13.py
PYTHONPATH=src python scripts/verify_v14.py
PYTHONPATH=src python scripts/verify_v15.py
PYTHONPATH=src python scripts/verify_v16.py
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

V11 has **210** inherited tests. V12 adds **34** regression tests (expected full suite **244**), with the same 84.5% coverage floor. GitHub Actions uploads V8–V12 evidence for 30 days. Verify actual hosted output before claiming success.

**V14 next:** Continue data correctness with explicit provenance, time semantics and review evidence according to the controlled development standard. No customer/plant data is authorized.


## V12 strict source schema and test report

The JSON contract at docs/data/SCHEMA_CONTRACT_V12.json mirrors V11's four fabricated datasets and 21 fields, requiring exact field presence, types, enumerations, SYN-only identifier shapes and evidence-reference formats. scripts/verify_v12.py checks every row and produces 16 non-destructive negative-case failures in evidence/V12/schema_validation_report.json. The 34 new tests are in tests/test_schema_v12.py. Reviewer instructions and security scope are in docs/data/SCHEMA_CONTRACT_V12.md, docs/DEMO_V12.md and docs/releases/V12.md.

The required artifact is a **schema validation test report**. It does not approve the V11 source dictionary, supersede the blocked V10 decision, or authorize real customer records, integrations, industrial control writes, predictive claims or measured ROI.


## V13 controlled negative cases

- fixtures/negative_cases_v13.json: **29 invalid fictional mutations** (null 8, out of range 5, nonfinite 3, impossible/referential 13) and **seven valid edge controls**.
- scripts/verify_v13.py: checks the unchanged V10 18-file snapshot and V11/V12 contracts, then executes each adverse or boundary control in memory and writes evidence/V13/negative_case_report.json.
- tests/test_negative_cases_v13.py: **56 additional tests**, one for each of 29 rejection scenarios and seven permitted edge values, plus corpus integrity and governance checks.
- docs/NEGATIVE_CASES_V13.md, docs/DEMO_V13.md, docs/releases/V13.md: reviewer protocol and six-part evidence packet.

Expected full regression suite: **300** tests (244 historical + 56 V13), subject to the actual hosted CI results. The 84.5% V8 combined coverage floor and historical module checks remain enforced. The product itself gains no customer API, industrial connector, real data source, maintenance decision or financial benefit. The V10 recommendation remains BLOCKED, not overwritten by a green CI run.


## V14 atomic in-memory replay comparisons

V14's exact identity and duplicate policy is in docs/data/IDEMPOTENCY_CONTRACT_V14.json, with a 16-case replay plan at fixtures/repeated_ingest_v14.json. The new scripts/ingest_v14.py module implements temporary, read-only-to-the-outside, all-or-none synthetic batch loading. scripts/verify_v14.py compares canonical state checksums for identical, reordered, partial, partitioned and duplicate-bearing replay sequences; verifies conflicts do not partially commit; and generates evidence/V14/repeated_ingest_comparison.json.

tests/test_idempotency_v14.py adds **48 tests** to the historical 300, for **348 expected**; the actual CI output controls. The V8 84.5% source coverage floor and V9–V13 checks remain enforced. CI publishes the V8–V14 reports. No real customer identity, production idempotency key, persistent store, distributed exactly-once guarantee, credential, customer interface or operational write endpoint is present.

Reviewer sources: docs/IDEMPOTENCY_V14.md, docs/DEMO_V14.md, docs/releases/V14.md. Passing tests are **engineering evidence only**, not owner sign-off or permission to cross the blocked V10 promotion gate.


## V15 canonical conversions

- fixtures/conversion_reference_v15.json: 27 accepted and 24 rejected synthetic references across UTC timestamp, hours/minutes/seconds and USD locale formatting.
- scripts/normalize_v15.py: standard-library Decimal and timezone-offset conversion; no timezone guesses, silent rounding or FX conversions.
- scripts/verify_v15.py: checks all references, canonical replay, 12 unchanged source cases, outputs evidence/V15/conversion_reference_report.json.
- tests/test_conversion_v15.py: 81 added tests (51 per-reference and 30 controls), expected total 429 (verify CI).
- docs/NORMALIZATION_V15.md, docs/DEMO_V15.md and docs/releases/V15.md: review and release packet.

The 84.5% combined coverage floor and prior V8-V14 controls remain in force. Green CI does not authorize customer financial data, industrial systems, or formally approved Phase 02.


## V16 reconstructed origin and transformation lineage

V16 adds docs/data/LINEAGE_CONTRACT_V16.json, scripts/lineage_v16.py and scripts/verify_v16.py, plus tests/test_lineage_v16.py. The verifier reports all 34 synthetic record origins, 36 V15 conversion steps, and a five-record sample with six transformation steps. Record origins are deterministic *reconstructions from committed fictional files*, NOT observations of a customer ingestion event. It writes evidence/V16/lineage_verification.json, evidence/V16/record_level_trace_sample.json and evidence/V16/synthetic_record_lineage.json.

V16 adds 115 tests to the inherited 429, yielding **544 expected** tests (verify actual hosted CI). Docs/LINEAGE_V16.md, docs/DEMO_V16.md and docs/releases/V16.md describe source hashing, replay, limitations and human review. The V9 application runtime remains unchanged, and formal V10 approval and V11/V12 sign-offs are still outstanding.
