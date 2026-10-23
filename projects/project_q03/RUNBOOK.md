# Q03 — Runbook

## Daily operation

1. **Record job history.** `POST /api/reactivation/customers` creates a
   (synthetic) customer; `POST
   /api/reactivation/customers/<public_id>/jobs` records completed jobs.
   In a real deployment this would be an import from the job system.
2. **Score.** Trigger `POST /api/reactivation/score` (or the "Score all
   customers" button on `/project_q03`). Every customer gets RFM
   features, a dormancy score, and a segment. Deterministic: replays
   produce identical scores.
3. **Run the win-back.** Trigger `POST /api/reactivation/winback-run`
   (or the button). Due steps for non-suppressed customers queue exactly
   one outbox row each. Replays are no-ops (idempotency keys).
4. **Review the outbox** at `/project_q03/outbox`. Queued rows are
   rendered touches waiting on the send adapter.
5. **Flush** (`POST /api/reactivation/outbox/flush` or the button) to
   hand queued rows to the adapter. v1's stub adapter logs `stub-logged`
   rows and sends nothing — flushing is bookkeeping that proves the
   pipeline shape. Suppression flags are re-checked here.
6. **Maintain suppression.** `POST
   /api/reactivation/customers/<public_id>/suppression`
   (`do_not_contact`, `active_job`) and `POST
   /api/reactivation/customers/<public_id>/complaint` set flags; every
   change is audit-logged and takes effect on the next queue/flush.
7. **Attribute.** `POST /api/reactivation/holdout` with a run name
   creates the deterministic treated/control split; `GET
   /api/reactivation/attribution?run_name=…&window_start=…&window_end=…`
   computes the holdout report (labeled synthetic-data illustration).

In this demo every step above is manual; a real deployment would call
score → win-back → flush from a scheduler (cron, systemd timer, or
equivalent). The scheduler entry points are idempotent, so overlapping
runs are safe.

## Changing a sequence

`SEQUENCE_PLANS` in `src/mavenu/reactivation.py` is the versioned plan
definition (steps are 1-based, `days_after_scored` offsets, `{{variable}}`
copy). Edit the plan, add a test pinning the step count, and re-run the
suite. Plans are code, not DB rows, so a code rollback restores the old
plan — but outbox rows already queued keep the segment/step they were
built under (by design: history is immutable).

## Changing scoring weights

Weights live in `src/mavenu/rfm.py` (`RECENCY_WEIGHT`,
`FREQUENCY_WEIGHT`, `MONETARY_WEIGHT` + normalization caps). Change them
in one place, update the hand-computed expectations in
`tests/test_reactivation.py`, and re-run. Re-score afterwards; old
`customer.scored` events keep the previous reasons for audit.

## Stopping touches for a customer

Set `do_not_contact: true` via the suppression endpoint. The customer is
excluded from every future win-back run in any segment, and any already-
queued touch is marked `suppressed` at the next flush instead of being
sent. Verify on `/project_q03/suppression`.

## Backup

The entire system is one SQLite file (`MAVENU_DB_PATH`, default
`src/data/mavenu.db`). Back it up with a file copy while the app is
stopped, or via SQLite's backup API. There are no other stateful
components.

## Rollback procedure

Every schema change ships a down-step. To roll back Q03:

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection("src/data/mavenu.db")
rollback_migration(conn, "005_reactivation.sql")  # True when applied
```

This drops the six Q03 tables (`reactivation_customers`,
`reactivation_jobs`, `reactivation_outbox`, `reactivation_send_log`,
`reactivation_holdouts`, `reactivation_events`) and removes the migration
record, leaving P01/P02/Q01/Q02 tables untouched. Re-apply with
`run_migrations(conn)`.

**Tested for real** on 2026-10-23:
`tests/test_reactivation.py::test_migration_005_down_step_rolls_back_for_real`
(apply → use → roll back → verify isolation → re-apply). See TEST_RESULTS.md.

To roll back application code: check out the previous commit (see
BUILD_LOG.md); the migration down-step handles the schema side. Code and
schema rollbacks are independent because the app runs pending migrations
at startup — old code simply ignores tables it doesn't know about after
the down-step removes them.

## Incident notes

- **Win-back queued nothing but customers look dormant:** check that
  customers are scored (segment set), not suppressed, and that the plan
  steps are due (step N queues only after `days_after_scored` days from
  `scored_at`). Check the `skipped` list in the run response for reasons.
- **Outbox row count didn't grow on re-run:** expected — idempotency
  keys make replays no-ops. This is the system working.
- **`touch.skipped` events appearing:** a plan step's template failed
  render-time validation. Fix the template copy and re-run.
- **Flush marked rows `suppressed`:** a suppression flag was set after
  queueing. This is the absolute-suppression guarantee working — see the
  suppression audit page.
