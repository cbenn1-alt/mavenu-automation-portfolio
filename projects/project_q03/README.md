# Q03 — Customer Reactivation Engine

**Status: Implemented · Tested** — 56 automated tests, all passing
(430/430 full suite: P01's 51 + P02's 101 + Q01's 89 + Q02's 133 + Q03's 56; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | RFM feature computation over synthetic job history; dormancy scoring behind a replaceable `DormancyScorer` protocol with documented weights (0.50 recency / 0.30 frequency / 0.20 monetary), 100% deterministic across replays; segment assignment (`active / cooling / dormant / churned`) with documented boundaries; per-segment win-back touch plans; outbox queue with idempotency keys (zero duplicates across 201 scheduler replays, tested); suppression rules (do-not-contact, recent complaint, active job) honored absolutely — checked at queue-build AND re-checked at send time, zero leaks across adversarial tests; stub send adapter + send log; holdout split + return-rate attribution arithmetic verified against hand-computed fixtures; segment/suppression reports reconciled to rows in tests; migration rollback tested for real |
| What is SIMULATED | **Simulated** | The outbox is **not a messaging system** — the automation is the dormancy scoring, the sequence computation, and the audit trail. The bundled `StubMessageAdapter` records a send-log row and delivers nothing anywhere. Win-back runs and attribution analyses run when triggered, not on a schedule |
| What is SYNTHETIC | **Synthetic** | Every customer, job, touch, and booking is invented ("Acme Test Co", "Beta Demo LLC", …). **Attribution results are a synthetic-data illustration of the arithmetic, never a measured campaign lift** — the report carries that label in the API, the UI, and the code |
| What is NOT claimed | — | No production deployment. No real messages sent, no real customers, no messaging-provider integration. No consent/opt-out review has been performed for real outreach — any real deployment needs telecom counsel first (see SECURITY.md). No platform or employer endorsement |

## Business problem

Past customers are the cheapest revenue a service business has, but nobody
mines them: no dormancy definition, no list, no sequence, no measurement.
This project gives every past customer a dormancy score, puts each one in a
segment with a purpose-built win-back sequence, respects every suppression
flag absolutely, and measures what came back against a holdout group — so
the owner can see, touch by touch, whether the win-back is working.

## Implemented capabilities

- **RFM features** (`src/mavenu/rfm.py`): recency (days since last job),
  frequency (lifetime jobs), monetary (lifetime cents) computed over job
  history at an injectable reference time; future-dated jobs ignored;
  no-history customers handled explicitly
- **Dormancy scoring** behind the `DormancyScorer` protocol (same seam
  pattern as P01's `LeadClassifier` / Q01's `UrgencyScorer`); the bundled
  `DeterministicDemoScorer` applies documented weights
  (`dormancy = 0.50·recency_norm + 0.30·(1−frequency_norm) + 0.20·(1−monetary_norm)`,
  normalization caps documented); every weight explained in the score's
  reasons; scores rounded to 3 decimals
- **Segmentation**: `active < 0.25`, `cooling < 0.50`, `dormant < 0.75`,
  `churned ≤ 1.0`; boundaries tested exactly
- **Suppression (absolute)**: do-not-contact flag, complaint within 180
  days, or active job excludes the customer from every win-back step —
  checked in `run_winback` (queue-build) and re-checked in `flush_outbox`
  (send time); a touch queued before a mid-sequence complaint is marked
  `suppressed` and the adapter is never called
- **Sequences**: per-segment touch plans (cooling 2 steps, dormant 3,
  churned 2, active none); reminders-only copy, never pressure tactics;
  global frequency cap (6 touches / 90 days); `{{variable}}` render with
  fail-closed missing-variable errors
- **Outbox**: idempotency key `rx:<customer_id>:seg:<segment>:step:<n>`
  with UNIQUE constraint; scheduler replays are no-ops; only due steps
  (scored_at + day offset elapsed) queue
- **Attribution** (`src/mavenu/attribution.py`): deterministic SHA-256
  holdout split per (run_name, public_id); treated return = traced
  reactivation bookings (source flag + a sent touch predating the job);
  control return = organic bookings; lift = treated − control with Wald
  95% CI; the report always carries the synthetic-data illustration label
- **Reports**: per-segment counts / mean dormancy / suppression tallies,
  outbox status totals, suppression audit (every flagged customer + its
  reason + event trail) — all reconciled against independent raw-SQL
  re-computations in tests
- **Audit trail**: `reactivation_events` rows (actor, JSON detail) plus
  stdout JSON log lines for scoring, suppression, queueing, flushing
- **Web UI + API**: `/project_q03*` pages (overview, segments, outbox,
  attribution, suppression audit) and `/api/reactivation*` endpoints
  (customers, jobs, suppression, complaint, score, win-back run, segments,
  outbox, flush, holdout, attribution, suppression audit, scoring info)
- **Migration rollback**: `005_reactivation.down.sql` +
  `db.rollback_migration()`, tested for real (apply → use → roll back →
  verify isolation → re-apply)

## What is simulated (labeled, not hidden)

- **Sending**: `StubMessageAdapter` writes `send_log` rows with status
  `stub-logged`. The outbox → adapter → send-log pipeline is real and
  tested; delivery is not. The `MessageAdapter` protocol (shared with Q02)
  is the seam where a real provider would plug in.
- **Scheduling**: win-back runs and attribution analyses execute when
  triggered via button/API; a real deployment would call them from a
  scheduler (documented in RUNBOOK.md).
- **Attribution**: the holdout arithmetic is real and verified; the data
  it runs on is synthetic, so any "lift" is an illustration of the method,
  not evidence of campaign performance.

## Technology stack

Python 3.12 stdlib (`wsgiref`-style app, `sqlite3`, `hashlib`), pytest
(dev only). Zero runtime dependencies, zero cost, no network calls.

## Quick start

```bash
cd mavenu-portfolio
.venv/bin/python -m pytest tests/test_reactivation.py tests/test_attribution.py tests/test_reactivation_api.py -q
# expect: 56 passed
MAVENU_DB_PATH=/tmp/q03-demo.db python3 run.py --port 8125
# open http://localhost:8125/project_q03
```

See DEMO.md for a guided walkthrough and RUNBOOK.md for operations.
