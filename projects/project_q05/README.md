# Q05 — Invoice Reconciliation & Exception Reporter

**Status: Implemented · Tested** — 56 automated tests, all passing
(693/693 full suite: 637 baseline + 56 Q05; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Invoice + payment CSV ingest with schema validation, row-level error reporting, and CSV-formula sanitization; idempotent inserts on natural keys (`invoice_id`/`payment_id`); deterministic two-pass matching engine (exact invoice-ID pass, then scored fuzzy pass with documented threshold) where **every match carries its reasons**; exception queue (`unmatched_invoice`, `unmatched_payment`, `partial_payment`, `overpaid_invoice`, `duplicate_payment`, `review_candidate`) with a code-enforced state machine (`open → investigating → resolved \| written_off`), actor-stamped history, and a suggested next action per exception; reconciliation summary, aging buckets, and exception aging — every total computed from source rows and tested against independent SQL recomputation; migration `008_reconciliation.sql` + real rollback test; Decimal-only money math |
| What is SIMULATED | **Simulated** | The fixture datasets (invented invoices/payments — no real business, no real transactions). The fuzzy-match weights are a documented, deterministic scoring formula — not a trained model and never described as one. The "operator" actor in demos is a form field, not authenticated users |
| What is SYNTHETIC | **Demo** | **All financial data is synthetic.** Every amount, customer name, invoice ID, and date is fabricated for demonstration. The UI carries the "SYNTHETIC DEMO DATA" banner |
| What is NOT claimed | — | No production deployment. No real users, no real accounting data, no real write-offs performed. **This is explicitly not a substitute for real accounting controls or an audit.** No platform or employer endorsement |

## Business problem

Small firms reconcile invoices to payments in spreadsheets, monthly, by
memory. Discrepancies surface late; write-offs hide in the noise.

This project is a working reconciliation engine: invoice and payment CSVs
are ingested, matched by a deterministic two-pass engine that explains
every pairing, and every discrepancy lands in an exception queue with a
suggested next action. The reconciliation summary, aging report, and
exception aging are all computed from source rows — the owner can defend
every total line by line.

## Implemented capabilities

- **Ingest** (`reconcile.ingest_invoices` / `ingest_payments`): header
  validation, row-level errors with 1-based row numbers (bad rows never
  abort the batch), CSV-formula sanitization (`=`, `+`, `-`, `@` cells
  neutralized with a leading `'`), idempotent inserts on natural keys,
  within-batch duplicate payment detection → visible `duplicate_payment`
  exception instead of a silent double-count
- **Matching** (`matching.run_match`): exact pass on normalized invoice
  IDs (structural, 100% precision by construction), then fuzzy pass with
  a documented component score (amount 0.60/0.40, date 0.20, ID overlap
  0.20/0.10) and threshold 0.75; below-threshold candidates are **never**
  silently auto-matched — they route to a `review_candidate` exception
  with the top-3 candidate breakdowns; every match row stores its
  explanation as JSON
- **Exception queue** (`reconcile`): `open → investigating → resolved |
  written_off` enforced by `EXCEPTION_WORKFLOW` (illegal moves raise
  `InvalidTransition`); actor-stamped append-only history; every
  exception proposes a next action; match re-runs rebuild the OPEN queue
  idempotently (human-touched rows are never touched)
- **Reports** (`reconcile`): reconciliation summary with the verified
  identity `outstanding − overpaid == invoiced − matched-paid`; aging
  buckets (`current`, `1–30`, `31–60`, `61–90`, `90+`) summing to the
  outstanding total; exception aging by creation age; injectable clock
- **Money**: amounts parse through `Decimal`, store as integer cents,
  render as `Decimal` — float is never used for amounts (tested)
- **Web**: `/project_q05` (upload + run match), `/project_q05/exceptions`,
  `/project_q05/reports`, and `/api/reconciliation/*` (upload, run-match,
  summary, aging, exceptions, exception transitions)
- **Rollback**: `008_reconciliation.down.sql` + `db.rollback_migration()`,
  tested for real (apply → use → roll back → re-apply)

## What is simulated (labeled, not hidden)

- **The data**: every invoice, payment, name, and amount is invented.
  Demo amounts are not real financial data and must never be presented
  as such.
- **The scorer**: a transparent, deterministic formula with documented
  weights — not a learned model.
- **The operator**: actor stamps are form/API fields, not authenticated
  identities.

## What is not claimed

- No production deployment, no real users, no real financial records.
- **Write-off actions require human authorization.** The system proposes;
  it never posts. `written_off` is a terminal state reached only through
  an explicit, actor-stamped transition.
- **Not a substitute for real accounting controls or an audit.**
