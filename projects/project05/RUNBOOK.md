# Project P05 — Runbook

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Run the app

```bash
cd ~/workspace/mavenu-portfolio
python3 run.py --port 8000 --db data/app.db
```

Migrations (including `023_governance`) apply automatically on startup.

## 2. Run the tests

```bash
# P05 only (fast, ~1.6s)
.venv/bin/python -m pytest tests/test_governance.py tests/test_governance_api.py -q

# Full suite, chunked (the /tmp tmpfs is 512 MB and fills during big runs —
# a 21-file chunk fills it mid-run and produces spurious
# "database or disk is full" sqlite errors; keep chunks to ~8 files)
.venv/bin/python -m pytest tests/test_governance.py tests/test_governance_api.py \
    tests/test_sqlops.py tests/test_sqlops_api.py -q
rm -rf /tmp/pytest-of-root
# …then the remaining chunks; see BUILD_LOG.md for the chunk list.
```

Two tests in the full suite currently fail on the pristine tree for a date reason (fixtures were written for 2026-10-23; today is later): `test_reconciliation_api.py::test_aging_endpoint` and `tests/test_estimates_api.py::test_api_cadence_run_queues_due_steps`. Both reproduce via `git stash` with P05 removed. Do not "fix" them by changing other projects — see `TEST_RESULTS.md` §1.

## 3. Operate

| Task | How |
|---|---|
| Seed demo data | Web: `/project05` → **Seed demo data**. API: `POST /api/governance/seed` (JSON, `{}`). Idempotent — a second seed inserts nothing |
| See overall health | Web: `/project05` (overall status + open counts). API: `GET /api/governance/status` |
| Run a check | Web: `/project05/checks/<id>` → **Run check now**. API: `POST /api/governance/checks/<id>/run` (JSON, `{}`) — the response includes the alert ids fired by the run |
| Create a check | Web: `/project05/checks` → form. API: `POST /api/governance/checks` with `{"name", "subsystem", "kind", "probe", "params", "warn_threshold", "fail_threshold", "description", "actor"}` |
| Create a policy | Web: `/project05/policies` → form. API: `POST /api/governance/policies` with `{"name", "max_attempts", "backoff_base_s", "backoff_cap_s", "jitter_max_s", "dead_letter_after", "description", "actor"}` |
| Supersede a policy | Web: `/project05/policies` → supersede form. API: `POST /api/governance/policies/<id>/supersede` with the new field values. Existing jobs keep the version they were created with |
| Create a job | Web: `/project05/jobs` → form. API: `POST /api/governance/jobs` with `{"name", "policy_id", "payload", "actor"}` |
| Report an attempt | Web: `/project05/jobs` → per-row Attempt form (outcome + error). API: `POST /api/governance/jobs/<id>/attempt` with `{"outcome": "success" \| "failure", "error", "actor"}` |
| Replay a dead letter | Web: `/project05/jobs` → per-row Replay button. API: `POST /api/governance/dead-letters/<id>/replay` — returns the fresh job (201) |
| Create a rule | Web: `/project05/rules` → form. API: `POST /api/governance/rules` with `{"name", "check_name", "metric", "operator", "threshold", "severity", "owner", "dedup_window_s", "actor"}` |
| Silence a rule | Web: `/project05/rules` → per-row Silence form (ISO timestamp). API: `POST /api/governance/rules/<id>/silence` with `{"until", "actor"}` |
| Ack / resolve an alert | Web: `/project05/alerts` → per-row Ack / Resolve buttons. API: `POST /api/governance/alerts/<id>/ack` or `/resolve` |
| Open an incident | Web: `/project05/incidents` → form. API: `POST /api/governance/incidents` with `{"title", "severity", "source_alert_id", "actor"}` |
| Transition an incident | Web: `/project05/incidents/<id>` → transition form (note required to resolve). API: `POST /api/governance/incidents/<id>/transition` with `{"to_status", "note", "actor"}` |
| Add an incident note | Web: `/project05/incidents/<id>` → note form. API: `POST /api/governance/incidents/<id>/notes` with `{"note", "actor"}` |
| Create / supersede a runbook | Web: `/project05/runbooks` → form; detail page → supersede form. API: `POST /api/governance/runbooks` / `POST /api/governance/runbooks/<id>/supersede` with `{"name", "alert_key", "steps", "actor"}` |
| Walk a runbook | Web: `/project05/runbooks/<id>` → **Run walkthrough**. API: `POST /api/governance/runbooks/<id>/walkthrough` |

## 4. Rollback procedure (migration 023)

The migration is reversible. The down-step (`src/mavenu/migrations/023_governance.down.sql`) drops all eleven `gov_*` tables.

**Tested rollback (exercised by `test_migration_023_down_step_rolls_back_for_real`):**

```python
from mavenu.db import run_migrations, rollback_migration
run_migrations(conn)          # applies 023, creates the 11 tables
rollback_migration(conn, "023_governance")   # drops all 11 tables
```

**Manual rollback** (if the app must be returned to the pre-P05 schema):

1. Stop the app.
2. Back up the database file (`cp data/app.db data/app.db.pre-p05-rollback`).
3. Run the down-step against the database:
   ```bash
   sqlite3 data/app.db < src/mavenu/migrations/023_governance.down.sql
   ```
   (The down-step is idempotent — `DROP TABLE IF EXISTS`.)
4. Record the rollback: `DELETE FROM schema_migrations WHERE version = '023_governance.sql';`
5. Restart the app and confirm `/project05` is gone (404) and the other projects still render.

**Data loss note:** rollback destroys all checks, runs, policies, jobs, dead letters, rules, alerts, runbooks, incidents, and audit rows. There is no partial rollback. In the demo this is acceptable — all data is synthetic and re-seedable from `seed_demo_data`, and every definition is re-creatable from its JSON.

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `sqlite3.OperationalError: database or disk is full` | `/tmp` (512 MB tmpfs) filled with pytest debris. `rm -rf /tmp/pytest-of-root` and rerun in smaller chunks. |
| Create check returns `422` | The check failed validation — read the error message; it names the rule (unknown probe/subsystem, unknown queue table/value, bad name, warn > fail, duplicate name). |
| Run a check returns `404` | No check with that id — list `GET /api/governance/checks` first. |
| Job attempt returns `422` | The job is terminal (`succeeded`/`dead_lettered`) or the outcome is not `success`/`failure`. Terminal jobs are never attempted again — replay the dead letter instead. |
| Incident transition returns `422` | Either the transition is illegal in the lifecycle (e.g. open → closed, or a self-transition), or resolving without a resolution note. Read the error message. |
| Alert never fires | Check the rule's metric name against the run's detail payload (a rule cannot fire on a metric the probe did not produce), the operator/threshold, and whether the rule is silenced. |
| Status summary says `unknown` | A check has never run — run it once from its detail page or via the API. |
| Walkthrough step is "OVER" its time box | The step's `timebox_s` is smaller than the work took (with the default no-op work this means the box is unreasonably small, or the clock was injected with a large jump in a test). Widen the box in a superseded runbook version. |
