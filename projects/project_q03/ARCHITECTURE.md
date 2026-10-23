# Q03 — Architecture

```
synthetic job history (reactivation_jobs)
        │
        ▼
┌───────────────┐   features/        ┌────────────────────┐
│  compute_rfm  │ ─────────────────▶ │ DormancyScorer     │  scoring/
│  (rfm.py)     │   RFMFeatures      │ protocol +         │
└───────────────┘                    │ DeterministicDemo  │  (rfm.py)
                                     │ Scorer (weights    │
                                     │ 0.50/0.30/0.20)    │
                                     └────────┬───────────┘
                                              │ DormancyScore
                                              ▼
                                     ┌────────────────────┐
                                     │ segment_for_score  │
                                     │ active/cooling/    │
                                     │ dormant/churned    │
                                     └────────┬───────────┘
                                              ▼
┌───────────────┐  suppression       ┌────────────────────┐
│ do-not-contact│ ─── checked ─────▶ │ run_winback        │  sequences/
│ recent        │  at queue-build    │ (reactivation.py)  │  (reactivation.py)
│ complaint     │                    └────────┬───────────┘
│ active job    │                             │ due steps only
└───────────────┘                             ▼
                                     ┌────────────────────┐
                                     │ reactivation_      │  outbox
                                     │ outbox (idempotency│  (same honest
                                     │ key rx:<id>:seg:   │  pattern as Q02)
                                     │ <seg>:step:<n>)    │
                                     └────────┬───────────┘
                                              │ flush_outbox
                    suppression re-checked ───┘ at send time
                                              ▼
                                     ┌────────────────────┐
                                     │ MessageAdapter     │  stub in v1:
                                     │ (stub → send log)  │  sends nothing
                                     └────────┬───────────┘
                                              ▼
                                     ┌────────────────────┐
                                     │ attribution/       │  attribution.py:
                                     │ holdout split,     │  SHA-256 split,
                                     │ return rates,      │  traced bookings,
                                     │ lift + Wald 95% CI │  synthetic label
                                     └────────────────────┘
```

## Modules

| Module | Responsibility |
|---|---|
| `src/mavenu/rfm.py` | `compute_rfm()` (pure features), `DormancyScorer` protocol, `DeterministicDemoScorer` with documented weights. No DB, no I/O — unit-testable in isolation. |
| `src/mavenu/reactivation.py` | Customers/jobs CRUD + validation, `score_customers()` (persist score/segment), `suppression_reason()`/`is_suppressed()`, `set_suppression()`/`record_complaint()`, `SEQUENCE_PLANS`, `run_winback()` (due-step queueing, idempotent), `flush_outbox()` (stub adapter, suppression re-check), `render_touch()` (fail-closed templates), reports (`segment_report`, `suppression_audit`, `touch_history`). Reuses Q02's `MessageAdapter`/`StubMessageAdapter` seam. |
| `src/mavenu/attribution.py` | `split_holdout()` (deterministic), `holdout_groups()`, `attribution_report()` (traced bookings, rates, lift, Wald CI, synthetic label). |

## Schema (migration `005_reactivation.sql`)

- `reactivation_customers` — public_id (`CUS-000001`), synthetic name,
  suppression flags (`do_not_contact`, `complaint_at`, `active_job`,
  `active_job_ref`), scoring state (`segment`, `dormancy_score`,
  `scored_at`).
- `reactivation_jobs` — per-customer job history; `booking_source`
  (`organic` | `reactivation`) is the attribution provenance flag.
- `reactivation_outbox` — rendered touches; UNIQUE `idempotency_key`
  (`rx:<customer_id>:seg:<segment>:step:<n>`); status
  (`queued` | `sent` | `suppressed` | `failed`).
- `reactivation_send_log` — stub adapter outcomes; UNIQUE `outbox_id`.
- `reactivation_holdouts` — (run_name, customer_id) → treated/control;
  UNIQUE (run_name, customer_id).
- `reactivation_events` — append-only audit trail.

Down-step `005_reactivation.down.sql` drops all six tables (FK order),
leaving P01/P02/Q01/Q02 tables untouched.

## Key design decisions

1. **Same scoring-protocol pattern as P01/Q01.** `DormancyScorer` is the
   seam where a real model would plug in; the demo scorer never claims to
   learn or predict.
2. **Same honest outbox pattern as Q02.** v1 sends nothing; the pipeline
   shape (queue → adapter → send log) is real and tested, delivery is a
   labeled stub.
3. **Suppression checked twice.** Queue-build skips suppressed customers;
   flush re-checks live flags, so a complaint recorded mid-sequence
   converts queued rows to `suppressed` without ever calling the adapter.
4. **Attribution traced, not assumed.** A treated booking counts only
   when it carries the reactivation flag AND a sent touch predates it —
   bookings without a prior touch are explicitly excluded (tested).
5. **Frozen clock everywhere.** All cadence math takes an injectable
   `now`; UTC storage, local rendering only in the UI.
6. **Reminders, not manipulation.** Sequence copy is check-ins and
   opt-out reminders; pressure tactics are out of scope by design
   (see SECURITY.md).

## Rationale

Scoring + outbox + measurement is now a proven reusable trio (Q01/Q02/Q03):
the dormancy engine defines the list, the sequences define the touches,
and the holdout defines whether any of it worked — all on synthetic data
with the honesty labels baked into the report itself.
