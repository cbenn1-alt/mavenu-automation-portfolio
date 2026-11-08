# Project P05 — Requirements

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Purpose

Give the portfolio a governance layer over its own synthetic operations: a way to ask whether the system is healthy, what happens when a job fails, who needs to know, and what to do about it — without ever sending a real alert, executing a real job, or touching a production system. The architecture doc gives P05 in one line only ("health checks, retries, alerting, runbooks"); this spec is the full realisation of that line, grounded in the closest siblings: Q10 (retry queue, circuit breaker, dead-letter), S01 (alert severity routing, timed runbook walkthrough, incident tickets), and P04 (audit log, versioning).

## 2. Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-01 | Health checks: a check is a named probe + warn/fail thresholds over a numeric "badness" value. Probes: `db_reachable`, `migrations_current`, `queue_depth`, `storage_tmp`, `app_smoke` | Done |
| FR-02 | A probe run records status (pass/degraded/fail), the numeric value, a detail payload, duration in ms, and actor; the run's status is derived from the thresholds (value ≤ warn → pass; ≤ fail → degraded; else fail) | Done |
| FR-03 | Status summary: overall is `fail` if any latest run is fail, `degraded` if any is degraded, `unknown` if any check has never run, else `pass`; also reports open-alert and open-incident counts | Done |
| FR-04 | Queue-depth probe reads only allow-listed tables (`leads`, `missed_calls`, `estimates`, `docintel_documents`) and allow-listed state values; anything else is rejected before any SQL runs | Done |
| FR-05 | Retry policies are versioned data: `max_attempts` (1–10), `backoff_base_s` (> 0), `backoff_cap_s` (≥ base), `jitter_max_s` (≥ 0), `dead_letter_after` (≥ 1). Create → v1 `current`; supersede → new version `current`, old `superseded`. Jobs pin the policy version they were created with | Done |
| FR-06 | Backoff: delay after failure n is `min(cap, base × 2^(n−1))` plus deterministic jitter — SHA-256 of `policy_id:attempt` scaled to `[0, jitter_max_s)` — so the same inputs always give the same delay | Done |
| FR-07 | Jobs: create (name, policy, JSON payload) → `pending`; `attempt_job` records the caller-reported outcome. Success → `succeeded`. Failure → `scheduled` with `next_run_at = now + delay`, or `dead_lettered` once attempts reach `min(max_attempts, dead_letter_after)`, with a `gov_dead_letters` row. Terminal jobs cannot be attempted again | Done |
| FR-08 | `due_jobs(now)` returns pending/scheduled/retrying jobs with `next_run_at ≤ now`, ordered by next run time | Done |
| FR-09 | Dead-letter replay requeues the job as a fresh job (attempts reset, same name/policy/payload) and marks the dead-letter row `replayed`; a replayed row cannot be replayed again | Done |
| FR-10 | Alerting rules: a rule watches one check's metric (or any check) with operator `gt`/`gte`/`lt`/`lte`/`eq`/`ne`, a `Decimal` threshold, a severity, an owner, and a dedup window in seconds. Rules are evaluated against each recorded check run | Done |
| FR-11 | **Alerts are recorded only and never sent anywhere.** There is no send path in P05 — no email, webhook, SMS, or pager call exists in the module. The `channel` column is always `log` | Done |
| FR-12 | Dedup: a firing whose fingerprint (rule + check) matches an open/acked alert whose `last_seen` is inside the dedup window bumps that alert's `count` and `last_seen` instead of opening a new alert; outside the window, a new alert opens | Done |
| FR-13 | Silence: a rule silenced until a future timestamp does not fire; the skipped firing is recorded as a `rule.suppressed` audit event | Done |
| FR-14 | Alert lifecycle: `open → acked → resolved` (open → resolved also allowed); `resolved` is terminal. Transitions are enforced by `ALERT_WORKFLOW` | Done |
| FR-15 | Runbooks are versioned data: `name`, `alert_key`, 1–20 steps each with `step`, `action`, and a positive `timebox_s`. Supersede creates a new version; `runbook_for_key` returns the current runbook for an alert key | Done |
| FR-16 | Walkthrough harness: executes each step (default no-op work, injectable `step_work`) against an injectable clock and reports per-step elapsed time and whether it was within its time box, plus wall-clock elapsed time | Done |
| FR-17 | Incident lifecycle: `open → triaged → mitigating → resolved → closed`, plus reopen from `resolved` or `closed` back to `open`. Transitions are enforced by `INCIDENT_WORKFLOW`; resolving requires a resolution note; every transition and note is actor-stamped on the timeline | Done |
| FR-18 | Audit log: every create/supersede/run/fire/dedup/suppress/transition/note writes an event to `gov_events` with actor and timestamp | Done |
| FR-19 | Demo seed: idempotent synthetic definitions (5 checks, 2 policies, 4 rules, 2 runbooks), one run of each check, one demo job, one demo incident; a second seed inserts nothing | Done |
| FR-20 | Web UI + JSON API for status, checks (create/list/get/run), runs, policies (create/list/supersede), jobs (create/list/attempt), dead letters (list/replay), rules (create/list/silence), alerts (list/get/ack/resolve), runbooks (create/list/get/supersede/walkthrough), incidents (create/list/get/transition/note) | Done |

## 3. Non-functional requirements

| ID | Requirement | Status |
|---|---|---|
| NFR-01 | Python 3.12 standard library only; pytest; $0 cost | Done |
| NFR-02 | SQLite via the shared `mavenu.db` helpers; parameterized SQL only — the queue-depth probe's identifiers come only from an allow-list; every other value is bound as a parameter | Done |
| NFR-03 | Threshold comparisons use `Decimal` (never float) for rule evaluation; backoff delays are computed in float but are schedule data, not money — no financial claim is made from them | Done |
| NFR-04 | Input validation at every boundary: names (1–64 chars, `[A-Za-z0-9 _-]`), subsystems/kinds/probes/severities/operators from fixed enums, policy field ranges, step shape (1–20 steps, positive integer time boxes), ISO timestamps for silence, actor names | Done |
| NFR-05 | Every state change is audit-logged with actor + timestamp; suppressed rule firings are logged too | Done |
| NFR-06 | Migration `023_governance` is reversible: the down-step drops all eleven tables and is exercised by test | Done |
| NFR-07 | Synthetic data only — no real business data, no production database, no external service calls, no alert is ever sent; no performance claims beyond measured fixture timings | Done |

## 4. Acceptance criteria (Gate E)

1. All 36 P05 tests pass (23 service + 13 API), including the migration rollback test, the dedup-window test, and the injection-attempt tests.
2. The fixture oracle in `TEST_RESULTS.md` matches hand-computed values exactly (backoff 30/60/120/240/480 s, cap at 150 s, dead-letter at attempt 3, dedup count 2 within the window).
3. No injection attempt in the test suite reaches the database as SQL text — the queue-depth probe rejects unknown tables/values at validation, and the tables survive intact.
4. Migration down-step removes all eleven `gov_*` tables and is exercised by test.
5. Live smoke test: real HTTP seed → status → create check → run → policy → job → fail → dead-letter → replay → rule → alert → ack → resolve → incident → walkthrough → injection 422, hub and P05 pages render 200.
