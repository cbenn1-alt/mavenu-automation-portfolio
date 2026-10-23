# Q02 — Runbook

## Daily operation

1. **Run the cadence.** Trigger `POST /api/cadence/run` (or the "Run
   cadence now" button on `/project_q02/outbox`). In this demo the run is
   manual; a real deployment would call it from a scheduler (cron,
   systemd timer, or equivalent) — e.g. hourly. The scheduler is
   replay-safe: running it twice queues nothing new.
2. **Review the outbox** at `/project_q02/outbox`. Queued rows are
   rendered follow-ups waiting on the send adapter.
3. **Flush** (`POST /api/cadence/flush` or the button) to hand queued rows
   to the adapter. v1's stub adapter logs `stub-logged` rows and sends
   nothing — flushing is bookkeeping that proves the pipeline shape.
4. **Work the estimates**: move them through the lifecycle on
   `/project_q02/estimates/<id>` (sent → viewed → followed_up → accepted
   / declined with a reason / expired).
5. **Read the reports** at `/project_q02/reports` (aging, win/loss,
   follow-up effectiveness).

## Changing the cadence

Replace the rule set atomically:

```bash
curl -X POST localhost:8080/api/cadence/rules \
  -H 'Content-Type: application/json' \
  -d '{"rules": [
    {"step_index": 1, "days_after_sent": 1, "template_name": "followup_step1"},
    {"step_index": 2, "days_after_sent": 5, "template_name": "followup_step2"}
  ]}'
```

Steps must be unique, start at 1, have no gaps; every template name must
exist and be active. Old rules are deactivated, never deleted.

## Changing a template

`POST /api/estimate-templates` with an existing `name` creates a new
version (old versions stay queryable and pinnable). Before pointing a
live rule at a new version, validate it:

```bash
curl -X POST localhost:8080/api/estimate-templates/followup_step1/test-send \
  -H 'Content-Type: application/json' \
  -d '{"context": {"estimate_id": "EST-000001", "customer_name": "Acme Test Co",
                   "service_type": "hvac", "amount": "$1,250.00", "estimator": "Rosa"}}'
```

A missing variable fails here — never in the outbox.

## Stopping follow-ups for a customer

`POST /api/estimates/<id>/unsubscribe`. The estimate is excluded from
every future cadence run in any state; the opt-out is audit-logged.

## Expiring stale estimates

`POST` to the cadence run does not expire; expiry is a separate sweep in
the service layer (`sweep_expired`, default 30 days). In this demo it is
exercised by tests; a real deployment would call it from the same
scheduler as the cadence run.

## Backup

The entire system is one SQLite file (`MAVENU_DB_PATH`, default
`src/data/mavenu.db`). Back it up with a file copy while the app is
stopped, or via SQLite's backup API. There are no other stateful
components.

## Rollback procedure

Every schema change ships a down-step. To roll back Q02:

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection("src/data/mavenu.db")
rollback_migration(conn, "004_estimates.sql")  # True when applied
```

This drops the seven Q02 tables (`estimates`, `estimate_events`,
`cadence_rules`, `message_templates`, `estimate_outbox`, `send_log`,
`estimate_idempotency_keys`) and removes the migration record, leaving
P01/P02/Q01 tables untouched. Re-apply with `run_migrations(conn)`.

**Tested for real** on 2026-10-23:
`tests/test_estimates.py::test_migration_004_down_step_rolls_back_for_real`
(apply → use → roll back → verify isolation → re-apply). See TEST_RESULTS.md.

To roll back application code: check out the previous commit (see
BUILD_LOG.md); the migration down-step handles the schema side. Code and
schema rollbacks are independent because the app runs pending migrations
at startup — old code simply ignores tables it doesn't know about after
the down-step removes them.

## Incident notes

- **Scheduler queued nothing but estimates look due:** check that the
  estimates are in an open state, not unsubscribed, and that `sent_at`
  is set (drafts never queue). Check rule thresholds via
  `GET /api/cadence/rules`.
- **Outbox row count didn't grow on re-run:** expected — idempotency
  keys make replays no-ops. This is the system working.
- **`followup_skipped` events appearing:** a rule's template failed
  render-time validation. Fix the template (new version), `test_send`
  it, then re-run the cadence.
