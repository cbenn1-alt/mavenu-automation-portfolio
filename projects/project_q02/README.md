# Q02 — Estimate Follow-Up Automation

**Status: Implemented · Tested** — 133 automated tests, all passing
(374/374 full suite: P01's 51 + P02's 101 + Q01's 89 + Q02's 133; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Estimate CRUD + lifecycle state machine (`draft → sent → viewed → followed_up → accepted \| declined \| expired`) enforced in code with CHECK constraints, timestamps and actor stamps on every transition; decline-reason capture (closed set); configurable follow-up cadence (day 2 / 7 / 14 defaults, replaceable rules); per-step message templates; cadence scheduler computing due follow-ups on an injectable frozen clock; outbox queue with idempotency keys (zero duplicates across 1,001 scheduler replays, tested); stub send adapter + send log; expiry sweep; unsubscribe stop rule; aging / win-loss / follow-up-effectiveness reports reconciled to rows in tests; migration rollback tested for real |
| What is SIMULATED | **Simulated** | The outbox is **not a mail server** — the automation is the cadence computation and the audit trail. The bundled `StubMessageAdapter` records a send-log row and delivers nothing anywhere. The cadence runs when triggered (`POST /api/cadence/run`), not on a schedule |
| What is SYNTHETIC | **Demo** | Every estimate, customer name ("Acme Test Co"), estimator label, amount, timestamp, and template is invented. The UI carries the "SYNTHETIC DEMO DATA" banner |
| What is NOT claimed | — | No production deployment. No real messages sent, no real customers, no messaging-provider integration. **No CAN-SPAM/TCPA-compliance review has been performed** — any real deployment that sends follow-ups needs telecom counsel first (see SECURITY.md). No platform or employer endorsement |

## Business problem

Estimates go out and die in inboxes. Techs are too busy on jobs to follow
up, and owners have no view of which estimates are aging, which were
declined, and why. This project gives every estimate a visible life —
sent, viewed, nudged on a schedule, won or lost with a reason — and makes
the follow-up cadence itself the auditable artifact, not a mail server.

## Implemented capabilities

- Estimate CRUD with server-side validation (synthetic customer name,
  service type, estimator, positive amount in cents, notes capped at
  2000 chars); duplicate protection via client `Idempotency-Key`
- Lifecycle enforced by `ESTIMATE_WORKFLOW` in code plus a SQLite CHECK
  constraint on `state`; all 49 state pairs tested (15 legal, 34 illegal —
  100% of illegal transitions rejected)
- Timestamps stamped per state (`sent_at`, `viewed_at`, `accepted_at`,
  `declined_at`, `expired_at`) and every transition writes an
  `estimate_events` audit row (actor, from/to, JSON detail) plus a stdout
  JSON log line
- Decline requires a reason from a closed set (`price`, `timing`,
  `chose_competitor`, `scope`, `no_response`, `other`) so win/loss
  reporting can group it
- Configurable cadence rules (step → days after sent → template);
  replacement is validated and atomic, old rules deactivated not deleted
- Versioned message templates: new version per name, history preserved,
  `{{variable}}` substitution with render-time validation — missing
  variables are a hard failure, never a half-filled message
- Scheduler: for each open, non-unsubscribed estimate, queues exactly one
  outbox row per due step; idempotency key `est:<id>:step:<n>` with a
  UNIQUE constraint; stop rules (accepted/declined/expired/unsubscribed)
  exclude estimates from every run
- Failure analysis implemented: broken template → `estimate.followup_skipped`
  event, estimate untouched (fail closed); UTC storage/comparison with an
  injectable clock (timezone-independence tested across a DST boundary);
  expiry sweep moves aging open estimates to `expired`
- Reports: aging buckets (0–2 / 3–7 / 8–14 / 15–30 / 31+ days), win/loss
  by service type and estimator (win rate = accepted / decided), decline
  reasons, follow-up effectiveness (accept rate by follow-up count,
  median days sent → accepted) — all reconciled against independent
  raw-SQL re-computations in tests
- Migration rollback: `004_estimates.down.sql` + `db.rollback_migration()`,
  tested for real (apply → use → roll back → re-apply)

## What is simulated (labeled, not hidden)

- **Sending**: `StubMessageAdapter` writes `send_log` rows with status
  `stub-logged`. The outbox → adapter → send-log pipeline is real and
  tested; delivery is not. The `MessageAdapter` protocol is the seam where
  a real provider would plug in.
- **Scheduling**: the cadence runs when triggered via the web button or
  `POST /api/cadence/run`; a real deployment would call it from a
  scheduler (documented in RUNBOOK.md).
- **Templates**: demo copy with honest "(demo message; nothing was sent)"
  footers.

## Technology stack

Python 3.12 stdlib (`wsgiref`-style app, `sqlite3`), pytest (dev only).
Zero runtime dependencies, zero cost, no network calls.

## Quick start

```bash
cd mavenu-portfolio
.venv/bin/python -m pytest tests/test_estimates.py tests/test_estimate_templates.py tests/test_cadence.py tests/test_estimate_reports.py tests/test_estimates_api.py -q
# expect: 133 passed
MAVENU_DB_PATH=/tmp/q02-demo.db python3 run.py --port 8124
# open http://localhost:8124/project_q02
```

See DEMO.md for a guided walkthrough and RUNBOOK.md for operations.
