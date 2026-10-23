# Q02 — Test Plan

**Scope:** 133 tests across five files, all run with the project venv
pytest. P01's 51, P02's 101, and Q01's 89 tests must keep passing
(regression gate).

## Coverage map

| Area | File | Tests | What is asserted |
|---|---|---|---|
| Estimate validation | `test_estimates.py` | 5 | Missing customer name / unknown service / non-positive amount / oversize notes / missing estimator rejected with field errors |
| Estimate CRUD | `test_estimates.py` | 3 | Sequential `EST-000001` IDs, draft initial state, `estimate.created` audit event, newest-first listing |
| Lifecycle matrix | `test_estimates.py` | 49 | All 7×7 state pairs, each from a fresh estimate walked to the from-state: 15 legal moves succeed, 34 illegal raise `InvalidTransition` and leave state unchanged; 15-legal count asserted; terminal states have no outgoing moves |
| Decline reasons | `test_estimates.py` | 8 | Missing reason rejected (state unchanged), unknown reason rejected, all six documented reasons accepted and stored with `declined_at` stamp |
| Stamps + audit | `test_estimates.py` | 1 | `sent_at`/`viewed_at` stamped on entry; audit row carries actor and from/to |
| Unsubscribe | `test_estimates.py` | 2 | Flag set + `estimate.unsubscribed` event; unknown estimate → KeyError |
| Create idempotency | `test_estimates.py` | 1 | Repeated key replays original response; one estimate row |
| Migration rollback | `test_estimates.py` | 2 | Down-step rolls back 004 for real (7 tables dropped, record removed, P01/P02/Q01 untouched, re-apply works); unapplied rollback is a no-op |
| Template versioning | `test_estimate_templates.py` | 3 | Variable auto-extraction; new version deactivates old, history preserved, old version pinnable for render; active-only listing |
| Template rendering | `test_estimate_templates.py` | 4 | Full substitution; missing variable → `TemplateRenderError`; unknown template → error; `test_send` renders without queueing; `test_send` fails on missing variable |
| Template validation | `test_estimate_templates.py` | 2 | Bad names / empty subject+body / bad variable list rejected |
| Render performance | `test_estimate_templates.py` | 1 | 2,000 renders; p95 < 2 ms (measured 0.026 ms) |
| Cadence rules | `test_cadence.py` | 4 | Day 2/7/14 defaults seeded; gapped steps rejected; unknown template rejected; replacement atomic, old rows preserved |
| Due computation | `test_cadence.py` | 5 | Only due steps queued (10-day-old → steps 1+2); fresh estimate → none; boundary day exact; outbox row carries rendered copy + idempotency key + template version; `followup_queued` event actor-stamped with frozen timestamp |
| Scheduler idempotency | `test_cadence.py` | 2 | Second run queues nothing; **1,001 runs → zero new outbox rows**, UNIQUE keys hold |
| Stop rules | `test_cadence.py` | 5 | Accepted/declined/expired (parametrized), unsubscribed, and draft estimates are never queued |
| Failure analysis | `test_cadence.py` | 2 | Broken template → `estimate.followup_skipped` event, no outbox row, state unchanged; identical elapsed age across a DST boundary → identical due steps (UTC) |
| Expiry sweep | `test_cadence.py` | 1 | 40-day-old open estimate → expired with stamp; 10-day-old untouched; accepted untouched; second sweep is a no-op |
| Outbox flushing | `test_cadence.py` | 2 | Stub adapter logs `stub-logged`, rows → `sent`, one send-log row per outbox row; second flush is a no-op; empty outbox is a no-op |
| Aging reconciliation | `test_estimate_reports.py` | 2 | Open count/value and bucket counts/amounts match independent raw-SQL re-computation; empty DB zeros |
| Win/loss reconciliation | `test_estimate_reports.py` | 3 | By service type and by estimator match independent per-segment SQL (accepted/declined/expired/sent/value won); win-rate math incl. None-when-undecided; decline reasons grouped |
| Follow-up effectiveness | `test_estimate_reports.py` | 2 | Per-bucket estimates/accepted/accept-rate match independent SQL; median days sent→accepted (hand-checked 3.0); empty DB nulls |
| Web + API | `test_estimates_api.py` | 19 | Hub lists Q02; four pages render; HTML create → 303 to detail; HTML validation error → 422 re-render; HTML transition + cadence-run + flush buttons; API create 201 / replay 200 / invalid 422; detail GET (allowed transitions + events); transition + illegal 409; decline-reason required (422 → 200); unsubscribe stops cadence; unknown 404; templates list/create/test-send (200 + 409 on missing var); rules get/replace (+422 on empty); cadence run (+replay); outbox + flush; three report endpoints reconcile |

## Test doubles and determinism

- **Clock:** `T0 = 2026-10-23T12:00:00Z`; every service call passes `now=`.
  Event rows accept injectable timestamps so cadence assertions are exact.
- **No network, no randomness in assertions:** public IDs are sequential
  (`EST-000001`…); the scheduler is a pure function of (rows, rules, now).
- **Fixtures are synthetic:** invented customer names ("Acme Test Co"),
  invented estimators, invented amounts.

## What is not tested (documented gaps)

- Real message delivery (none exists by design; see README).
- Scheduled cadence execution (endpoint tested; cron wiring is an ops step).
- Concurrency (single-process demo; SQLite WAL only).
- Authentication (none exists by design; see SECURITY.md).
- Retention enforcement (recommended, not implemented).

## Regression gate

Full suite: `.venv/bin/python -m pytest tests/ -q` → **374 passed**
(51 P01 + 101 P02 + 89 Q01 + 133 Q02), recorded in TEST_RESULTS.md with
date and environment.
