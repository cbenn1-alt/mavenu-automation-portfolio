# V18 — Missing, stale and malformed input regression

**Source:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**V18 objective:** Test missing, stale and malformed inputs.
**Required proof:** Adverse-case regression suite.

**Status:** Synthetic-only technical regression candidate. The V10 Phase 02 promotion recommendation remains BLOCKED and the formal decision PENDING_HUMAN_SIGNOFF; V11/V12 customer-source definitions are unsigned. No live customer ingestion, actual data freshness SLA, finance-domain acceptance or industrial control authorization exists.

## Adverse-case matrix

| Rejection class | Cases | Meaning |
|---|---:|---|
| Missing | 16 | Missing case fields, source files or collections, required script and label values |
| Stale | 7 | Old or far-future UTC event timestamps, using a deliberately fixed reference clock |
| Malformed | 21 | Invalid/naive timestamps, nulls, nonfinite values, wrong types, unapproved source identity, unknown fields, invalid UTF-8, JSON syntax and duplicate JSON keys |
| **Total** | **44** | Fixed, non-sensitive error codes; no source mutation |

The corpus is fixtures/adverse_inputs_v18.json. All mutations use deep copies of fabricated V5/V6 sources. Malformed raw-byte examples include invalid UTF-8, duplicate JSON members, trailing comma and nonstandard JSON NaN. No external data is read.

## Synthetic freshness policy

Reference timestamp: **2026-02-05 00:00:00 UTC**. Records earlier than **2025-12-22 00:00:00 UTC** (45 days) or later than **2026-02-06 00:00:00 UTC** (24 hours) are rejected; boundaries are inclusive. Five valid controls include source baseline, both boundaries, one second inside the older boundary and exact reference-clock time. The validator does not read current wall time.

These are **illustrative test values, not a Minn-Dak/plant freshness SLA**. This code does not authenticate device clocks, infer local time zones, quarantine production records, dispatch work orders or initiate real operational alerts.

## Implementation

- scripts/adverse_v18.py: strict JSON/UTF-8 input parsing, duplicate-key and NaN rejection, field presence and type policy, deterministic fixed-clock checking, deep-copy scenario execution.
- scripts/verify_v18.py: proves unchanged V10 source snapshot, verifies inherited V11–V13 constraints and executes every V18 adverse case, writing evidence/V18/adverse_regression_report.json.
- tests/test_adverse_v18.py: **74 regression tests**: 44 per-adverse case, five per-accepted control and 25 inventory/negative/security/immutability tests. Expected full suite **677**, subject to actual GitHub Actions verification.
- Original V9 runtime and read-only API stay frozen. V15–V17 normalization, lineage and golden arithmetic remain test-only utilities.

A passing report is evidence of these particular synthetic rejection behaviors, **not customer data-quality sign-off**. A named customer data owner must separately define source systems, missing-field rules, permitted ages by source, timezone/clock assumptions, quarantine/retry procedures, retention and security/OT boundaries. Formal V10 phase promotion and V11/V12 approvals remain outstanding.
