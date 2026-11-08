# Project P05 — Test Results

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Headline

| Suite | File | Tests | Result |
|---|---|---|---|
| Service layer | `tests/test_governance.py` | 23 | ✅ 23 passed |
| API + pages | `tests/test_governance_api.py` | 13 | ✅ 13 passed |
| **P05 total** | | **36** | **✅ 36 passed** |

Run: `.venv/bin/python -m pytest tests/test_governance.py tests/test_governance_api.py -q`
— `36 passed in 1.62s` (2026-11-08).

Full repo suite after P05 (chunked runs, `/tmp/pytest-of-root` cleared between chunks — a 21-file chunk fills the 512 MB `/tmp` tmpfs mid-run and produces spurious `sqlite3.OperationalError: database or disk is full` errors; chunks of ~8 files pass cleanly): **1,757 passed, 2 failed** out of 1,759 collected (baseline 1,723 + 36 new). The 2 failures are **pre-existing and unrelated to P05** — both reproduce on the pristine tree via `git stash` (verified 2026-11-08, same as at the P03/P04 builds):
- `tests/test_reconciliation_api.py::test_aging_endpoint` — date-dependent: the fixture's due dates were written for 2026-10-23; on 2026-11-08 invoice INV-0007 (due 2026-11-01) has moved from "current" to "1–30 days overdue", so the current bucket is 0, not 60,000 cents.
- `tests/test_estimates_api.py::test_api_cadence_run_queues_due_steps` — same cause (cadence computed against the real clock).

Both were passing on 2026-10-23 and fail now purely because time moved on. They are **not fixed** here: the task instruction is to not change other projects, and the fix (freezing the clock in those tests) belongs to their owners.

Chunk breakdown (2026-11-08): 255 + 270 + 281 + 237 (1 pre-existing failure) + 262 + 186 (1 pre-existing failure) + 266 = 1,757 passed, 2 failed, 1,759 collected.

## 2. Fixture oracle (hand-computed, asserted by tests)

Seed `seed_demo_data` in `src/mavenu/governance.py`: 5 checks, 2 policies, 4 rules, 2 runbooks, 5 runs, 1 job, 1 incident.

| Measure | Expected | Actual |
|---|---|---|
| Backoff, base 30 s, cap 3,600 s, jitter 0 | attempts 1–5 → 30, 60, 120, 240, 480 s | same |
| Backoff cap, base 100 s, cap 150 s, jitter 0 | attempts 1–3 → 100, 150, 150 s | same |
| Jitter, base 30 s, jitter 5 s | same policy + attempt → same delay; delay 1 in [30, 35] s; delay 2 ≠ delay 1 | same |
| Retry limit | `min(max_attempts, dead_letter_after)` binds: max 5 / DL 3 → no retry at 3 attempts; max 2 / DL 5 → no retry at 2 attempts | same |
| Job failure path | failure 1 at T0 → scheduled, attempts 1, `next_run_at` T0+30 s; failure 2 at T0+30 s → scheduled, attempts 2, `next_run_at` T0+90 s; failure 3 → dead_lettered, attempts 3, dead-letter row open | same |
| Queue-depth thresholds | 3 pending calls → pass (3); 7 → degraded (7); 21 → fail (21) | same |
| Storage thresholds (injected disk usage) | 50% used → pass; 85% → degraded; 98% → fail | same |
| Rule firing | 21 pending calls, rule value > 20 → 1 alert, open, high, count 1, value 21 | same |
| Dedup window (3,600 s) | second run at T0+30 min → same alert, count 2; third run at T0+2 h → new alert; 2 open alerts | same |
| Silenced rule | rule silenced until 2026-11-09, run at T0 → no alert; 1 `rule.suppressed` audit event | same |
| Incident lifecycle | open → triaged → mitigating → resolved (note required) → closed → reopen to open; open → closed illegal; 5 timeline events after create + 3 transitions + note | same |
| Walkthrough (fake clock) | step elapsed 100 s / time boxes 900 + 3,600 s → all within; fake clock advancing 9,999 s on step 1 → step 1 over, `all_within_timebox` false | same |
| Seed idempotency | first seed creates 5/2/4/2 checks/policies/rules/runbooks + 5 runs + 1 job + 1 incident; second seed creates 0 of everything | same |

## 3. Rollback test

`test_migration_023_down_step_rolls_back_for_real` applies migration 023 to a fresh database, confirms all eleven `gov_*` tables exist, applies `023_governance.down.sql`, and confirms all eleven are gone, then re-applies 023 so later tests still see the tables. ✅ Passed.

## 4. Live smoke test (2026-11-08)

Real server (`python3 run.py --port 8125 --db /tmp/p05-live.db`), real HTTP:
- `GET /` → 200; `GET /project05` → 200.
- `POST /project05/seed` → 303.
- `GET /api/governance/status` → 200, overall `pass`, 5 checks, 0 open alerts.
- `POST /api/governance/checks` (SMOKE-QUEUE, queue_depth on `missed_calls`/`pending`) → 201, check id 6.
- `POST /api/governance/checks/6/run` → 200, `pass`, value 0 (empty queue), 0 ms.
- `POST /api/governance/policies` (SMOKE-POL, max 2, base 30 s) → 201, policy id 3.
- `POST /api/governance/jobs` (SMOKE-JOB, policy 3) → 201, job id 2, pending.
- Attempt 1 (failure) → 200, `scheduled`, attempts 1, `next_run_at` exactly +30 s (16:12:40 → 16:13:10).
- Attempt 2 (failure) → 200, `dead_lettered`, attempts 2; dead-letter row open.
- `POST /api/governance/dead-letters/1/replay` → 201, fresh job id 3, pending, attempts 0.
- `POST /api/governance/rules` (SMOKE-RULE, DB-REACHABLE value < 1 → low) → 201, rule id 5.
- `POST /api/governance/checks/1/run` → 200, `pass`, value 0, alerts `[1]` — the rule fired.
- `POST /api/governance/alerts/1/ack` → 200, `acked`; `/resolve` → 200, `resolved`.
- `POST /api/governance/incidents` (linked to alert 1) → 201, incident id 2, open, 1 timeline event.
- `POST /api/governance/incidents/2/transition` (to `triaged`) → 200; a second transition to `triaged` → 422 (self-transition not permitted).
- `POST /api/governance/runbooks/1/walkthrough` → 200, 4 steps, all within timebox, wall elapsed ~0.00001 s.
- Injection attempt (`queue_depth` table `"missed_calls; DROP TABLE leads"`) → 422; `leads` intact (`GET /api/stats` → total 0 on the empty smoke DB, tables present).
- Server stopped afterwards; temp DB deleted.

## 5. Bugs caught pre-ship (fixed before commit)

1. **Unescaped braces in a web.py f-string** (`p05_runbooks_page`: the textarea's default JSON `[{"step": ...}]` contained literal `{`/`}` that Python parsed as format specifiers). The page returned 500 `ValueError: Invalid format specifier`. Fixed by doubling the braces in the f-string; caught by the first API test run.
2. **Supersede-pointer direction (test, not code).** The service tests first read `new["superseded_by"]` expecting the old row's id; P04's convention is the opposite — the *old* row's `superseded_by` points to the *new* row. The tests were corrected to fetch the old version by name + version and assert its status and pointer. The service behaviour was already correct.
3. **Dedup-key collision in the test helper (test, not code).** `_pending_calls` reused `dedup-{i}` across calls in the same test, violating the `missed_calls.dedup_key` unique constraint on the second call. The helper now offsets keys per call.
4. **Job pins its policy version (test, not code).** The API lifecycle test first assumed superseding a policy would change an existing job's limit; it does not — the job pins the policy row it was created with, so the second failure dead-letters a max-2 job. The test was corrected to assert the pinning behaviour, which is the documented design.
5. **Timeline-count miscounts (tests, not code).** Two incident tests first asserted 6 timeline events where the correct count is 5 (created + 3 transitions + 1 note — failed transitions insert nothing). Corrected against the actual event log.

## 6. Known limitations

- **Five probes only.** The probe registry covers `db_reachable`, `migrations_current`, `queue_depth`, `storage_tmp`, `app_smoke`. A new subsystem needs a `_PROBES` entry — deliberate, not an oversight.
- **Queue-depth reads four tables only.** The allow-list covers `leads`, `missed_calls`, `estimates`, `docintel_documents` with their state enums. A new table needs a `_QUEUE_TABLES` entry.
- **Jobs execute no real work.** `attempt_job` records caller-reported outcomes; there is no executor, worker, or HTTP call. The schedule math is the feature; the execution is the caller's.
- **Alerts are recorded only.** There is no send path — no email, webhook, SMS, or pager. If a real notification channel is ever wanted, it is a new project with its own threat model, not a flag on P05.
- **Walkthrough steps are text.** The harness times the steps; it does not perform them. A walkthrough passing means the steps fit their time boxes on the clock, not that the underlying procedure was verified.
- **At most 20 steps per runbook, at most 10 attempts per policy.** Deliberate caps that keep the governance data small and readable.
