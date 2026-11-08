# Project P05 — Test Plan

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Strategy

- **Service tests** (`tests/test_governance.py`, 23 tests) exercise `governance.py` directly against a fresh SQLite database with migration `023_governance` applied (the `conn` fixture runs all migrations). No HTTP, no server.
- **API + page tests** (`tests/test_governance_api.py`, 13 tests) exercise the WSGI app through the shared `wsgi_call` helpers: JSON endpoints, form posts, page renders, status codes.
- **Fixture oracle**: one hand-built seed (`seed_demo_data` in `src/mavenu/governance.py`) plus hand-computed backoff/dedup expectations. Every delay, count, and threshold is asserted against the oracle — the tests cannot pass by construction, only by correct behaviour.
- **Determinism check**: the same policy and attempt always produce the same delay (`test_jitter_is_deterministic_and_bounded`); the same check run twice produces the same status for the same data.

## 2. Fixture design (synthetic only)

`seed_demo_data` inserts 5 checks, 2 policies, 4 rules, 2 runbooks, one run of each check, one demo job, and one demo incident — all invented. Idempotent: a second seed inserts nothing (`test_seed_demo_data_is_idempotent`). The queue-depth tests insert their own `missed_calls` rows with unique dedup keys per call (`_pending_calls` helper).

| Seed item | Rows | Hand-computed oracle |
|---|---|---|
| Checks | 5 | DB-REACHABLE, MIGRATIONS-CURRENT, QUEUE-MISSED-CALLS (warn 5 / fail 20), STORAGE-TMP (warn 80 / fail 95), APP-SMOKE — all pass on a fresh seeded DB |
| Policies | 2 | STANDARD-RETRY (max 5, base 30 s, cap 3,600 s, jitter 5 s, dead-letter 5); FAST-RETRY (max 3, base 5 s, cap 300 s, jitter 2 s, dead-letter 3) |
| Rules | 4 | QUEUE-DEPTH-HIGH (value > 20 → high), MIGRATIONS-PENDING (value > 0 → critical), STORAGE-HIGH (value > 90 → high), DB-UNREACHABLE (value > 0 → critical) |
| Runbooks | 2 | RB-CRITICAL (4 steps, time boxes 900/3,600/14,400/28,800 s); RB-HIGH (3 steps, 3,600/28,800/172,800 s) |
| Jobs | 1 | DEMO-WEBHOOK-DELIVERY, pending, policy STANDARD-RETRY |
| Incidents | 1 | "Demo: weekly governance review", low, open |

## 3. Coverage map (real test names — verify with `pytest --collect-only -q`)

| Area | Tests |
|---|---|
| Checks + probes | `test_create_and_run_db_check_passes`, `test_storage_probe_thresholds_with_injected_disk_usage`, `test_queue_depth_probe_counts_pending_calls`, `test_migrations_probe_passes_when_current`, `test_check_validation_rejects_bad_inputs`, `test_status_summary_aggregates_worst_and_unknown` |
| Policies + backoff | `test_backoff_schedule_is_exponential_and_capped`, `test_jitter_is_deterministic_and_bounded`, `test_should_retry_uses_min_of_max_and_dead_letter`, `test_policy_validation_and_supersede` |
| Jobs + dead letters | `test_job_success_path`, `test_job_failure_backoff_then_dead_letter`, `test_due_jobs_and_replay` |
| Rules + alerts | `test_rule_fires_alert_on_threshold_breach`, `test_rule_dedup_bumps_count_within_window`, `test_silenced_rule_does_not_fire_but_is_logged`, `test_alert_ack_and_resolve_transitions`, `test_rule_skips_missing_metric_and_rejects_bad_inputs` |
| Runbooks | `test_runbook_create_supersede_lookup`, `test_walkthrough_respects_timeboxes_with_fake_clock` |
| Incidents | `test_incident_full_lifecycle` |
| Seed + migration | `test_seed_demo_data_is_idempotent`, `test_migration_023_down_step_rolls_back_for_real` — `023` up applies 11 tables; down drops all 11 |
| API (13 tests) | `test_pages_render_before_and_after_seed`, `test_seed_is_idempotent_via_api`, `test_check_detail_page_and_run_form`, `test_status_api`, `test_create_check_api_and_validation`, `test_run_check_api`, `test_policy_supersede_and_job_lifecycle_api`, `test_job_create_rejects_unknown_policy`, `test_rule_fire_ack_resolve_api`, `test_rule_validation_and_silence_api`, `test_runbook_walkthrough_api`, `test_incident_lifecycle_api`, `test_incident_page_flow` |

## 4. What is NOT tested (deliberate)

- No real business data, no production database — out of scope by design.
- No performance/load testing — the SQLite demo scale (tens of rows) is the target; per-run `duration_ms` is recorded, not benchmarked.
- No multi-user concurrency — single-writer demo; SQLite WAL is the repo default.
- No real alert delivery — there is no send path to test; the tests assert alerts are recorded (and deduped, silenced, acked, resolved) and never claim a notification was sent.
- No real job execution — `attempt_job` records caller-reported outcomes; the tests assert the schedule math, not a worker.
