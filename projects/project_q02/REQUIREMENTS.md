# Q02 — Requirements

Target user: owner/operators of 1–10-person home-service firms
(HVAC, plumbing, electrical, roofing, landscaping), working from the
office manager's desk. v1 is a **cadence computation and audit engine**
with an outbox queue — it does not send real messages.

## Functional requirements

### FR-1 Estimate records
- FR-1.1 Create estimates with: synthetic customer name (required,
  ≤120 chars), service type (one of `hvac`, `plumbing`, `electrical`,
  `roofing`, `landscaping`), estimator label (required, ≤80 chars),
  amount in cents (positive integer), notes (≤2000 chars).
- FR-1.2 Public IDs are sequential (`EST-000001`…); new estimates start
  in `draft`.
- FR-1.3 Client `Idempotency-Key` replay (header or form field) returns
  the original create response without a duplicate record.

### FR-2 Lifecycle state machine
- FR-2.1 States: `draft → sent → viewed → followed_up → accepted |
  declined | expired`. Legal moves: draft→sent; sent→{viewed, followed_up,
  accepted, declined, expired}; viewed→{followed_up, accepted, declined,
  expired}; followed_up→{followed_up, viewed, accepted, declined,
  expired}. accepted/declined/expired are terminal.
- FR-2.2 Transitions are enforced in code (`ESTIMATE_WORKFLOW`) and by a
  SQLite CHECK constraint on `state`. Illegal moves raise
  `InvalidTransition` and change nothing — 100% of the 34 illegal pairs
  rejected, tested.
- FR-2.3 Every transition stamps the relevant `*_at` column (UTC
  ISO-8601) and writes an `estimate_events` row (actor, from/to, detail)
  plus a JSON stdout log line.

### FR-3 Decline reasons
- FR-3.1 Moving to `declined` requires a `decline_reason` from the closed
  set: `price`, `timing`, `chose_competitor`, `scope`, `no_response`,
  `other`. Missing/unknown reasons are rejected with field errors.
- FR-3.2 An optional free-text `decline_note` (≤2000 chars) may be stored.

### FR-4 Cadence rules (configurable)
- FR-4.1 Rules map a 1-based step index → days after sent → template
  name. Defaults: step 1 = day 2, step 2 = day 7, step 3 = day 14.
- FR-4.2 Replacing the rule set validates step indexes (unique, start at
  1, no gaps), non-negative days, and that each template exists; old
  rules are deactivated, not deleted.

### FR-5 Scheduler
- FR-5.1 `run_cadence(now)` queues, for each open (`sent`/`viewed`/
  `followed_up`), non-unsubscribed estimate with `sent_at` set, every
  active rule step whose day threshold has elapsed and that has not been
  queued before.
- FR-5.2 Each queued step renders the active template version and writes
  exactly one `estimate_outbox` row with idempotency key
  `est:<estimate_id>:step:<step_index>` (UNIQUE). Scheduler replays queue
  nothing new — zero duplicates across 1,001 runs, tested.
- FR-5.3 Stop rules: accepted, declined, expired, unsubscribed, and draft
  estimates are never queued.
- FR-5.4 The estimate moves to `followed_up` on its first queued step
  (`followup_count`, `last_followup_at` stamped); later steps increment
  the count without changing state.
- FR-5.5 A template that fails render-time validation is skipped
  fail-closed: an `estimate.followup_skipped` event is recorded, no outbox
  row is written, the estimate is untouched.
- FR-5.6 The clock is injectable; all timestamps are stored and compared
  in UTC (timezone-independence tested).

### FR-6 Outbox and send adapter
- FR-6.1 Outbox rows carry the rendered subject/body, template name +
  version, step, scheduled time, and a synthetic recipient label (never a
  real address).
- FR-6.2 `flush_outbox(adapter)` hands queued rows to a `MessageAdapter`
  and writes one `send_log` row per outbox row; flushed rows are never
  flushed twice. v1 ships only `StubMessageAdapter` (status
  `stub-logged`; delivers nothing).

### FR-7 Expiry
- FR-7.1 `sweep_expired(now, expiry_days=30)` moves open estimates older
  than the window to `expired` with an audit event; the sweep is
  idempotent.

### FR-8 Unsubscribe
- FR-8.1 `set_unsubscribed` flags the estimate; unsubscribed estimates
  are excluded from every cadence run in any state.

### FR-9 Templates
- FR-9.1 Templates are versioned per name (new version deactivates old;
  history preserved and pinnable for render).
- FR-9.2 `{{variable}}` substitution; render fails loudly on missing
  required variables. `test_send` renders against a fixture context
  without queueing anything (the render-time validation gate).

### FR-10 Reports
- FR-10.1 Aging: open estimates bucketed 0–2 / 3–7 / 8–14 / 15–30 / 31+
  days since sent, with counts and open value; buckets reconcile to rows.
- FR-10.2 Win/loss by service type and by estimator: sent opportunities,
  accepted, declined, expired, win rate (accepted / decided; null when
  undecided), value won; decline reasons grouped.
- FR-10.3 Follow-up effectiveness: accept rate by follow-up count
  (0 / 1 / 2 / 3+), median days sent → accepted over accepted estimates.

## Non-functional requirements

- NFR-1 Zero cost: Python 3.12 stdlib only at runtime; no network calls.
- NFR-2 Determinism: frozen-clock tests make cadence and report
  assertions equality checks.
- NFR-3 Performance: template render p95 < 2 ms (measured 0.026 ms).
- NFR-4 Rollback: `004_estimates.down.sql` drops all Q02 tables without
  touching P01/P02/Q01; tested for real.
- NFR-5 Honesty: status vocabulary exactly Implemented / Tested /
  Simulated / Demo; no production, no real-message, no endorsement claims.

## Out of scope (v1)

Real message delivery, scheduled execution, multi-user auth, retention
enforcement, CAN-SPAM/TCPA review (documented as required before any real
deployment — see SECURITY.md).
