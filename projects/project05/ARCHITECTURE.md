# Project P05 — Architecture

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Module map

| Module | Responsibility |
|---|---|
| `src/mavenu/governance.py` | Service layer: probes, checks, retry policies, jobs, dead letters, alerting rules, alerts, runbooks, walkthrough harness, incidents, demo seed, audit events. |
| `src/mavenu/workflow.py` | `INCIDENT_WORKFLOW` (open→triaged→mitigating→resolved→closed + reopen) and `ALERT_WORKFLOW` (open→acked→resolved), alongside the sibling workflows. |
| `src/mavenu/web.py` | P05 pages + `/api/governance/*` JSON endpoints; reuses shared page helpers and the Q05-style form-post → 303-redirect pattern. |
| `src/mavenu/migrations/023_governance.sql` | Eleven tables (see §2). `023_governance.down.sql` drops them all. |
| `tests/test_governance.py` | 23 service-layer tests incl. the hand-computed backoff/dead-letter/dedup oracle and the migration rollback test. |
| `tests/test_governance_api.py` | 13 API + page tests over the WSGI app. |

## 2. Data model (migration 023)

| Table | Purpose |
|---|---|
| `gov_checks` | One row per check: `name` (unique), `subsystem` (`db`/`queue`/`storage`/`app`), `kind` (`liveness`/`readiness`), `probe`, `params_json`, `warn_threshold`, `fail_threshold`, `description`, `created_by`. |
| `gov_check_runs` | One row per probe execution: `check_id`, `status` (`pass`/`degraded`/`fail`), `value_json`, `detail_json`, `duration_ms`, `actor`, timestamps. |
| `gov_policies` | One row per retry-policy version: `name`, `version`, `status` (`current`/`superseded`), `max_attempts`, `backoff_base_s`, `backoff_cap_s`, `jitter_max_s`, `dead_letter_after`, `description`, `created_by`, `superseded_by`. Unique per `(name, version)`; only one `current` per name. |
| `gov_jobs` | One row per retry job: `name`, `policy_id` (pinned version), `payload_json`, `status` (`pending`/`scheduled`/`retrying`/`succeeded`/`dead_lettered`), `attempts`, `next_run_at`, `last_error`, `actor`, timestamps. |
| `gov_dead_letters` | One row per dead-lettered job: `job_id`, `policy_id`, `attempts`, `last_error`, `payload_json`, `status` (`open`/`replayed`). |
| `gov_rules` | One row per alerting rule: `name` (unique), `check_name` (NULL = any check), `metric`, `operator`, `threshold` (stored as text, compared as `Decimal`), `severity`, `owner`, `channel` (always `log`), `dedup_window_s`, `silenced_until`, `status` (`active`/`disabled`), `created_by`. |
| `gov_alerts` | One row per alert: `fingerprint` (SHA-256 of `rule_id:check_id`), `rule_id`, `check_id`, `severity`, `status` (`open`/`acked`/`resolved`), `first_seen`, `last_seen`, `count`, `detail_json`. |
| `gov_runbooks` | One row per runbook version: `name`, `version`, `status`, `alert_key`, `steps_json`, `created_by`, `superseded_by`. Unique per `(name, version)`. |
| `gov_incidents` | One row per incident: `title`, `severity`, `status`, `source_alert_id` (nullable FK to `gov_alerts`), `resolution_note`, `actor`, timestamps. |
| `gov_incident_events` | Timeline rows: `incident_id`, `event_type` (`created`/`transition`/`note`), `actor`, `from_status`, `to_status`, `detail_json`. |
| `gov_events` | Append-only audit log: `entity_type`, `entity_id`, `event_type`, `actor`, `detail_json`, `created_at`. |

Foreign keys: runs reference their check; jobs reference their policy; dead letters reference their job and policy; alerts reference their rule and check; incidents optionally reference an alert; incident events reference their incident. The operational tables the queue probe reads (`leads`, `missed_calls`, `estimates`, `docintel_documents`) are owned by other projects — P05 reads them, never writes them.

## 3. Probes

A probe returns `(value, detail)`. `value` is a numeric "badness" measure — higher is worse — and the check's thresholds turn it into a status. Boolean probes return 0 (good) or 1 (bad) with warn = fail = 0.

| Probe | What it measures | Value |
|---|---|---|
| `db_reachable` | `SELECT 1` answers and the database has tables | 0 / 1 |
| `migrations_current` | Count of migration files in `src/mavenu/migrations/` not recorded in `schema_migrations` | pending count |
| `queue_depth` | `COUNT(*)` of rows in an allow-listed table with an allow-listed state value | row count |
| `storage_tmp` | Percent of the given path's filesystem used (injectable `disk_usage` fn for tests) | used % (1 decimal) |
| `app_smoke` | Migrations applied and the `gov_checks`/`gov_policies`/`gov_rules` tables present | 0 / 1 |

The queue-depth probe is the only probe that builds SQL from a caller-supplied name, and it does so only through `_QUEUE_TABLES`: the table and column come from the allow-list, the state value is bound as a parameter. There is no code path that interpolates caller text into SQL.

## 4. Retry policies as data

A policy is a row, not code. `next_delay_s(policy, attempts_completed)` computes `min(cap, base × 2^(n−1))` plus deterministic jitter: SHA-256 of `f"{policy_id}:{attempts_completed}"`, first 8 hex digits scaled to `[0, jitter_max_s)`. The same policy and attempt always give the same delay, which is what makes the schedule testable — the oracle in `TEST_RESULTS.md` asserts exact delays. A job pins the policy row it was created with, so superseding a policy never changes an in-flight job's schedule. The effective attempt limit is `min(max_attempts, dead_letter_after)`: whichever binds first dead-letters the job.

**Jobs execute no real work.** `attempt_job` records the outcome the caller reports and computes the next delay or the dead-letter transition. There is no executor, no HTTP call, no queue worker in P05 — the job table is a record of retry *decisions*, and the demo's "attempts" are the operator pressing a button (or the API caller reporting what happened).

## 5. Alerting: recorded, never sent

`evaluate_rules` runs after every recorded check run. It looks up active rules for that check (or for any check), reads the metric from the run's detail payload, compares it with `Decimal` arithmetic, and:

- skips the rule when the metric is absent from the run detail (a rule cannot fire on data the probe did not produce);
- skips a silenced rule and records a `rule.suppressed` audit event, so a silence is visible, not invisible;
- dedups on `fingerprint = SHA-256(rule_id:check_id)`: an open/acked alert whose `last_seen` is inside the dedup window gets `count + 1` and a fresh `last_seen`; outside the window, a new alert opens.

The `channel` column on `gov_rules` is always `log`. This is deliberate and load-bearing: there is no send path in the module at all, so "alerts are recorded only" is a property of the code, not a configuration promise.

## 6. Runbooks and incidents

Runbooks follow the P04 versioning shape (name + version, `current`/`superseded`, old rows never edited). The walkthrough harness follows the S01 shape: an injectable clock and injectable `step_work`, per-step elapsed time checked against the step's time box, plus wall-clock elapsed time. The default `step_work` is a no-op — a walkthrough times the harness, not a real procedure; the steps are text a human follows.

Incidents follow the S01 ticket shape but with P05's own lifecycle (no `contained` state — mitigation is the state, containment is a step inside it). The resolution-note rule is the one hard gate in the module: an incident cannot be marked resolved by silence. The timeline is the incident's own table (`gov_incident_events`), separate from the global audit log (`gov_events`), so an incident's story reads in one place.

## 7. Key decisions

1. **The one-line spec, realised as data.** The architecture doc's "health checks, retries, alerting, runbooks" becomes four data tables (checks, policies, rules, runbooks) plus two state machines (alerts, incidents). Nothing in P05 is a hardcoded procedure — every behaviour is a row a caller can create, version, or silence.
2. **Grounded in Q10, S01, and P04.** Backoff shape, dead-letter routing, and "every attempt logged" come from Q10's `delivery.py`; severity routing, timed walkthroughs, and incident tickets come from S01's `netsec.py`; versioning and the audit event table come from P04. P05 adds the probe layer, the status summary, dedup windows, silence rules, and the resolution-note gate — the pieces none of the siblings has.
3. **Deterministic jitter.** Random jitter would make the schedule untestable; zero jitter would make every retry collide. SHA-256 of policy id + attempt gives a stable, bounded, per-attempt offset that the oracle can assert exactly.
4. **Alerts are recorded only — by construction.** No send path exists in the module. This is stated in every doc, on the P05 pages, and in the service module's docstring, because the most dangerous failure of an alerting demo is implying a notification went out when nothing was ever sent.
5. **A run that fires nothing is still a run.** Every probe execution is recorded, including runs that fire no alert and runs whose status is `pass`. A health history that only shows failures is a lie by omission; P05's shows both.
6. **No performance claims.** Timings are recorded per run (`duration_ms`) on fixtures, and the docs report only those measured fixture timings. There is no production system to benchmark against, and none is claimed.
