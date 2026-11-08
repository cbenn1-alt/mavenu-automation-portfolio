# Project P05 — Evidence Matrix

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

Every claim in this project's docs maps to a test, a file, or a measured run. If a claim has no evidence row, it is not a claim — it is a TODO.

## 1. Functional claims

| Claim | Evidence |
|---|---|
| Checks are a named probe + warn/fail thresholds; probes db_reachable, migrations_current, queue_depth, storage_tmp, app_smoke | `test_create_and_run_db_check_passes`, `test_migrations_probe_passes_when_current`, `test_queue_depth_probe_counts_pending_calls`, `test_storage_probe_thresholds_with_injected_disk_usage`, `ARCHITECTURE.md` §3 |
| A run records status/value/detail/duration/actor; status derived from thresholds (≤ warn pass, ≤ fail degraded, else fail) | `test_storage_probe_thresholds_with_injected_disk_usage` (50% pass / 85% degraded / 98% fail), `test_queue_depth_probe_counts_pending_calls` (3 pass / 7 degraded / 21 fail) |
| Status summary rolls latest runs into one verdict (fail > degraded > unknown > pass) + open counts | `test_status_summary_aggregates_worst_and_unknown`, `test_status_api` |
| Queue-depth probe reads only allow-listed tables/values; anything else rejected before SQL | `test_check_validation_rejects_bad_inputs`, `test_create_check_api_and_validation`; live smoke: `"missed_calls; DROP TABLE leads"` → 422 |
| Retry policies are versioned data (max 1–10, base > 0, cap ≥ base, jitter ≥ 0, dead-letter ≥ 1); supersede creates a new version; jobs pin their policy version | `test_policy_validation_and_supersede`, `test_policy_supersede_and_job_lifecycle_api` (job keeps v1 limits after supersede) |
| Backoff is `min(cap, base × 2^(n−1))` + deterministic SHA-256 jitter; same inputs give the same delay | `test_backoff_schedule_is_exponential_and_capped` (30/60/120/240/480; cap 100/150/150), `test_jitter_is_deterministic_and_bounded` |
| Jobs: success → succeeded; failure → scheduled with `next_run_at = now + delay`, or dead_lettered at `min(max_attempts, dead_letter_after)`; terminal jobs cannot be attempted | `test_job_success_path`, `test_job_failure_backoff_then_dead_letter` (T0 → +30 s → +90 s → dead-letter), `test_policy_supersede_and_job_lifecycle_api` |
| `due_jobs(now)` returns jobs with `next_run_at ≤ now`, ordered by next run | `test_due_jobs_and_replay` |
| Dead-letter replay creates a fresh job (attempts reset) and marks the row replayed; double replay rejected | `test_due_jobs_and_replay`, `test_policy_supersede_and_job_lifecycle_api` |
| Rules watch a check's metric with gt/gte/lt/lte/eq/ne and a `Decimal` threshold, severity, owner, dedup window | `test_rule_fires_alert_on_threshold_breach`, `test_rule_validation_and_silence_api` (bad operator/severity → 422) |
| Alerts are recorded only and never sent; no send path exists in the module; `channel` is always `log` | Code review of `src/mavenu/governance.py`; `SECURITY.md` §2; the P05 pages state it |
| Dedup: repeat firing inside the window bumps count/last_seen; outside the window a new alert opens | `test_rule_dedup_bumps_count_within_window` (count 2 at +30 min; new alert at +2 h) |
| Silenced rules do not fire; the suppression is audit-logged | `test_silenced_rule_does_not_fire_but_is_logged` |
| Alert lifecycle open → acked → resolved (open → resolved allowed); resolved is terminal | `test_alert_ack_and_resolve_transitions`, `test_rule_fire_ack_resolve_api` |
| Runbooks are versioned data (1–20 steps, positive integer time boxes); `runbook_for_key` returns the current runbook | `test_runbook_create_supersede_lookup` |
| Walkthrough harness times each step against its box with an injectable clock; reports per-step elapsed + wall time | `test_walkthrough_respects_timeboxes_with_fake_clock`, `test_runbook_walkthrough_api` |
| Incident lifecycle open → triaged → mitigating → resolved → closed + reopen; resolving requires a note; actor-stamped timeline | `test_incident_full_lifecycle`, `test_incident_lifecycle_api` |
| Audit log for every create/supersede/run/fire/dedup/suppress/transition/note | `test_seed_demo_data_is_idempotent` (events exist), `gov_events` table (`ARCHITECTURE.md` §2) |
| Demo seed idempotent (5 checks, 2 policies, 4 rules, 2 runbooks, 5 runs, 1 job, 1 incident) | `test_seed_demo_data_is_idempotent`, `test_seed_is_idempotent_via_api` |
| Web UI + JSON API for the whole flow | `tests/test_governance_api.py` (13 tests incl. 404/422 paths, form redirects, page renders) |
| Backoff is deterministic (same policy + attempt → same delay) | `test_jitter_is_deterministic_and_bounded` |

## 2. Fixture oracle arithmetic (hand-computed)

From `seed_demo_data` in `src/mavenu/governance.py` and the service tests:

| Measure | Arithmetic |
|---|---|
| Backoff 30/60/120/240/480 s | base 30, cap 3,600: 30×2⁰ = 30; 30×2¹ = 60; 30×2² = 120; 30×2³ = 240; 30×2⁴ = 480 — all under the cap |
| Backoff cap 100/150/150 s | base 100, cap 150: 100; min(150, 200) = 150; min(150, 400) = 150 |
| Job failure path | failure 1 at T0 → next T0+30 s; failure 2 at T0+30 s → delay 60 s → next T0+90 s; failure 3 → dead-letter (limit 3) |
| Queue thresholds | warn 5 / fail 20: 3 ≤ 5 → pass; 5 < 7 ≤ 20 → degraded; 21 > 20 → fail |
| Storage thresholds | warn 80 / fail 95: 50 → pass; 85 → degraded; 98 → fail |
| Dedup window | window 3,600 s: run at T0 fires; run at T0+1,800 s is inside → count 2; run at T0+7,200 s is 5,400 s after the last bump → outside → new alert |
| Incident timeline | created + triaged + mitigating + resolved + note = 5 events (failed transitions insert nothing) |

## 3. Non-functional claims

| Claim | Evidence |
|---|---|
| Stdlib only, pytest, $0 cost | `src/mavenu/governance.py` imports only stdlib + repo modules; no new dependency |
| Parameterized SQL only; queue-depth identifiers come only from the allow-list | Code review of `src/mavenu/governance.py`; injection tests (unknown table/value → 422, live smoke attempt → 422) |
| Input validation at every boundary | `test_check_validation_rejects_bad_inputs`, `test_policy_validation_and_supersede`, `test_rule_validation_and_silence_api`, API 422 tests |
| Resolving an incident requires a note | `test_incident_full_lifecycle`, `test_incident_lifecycle_api` |
| Migration 023 reversible; down-step exercised | `test_migration_023_down_step_rolls_back_for_real` |
| Live smoke test (real HTTP) | `TEST_RESULTS.md` §4 — hub 200, P05 200, seed 303, status `pass`, check 201 + run 200, policy 201, job 201, fail → +30 s → dead-letter, replay 201, rule 201, alert fired + ack + resolve 200, incident 201 + triaged 200 + self-transition 422, walkthrough 200, injection 422 (2026-11-08) |
| Full suite: 1,757 passed / 2 pre-existing date-dependent failures (1,759 collected) | `TEST_RESULTS.md` §1 — both failures reproduced on the pristine tree via `git stash` |

## 4. Honest-status banner (in every doc)

Implemented + tested (Gate E ✓) · synthetic/demo data only · no production deployment · no real clients · no bank approval · no real business data · no performance claims beyond measured fixture timings.
