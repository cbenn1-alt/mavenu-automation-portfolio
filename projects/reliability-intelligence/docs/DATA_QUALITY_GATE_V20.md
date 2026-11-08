# V20 — Data correctness test baseline and sign-off gate

**Architecture:** Mavenu AI SaaS Platform Development Architecture V4, p.42.
**Exact requirement:** Approve data correctness test baseline.
**Required proof:** Data quality sign-off.

This is a reproducible technical evidence review packet for the **synthetic-only** V11–V19 work. It is NOT a human-signed data-quality baseline, customer acceptance, a production release or evidence of V10 formal phase promotion.

## Distinct decisions

| Decision | CI evidence | Human authority |
|---|---|---|
| Technical baseline | Eleven machine evidence reports, full unit regression and source coverage, preserved V10 frozen files | Automated verification can pass |
| Real-world data semantics | Synthetic field/type/limits and reference values only | Unapproved V11/V12 data rights, clocks, field owners and ground truth |
| Formal Phase 02 completion | Unsigned decision packet with eight blockers | BLOCKED_PENDING_HUMAN_SIGNOFF |
| Advancement to V21 | No additional authorization | DO_NOT_PROMOTE; future phase not approved |

## Required data-correctness evidence

V11 approved source/field dictionary (currently draft); V12 schema test report; V13 adverse-value fixtures; V14 repeated ingest comparison; V15 conversion references; V16 reconstructed lineage sample; V17 authored expected-output fixtures; V18 missing/stale/malformed regressions; V19 separate SQL/integer independent computation. Also V8 test/coverage evidence and V10 frozen-source/blocked phase decision.

The machine register at docs/data/DATA_QUALITY_BASELINE_V20.json pins exact evidence paths, expected results and selected checks for all eleven reports. The unsigned template docs/releases/V20_SIGNOFF.json contains null signatory names, approval dates, accepted scope and signatures. It must never be cited as completed approval.

## Human blockers

G20-01 — Signed V2 requirements and V3–V8 human acceptance.
G20-02 — Independent V9 human replay and formal V10 signed phase-promotion decision.
G20-03 — Accountable customer owner and signed V11 source-field dictionary.
G20-04 — Signed V12 customer source schema and allowable field values.
G20-05 — Domain review of V13–V18 synthetic thresholds, timestamps and missing/stale rules.
G20-06 — Real-world adjudicated V17–V19 reference metrics, finance definitions and operating denominators.
G20-07 — Written rights, privacy/security and OT integration review.
G20-08 — Named product and independent reviewer signatures on V20 with scope, risk and evidence identifiers.

Each blocking condition has its expected human role and resolution proof in the JSON register. CI cannot fulfill these items by generating test success or a fake signature.

## Reproduce

After running V8–V19 verifiers in the **same clean checkout**, execute:

    PYTHONPATH=src python scripts/verify_v20.py

The generated evidence/V20 directory contains verification.json, evidence_manifest.json, and data_quality_signoff_packet.json. The manifest includes raw-file and canonical JSON SHA-256 of each of eleven report files; hashes support reproducibility, NOT signed chain-of-custody or customer data-quality attestation.

Minimum historical suite remains 754 tests; V20 adds 65 tests, so **819 are expected** subject to exact GitHub Actions result. Coverage floor remains 84.5%; frozen V10 source remains 18 files.

**Release interpretation:** Technical PASS may coexist with formal sign-off BLOCKED. V21 cannot be described as formally authorized. The V9 runtime 0.9.0 and read-only API v1/schema 1.3.0 are unchanged. No real Minn-Dak data, OEE, MTBF/MTTR, actual downtime, savings, customer rights, OT/CMMS/ERP writes or production readiness is established.
