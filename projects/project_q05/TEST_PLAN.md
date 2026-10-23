# Q05 — Test Plan

Run with `.venv/bin/python -m pytest tests/test_reconciliation.py tests/test_reconciliation_api.py -q`
from the repo root. All fixtures are synthetic.

## 1. Hand-built fixture (the core)

`tests/test_reconciliation.py` defines `INVOICES_CSV` (8 invoices) and
`PAYMENTS_CSV` (11 rows, one within-batch duplicate) with **hand-computed
expectations** (`EXPECTED`):

| Expected | Value |
|---|---|
| Exact matches | 6 (PAY-0001,02,03,05,08 → their invoices; PAY-0010 → INV-0006) |
| Fuzzy matches | 1 (PAY-0004 → INV-0005, score 0.90) |
| Review-routed | 1 (PAY-0006, best 0.60 < 0.75) |
| Unmatched payments | PAY-0007, PAY-0009 |
| Invoiced / paid | 7925.50 / 7287.84 (duplicate row excluded) |
| Outstanding / overpaid | 3000.00 / 1200.00 |
| Identity check | 3000.00 − 1200.00 == 7925.50 − 6125.50 (== 1800.00) |
| Open exceptions | 9 (2 partial, 1 overpaid, 2 unmatched invoices, 2 unmatched payments, 1 review, 1 duplicate) |
| Aging @ 2026-10-23 | current 600.00, 1–30: 1500.00, 31–60: 600.00, 61–90: 0, 90+: 300.00 |

## 2. Test matrix

| Area | Tests |
|---|---|
| Ingest: happy path, row-level errors (bad amount/date, missing customer, due<issued), fatal header validation, idempotent re-ingest | 7 |
| CSV injection: formula cells neutralized (`=`,`+`,`-`,`@`), sanitized count, formula amounts rejected, note sanitization | 4 |
| Decimal: `0.29`→29c (float would give 28.99…), `cents_to_decimal` type, invalid amounts rejected, summary values are Decimal | 4 |
| Exact-pass precision: deceptive fixture (INV-01 vs INV-1, nonexistent ref, case/whitespace normalization) | 2 |
| Fuzzy: component breakdown, threshold boundary (`decide` at 0.75/0.74), below-threshold → review with zero silent auto-matches, 5-candidate bulk review test | 4 |
| End-to-end fixture: match counts, known pairs + explanations, exception queue contents, partial balance, overpaid exception | 5 |
| Summary: hand-computed expectations, **independent raw-SQL recomputation**, reconciliation identity | 3 |
| Idempotency: re-ingest + re-match → zero new matches, identical open queue | 1 |
| Duplicates: within-batch duplicate → exception + single row; coverage uses one payment only | 2 |
| State machine: legal paths, parametrized illegal moves (8 cases), unknown ID, workflow API | 4 |
| Aging: hand-computed buckets @ frozen clock, buckets sum to outstanding, exception aging (fresh + 83-day-old) | 3 |
| Migration rollback: apply → use → roll back → verify tables gone + other tables intact → re-apply | 1 |
| API: upload, invalid kind, row errors, run-match stats, exception list/filter, transition flow, illegal transition, unknown ID, aging endpoint, pages, form upload, hub/nav | 11 |

## 3. Adversarial coverage

- Formula-injection CSVs (command pipe, HYPERLINK) neutralized; formula
  amounts rejected as row errors (never reach the ledger).
- Deceptive invoice IDs (prefix collisions, nonexistent refs) never
  match in the exact pass.
- Duplicate payment IDs within and across batches (double-count
  protection).
- Illegal state transitions (parametrized matrix) — the machine holds.

## 4. What is not tested (documented gaps)

- Concurrent ingest (single-writer demo; SQLite serializes).
- Non-USD/multi-currency amounts.
- Real-world OCR'd invoices (input is structured CSV by design).
- Performance beyond fixture scale (p95 ingest timing is measured for
  Q01; Q05 ingest is the same `csv`+SQLite path).
