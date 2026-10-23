# Q05 — Requirements

**Status: Implemented** (all requirements below are built and tested).

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| R1 | Ingest an invoice CSV (`invoice_id,customer,amount,issued_date,due_date`) and a payment CSV (`payment_id,invoice_ref,customer,amount,paid_date,note`) | Implemented, Tested |
| R2 | Schema validation with **row-level error reporting**: a bad row is recorded with its 1-based row number and reason; it never aborts the batch | Implemented, Tested |
| R3 | Sanitize CSV-formula cells on ingest (cells starting `=`, `+`, `-`, `@` neutralized with a leading `'`) and document the control | Implemented, Tested |
| R4 | Idempotent ingest: re-ingesting the same CSV inserts zero new rows (natural keys `invoice_id` / `payment_id`) | Implemented, Tested |
| R5 | Exact matching pass: match on invoice ID (normalized), with **every match explained** | Implemented, Tested |
| R6 | Fuzzy fallback pass: score candidates by amount (± tolerance), date window, and ID overlap; auto-match only at/above a documented threshold; **every match explained** | Implemented, Tested |
| R7 | Below-threshold candidates are **never silently auto-matched**: they route to human review with candidate score breakdowns | Implemented, Tested |
| R8 | Exception queue with kinds `unmatched_invoice`, `unmatched_payment`, `partial_payment`, `overpaid_invoice`, `duplicate_payment`, `review_candidate` — **each with a suggested next action** | Implemented, Tested |
| R9 | Exception lifecycle `open → investigating → resolved \| written_off`, enforced in code; illegal transitions rejected; actor-stamped history | Implemented, Tested |
| R10 | Partial-payment handling: invoice coverage computed as sum of matched payments; balances and overpayments reported as exceptions | Implemented, Tested |
| R11 | Duplicate-payment protection: within-batch repeats raise a visible exception and are not double-counted; re-ingest produces zero duplicate matches | Implemented, Tested |
| R12 | Aging report (current / 1–30 / 31–60 / 61–90 / 90+ days) whose bucket totals sum to the outstanding total | Implemented, Tested |
| R13 | Reconciliation summary where **every total reconciles to source rows**; identity `outstanding − overpaid == invoiced − matched-paid` verified | Implemented, Tested |
| R14 | Exception aging by age since creation | Implemented, Tested |
| R15 | Money math in Decimal only; float is never used for amounts | Implemented, Tested |
| R16 | No real financial data anywhere: all fixtures, demos, and amounts are synthetic | Implemented, Tested |
| R17 | Web UI + JSON API for ingest, match, exception queue, transitions, reports | Implemented, Tested |

## Non-functional requirements

- **Zero cost / stdlib only** at runtime (`csv`, `sqlite3`, `decimal`, `wsgiref`, `json`, `re`, `datetime`); no network calls; no paid services.
- **Determinism**: the same CSVs + clock produce the same matches and exceptions (frozen-clock tests).
- **Auditability**: every match explanation, every exception transition, and every run is a database row (queryable) plus a structured JSON log line.
- **Rollback**: migration `008_reconciliation.sql` ships with a tested down-step.
- **Honest labeling**: SYNTHETIC DEMO DATA banner; README honest-status table; SECURITY.md documents what a real deployment would still need.

## Out of scope (v1)

- Real bank/ERP integrations, payment posting, or GL writes.
- Multi-currency, taxes, or discounts (amounts are plain decimals).
- Authenticated multi-user access (actor stamps are form/API fields).
- Automated write-offs — `written_off` requires an explicit human transition.
- Real-time/streaming ingest (batch CSV + JSON API only).
