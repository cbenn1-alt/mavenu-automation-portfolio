# V19 — Independent reconciliation of synthetic aggregates

**Mavenu AI SaaS Platform Development Architecture V4, page 42.**
**V19 objective:** Reconcile aggregates and operational metrics.
**Required proof:** Independent computation results.

**Status:** Reproducible technical candidate with **synthetic data only**. V10 formal promotion is BLOCKED/PENDING human sign-off; V11 source-field approval, V12 schema approval and V17 reference-domain adjudication remain unsigned.

## What is independently computed?

V17 derived 25 authored regression expectations using Python Decimal and V16 normalized synthetic cases. V19 deliberately uses a **second implementation path**: it reads the original fictional JSON rows, converts durations to *integer seconds* and USD to *integer cents* without rounding, inserts these into an **in-memory SQLite database**, and calculates aggregates using SQL queries.

The independent method computes:
- **Seven** summary values: case count, asset count, total fictional downtime, total fictional repair cost, median example case duration, count lacking invented evidence-reference identifiers, and later occurrences of an already-seen fictional asset.
- **Six** per-asset aggregates: case counts, sum downtime, sum cost and missing-example-evidence counts.
- **Twelve** case-history entries: synthetic ID, associated fictional asset, count of prior asset events in the sample, occurrence index, and presence of an example evidence-reference ID.

All **25 comparison units** must exactly match the separately authored V17 expected-output fixture. SQL group totals must also reconcile to their grand totals, independently of the reference fixture. Reordering raw inputs must produce identical results.

## Example synthetic reference figures

| Metric | Expected |
|---|---:|
| Cases / assets | 12 / 6 |
| Fictional downtime sum | 45.5 hours |
| Invented repair-cost total | USD 12,735.00 |
| Median fabricated case downtime | 3 hours |
| Cases without a synthetic evidence-reference ID | 1 |
| Later synthetic events for an already-seen asset | 6 |

These are **not observed Minn-Dak plant downtime or expenses** and imply no reliability prediction, avoidable expenditure, savings or business ROI. A synthetic reference is *not* customer ground truth even when two code paths agree.

## Deliberate discrepancies and fail-closed outcomes

The fixture at fixtures/reconciliation_v19.json pins **16 negative comparisons**. Nine test wrong but potentially parseable calculations or changed reference expectations, including a cost change offset elsewhere so the grand total remains unchanged while per-asset sums diverge. Seven test malformed or unsupported records, including missing/duplicate case IDs, unknown assets, fractional cents or seconds, false customer provenance and undeclared personnel columns.

Every negative case must fail with its exact fixed error class. No mismatch may be silently tolerated or overwritten to make the expected and computed results agree. The source fixtures remain unchanged.

## Coverage and security boundaries

- scripts/reconcile_v19.py: independent SQLite/integer seconds and cents calculation and exact comparison.
- scripts/verify_v19.py: rechecks historical V10 frozen source and V17/V18 synthetic correctness, verifies all 25 computations and 16 adversarial comparisons, writes the two ignored evidence files.
- tests/test_reconciliation_v19.py: **77 additional unit tests**, bringing the expected complete regression suite to **754** (677 earlier + 77 V19); actual CI result controls.
- evidence/V19/independent_reconciliation_report.json: summary, reproducibility fingerprints, source approval limitations.
- evidence/V19/independent_computation_results.json: full calculated synthetic values, per-case adverse test statuses.

The source/fixture and expected-output files are *read-only*. SQLite is strictly memory-backed (no file database, external network or customer connector). Existing V9 application runtime 0.9.0 and read-only API v1/schema 1.3.0 remain unchanged.

## No invented operational metrics

The fabricated data has **no true operating-hours denominator, authorized failure definition, maintenance labor hours, dispatch and restoration times, revenue attribution or actual GL expense**, so V19 intentionally does **not** calculate availability percentage, MTBF, MTTR, OEE, predicted failure probabilities, saved cost or ROI. Counts of synthetic cases are valid arithmetic but are not substitute denominators for operating-hour KPIs.

An independent *algorithm* is not independent customer/source validation. Domain, data, finance and OT owners must approve real measurement and reconciliation definitions; named independent reviewer approval remains unrecorded. V10 promotion remains blocked and V11/V12 source approvals are unsigned.
