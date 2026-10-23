# Q05 — Architecture

## Module map

```
src/mavenu/
├── reconcile.py        # service layer: ingest, sanitization, exception queue,
│                       #   state transitions, reports, run log, audit events
├── matching.py         # deterministic two-pass matching engine + explanations
├── migrations/
│   ├── 008_reconciliation.sql       # invoices, payments, matches, exceptions,
│   │                                #   exception events, run log
│   └── 008_reconciliation.down.sql  # full rollback (tested for real)
└── web.py              # /project_q05* pages, /api/reconciliation* endpoints
```

## Data model

- `recon_invoices` — one row per invoice. `invoice_id` UNIQUE (natural
  idempotency key). `amount_cents` INTEGER (Decimal dollars × 100 at the
  service layer; never float). `source_row` + `ingest_batch` give CSV
  provenance for every row.
- `recon_payments` — one row per payment. `payment_id` UNIQUE. Optional
  `invoice_ref` (exact-pass key). `note` is sanitized text.
- `recon_matches` — one row per (invoice, payment) pairing, UNIQUE on the
  pair. `match_kind` (`exact` | `fuzzy`), `score` (Decimal text, 1.00 for
  exact), `explanation_json` (`[{rule, detail}]` — the auditable "why"),
  `matched_by` (`exact-pass` | `fuzzy-pass`).
- `recon_exceptions` — the queue. `kind`, `ref_type`/`ref_id`/`ref_public_id`,
  `detail_json` (structured facts; review candidates carry the top-N
  candidate breakdowns), `suggested_action` (the system's proposal —
  never posts), `state` (`open|investigating|resolved|written_off`,
  CHECK-constrained), actor stamps. Partial unique index
  `uq_recon_exceptions_open` on `(kind, ref_type, ref_public_id) WHERE
  state='open'` — the queue is a set, not a log, so re-runs rebuild it
  without duplicating it.
- `recon_exception_events` — append-only, actor-stamped transition
  history (FK `ON DELETE CASCADE`: rebuilds regenerate auto-created
  OPEN exceptions and their single creation row together; human-touched
  rows are never deleted).
- `recon_runs` — append-only ingest/match run log with counts.

## Matching engine (matching.py)

**Pass 1 — exact.** A payment with a non-empty `invoice_ref` whose
normalized form (uppercase, alphanumeric-only) equals a normalized
invoice ID matches it, score 1.00. Precision is structural: it can only
fire on ID equality.

**Pass 2 — fuzzy.** Each unmatched payment is scored against unmatched
invoices:

| Component | Weight | Rule |
|---|---|---|
| amount | 0.60 exact / 0.40 within ±$1.00 tolerance / 0.00 | cent-exact Decimal compare |
| date | 0.20 / 0.00 | `|paid_date − due_date| ≤ 14 days` |
| id overlap | 0.20 normalized-equal / 0.10 one-contains-the-other / 0.00 | against ref+note+customer |

`MatchConfig` holds the policy (`amount_tolerance_cents=100`,
`date_window_days=14`, `fuzzy_threshold=0.75`, `review_candidates=3`).

Decision rule: best score ≥ 0.75 → auto-match (`fuzzy`); best score > 0
but < 0.75 → `review_candidate` exception with the top-3 breakdowns —
**zero silent auto-matches**; best score = 0 → stays `unmatched_payment`.

**Coverage pass** (`rebuild_exceptions`): per invoice,
`paid = Σ matched payment cents`. `paid == 0` → `unmatched_invoice`;
`paid < amount` → `partial_payment` (balance in detail + suggested
action); `paid > amount` → `overpaid_invoice`. Open non-review,
non-duplicate exceptions are deleted and rebuilt from scratch each run
(idempotent); human-touched rows (`investigating`/`resolved`/
`written_off`) and ingest/review artifacts are preserved.

## Exception state machine

`open → investigating → resolved | written_off`, enforced by
`workflow.EXCEPTION_WORKFLOW`; `InvalidTransition` on any other move.
Write-off is terminal and human-only.

## Reports (reconcile.py)

- `reconciliation_summary()` — all totals from source-row SQL; verified
  identity: `outstanding − overpaid == invoiced − matched-paid`.
- `aging_report(now=)` — outstanding by days overdue vs. due date:
  `current`, `1–30`, `31–60`, `61–90`, `90+`; buckets sum to outstanding.
- `exception_aging(now=)` — open/investigating exceptions by age since
  creation: `0–7`, `8–30`, `31+` days. The clock is injectable.

## Ingest pipeline

CSV text → `csv.DictReader` → header validation → per-row:
sanitize (`sanitize_cell`) → validate (`parse_amount_cents` via Decimal,
`parse_iso_date`, due ≥ issued) → natural-key idempotency check →
INSERT. Errors accumulate as `{row, field: message}`; the batch never
aborts. Within-batch payment-ID repeats skip the row and raise an open
`duplicate_payment` exception. Every run is appended to `recon_runs`.

## Design rationale

- **Explainability is the thesis**: the match explanation JSON, the
  candidate breakdowns in review exceptions, and the reconciliation
  identity check turn "trust me" into "verify me".
- **The queue is a set**: the partial unique index makes regeneration
  idempotent and prevents exception spam across re-runs.
- **The system proposes, never posts**: write-offs and refunds are
  human decisions; the engine's job is to make the discrepancy and its
  suggested action impossible to miss.
