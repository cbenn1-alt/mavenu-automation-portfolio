# Q02 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| Estimate CRUD + validation | Implemented, Tested | `estimates.create_estimate` / `normalize_estimate`; `tests/test_estimates.py` (validation + CRUD blocks); `POST /api/estimates` |
| Lifecycle `draft → sent → viewed → followed_up → accepted \| declined \| expired` enforced in code | Implemented, Tested | `workflow.ESTIMATE_WORKFLOW`; `transition_estimate()`; 49 parametrized matrix tests (15 legal / 34 illegal) |
| Timestamps + actor stamps on every transition | Implemented, Tested | `sent_at`/`viewed_at`/… columns; `estimate_events` rows; `test_state_timestamps_are_stamped` |
| Decline-reason capture (closed set) | Implemented, Tested | `DECLINE_REASONS`; `validate_decline()`; 8 decline tests; grouped in win/loss report |
| Configurable cadence (day 2 / 7 / 14) with per-step templates | Implemented, Tested | `cadence_rules` table + seed; `list_rules`/`replace_rules`; 4 rule tests; `POST /api/cadence/rules` |
| Versioned message templates, history preserved | Implemented, Tested | `templates.create_template`; `template_history()`; version-deactivation tests; pinned-render test |
| Scheduler computes due follow-ups on frozen clock | Implemented, Tested | `run_cadence()`; due/boundary/not-due tests; timezone-independence test |
| Outbox with idempotency keys; zero duplicates across replays | Implemented, Tested | UNIQUE `idempotency_key`; `ON CONFLICT DO NOTHING`; `test_scheduler_run_twice_queues_each_step_once`; `test_1000_scheduler_replays_produce_zero_duplicates` (1,001 runs) |
| Stub send adapter + send log; v1 sends nothing | Implemented, Tested (stub) | `StubMessageAdapter`; `flush_outbox()`; `send_log` UNIQUE(outbox_id); flush tests; labeled stub in README |
| Expiry sweep | Implemented, Tested | `sweep_expired()`; aging/open-only/idempotency assertions |
| Unsubscribe stop rule | Implemented, Tested | `set_unsubscribed()`; exclusion tested in cadence stop-rule tests |
| Render-time template validation (fail closed) | Implemented, Tested | `render_template` missing-variable failure; `test_send`; scheduler skip test with `estimate.followup_skipped` event |
| Aging report reconciles to rows | Implemented, Tested | `aging_report()`; `test_aging_report_reconciles_to_estimate_rows` (independent SQL) |
| Win/loss by service type and estimator | Implemented, Tested | `win_loss_report()`; per-segment reconciliation tests; `/project_q02/reports` |
| Follow-up effectiveness | Implemented, Tested | `followup_effectiveness()`; bucket + median reconciliation tests |
| Migration rollback tested | Implemented, Tested | `004_estimates.down.sql`; `db.rollback_migration()`; `test_migration_004_down_step_rolls_back_for_real` (run 2026-10-23) |
| Template render p95 < 2 ms | Tested | `test_render_p95_under_2ms`; measured p95 0.026 ms (TEST_RESULTS.md) |
| 100% of illegal transitions rejected | Tested | 34/34 parametrized illegal pairs raise `InvalidTransition` |
| Outbox is not a mail server — "the automation is the cadence computation and the audit trail" | Simulated (labeled) | README "What is simulated"; `StubMessageAdapter` docstring; honest stub text; RUNBOOK incident notes |
| Scheduled execution | Simulated (labeled) | Triggered via button/API; cron wiring documented as an ops step in RUNBOOK |
| All estimate/customer data synthetic | Demo | Fictional fixtures ("Acme Test Co"); SYNTHETIC DEMO DATA banner in `web.py` |
| No production deployment / no real messages sent / no real users | — (not claimed) | Honest-status banner in README; no such claim anywhere |
| No CAN-SPAM/TCPA-compliance review performed | — (explicitly not claimed) | README banner; SECURITY.md section advising counsel |
| P01/P02/Q01 regression-free | Tested | Full suite `374 passed` 2026-10-23 (TEST_RESULTS.md) |

## Claim-grade summary

- **Verified on the custom stack:** estimate CRUD + validation, full
  49-pair lifecycle matrix, timestamp/actor audit trail, decline reasons,
  configurable cadence rules, versioned templates with render-time
  validation, frozen-clock scheduler, idempotent outbox (1,001 replays,
  zero duplicates), stop rules, expiry sweep, stub flush + send log,
  reconciled aging/win-loss/effectiveness reports, migration rollback.
- **Simulated, labeled:** message delivery (stub adapter), scheduled
  execution (triggered), template copy (demo footers).
- **Not demonstrated:** real provider integration, CAN-SPAM/TCPA-compliant
  sending, authenticated multi-user access, retention enforcement.
