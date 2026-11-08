# Project P04 — Runbook

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Run the app

```bash
cd ~/workspace/mavenu-portfolio
python3 run.py --port 8000 --db data/app.db
```

Migrations (including `022_sqlops`) apply automatically on startup.

## 2. Run the tests

```bash
# P04 only (fast, ~2.5s)
.venv/bin/python -m pytest tests/test_sqlops.py tests/test_sqlops_api.py -q

# Full suite, chunked (the /tmp tmpfs is 512 MB and fills during big runs —
# a 21-file chunk fills it mid-run and produces spurious
# "database or disk is full" sqlite errors; keep chunks to ~8 files)
.venv/bin/python -m pytest tests/test_sqlops.py tests/test_sqlops_api.py \
    tests/test_docintel.py tests/test_docintel_api.py -q
rm -rf /tmp/pytest-of-root
# …then the remaining chunks; see BUILD_LOG.md for the chunk list.
```

Two tests in the full suite currently fail on the pristine tree for a date reason (fixtures were written for 2026-10-23; today is later): `test_reconciliation_api.py::test_aging_endpoint` and `tests/test_estimates_api.py::test_api_cadence_run_queues_due_steps`. Both reproduce via `git stash` with P04 removed. Do not "fix" them by changing other projects — see `TEST_RESULTS.md` §1.

## 3. Operate

| Task | How |
|---|---|
| Seed demo data | Web: `/project04` → **Seed demo data**. API: `POST /project04/seed` (form post). Idempotent — a second seed inserts nothing |
| Create a query | Web: `/project04` → paste a spec JSON → **Save query (v1)**. API: `POST /api/sqlops/queries` with `{"name", "spec", "description", "actor"}` |
| Run a query | Web: `/project04/queries/<id>` → period start/end → **Run**. API: `POST /api/sqlops/queries/<id>/run` with `{"period_start", "period_end", "actor"}` |
| Drill down | Web: `/project04/runs/<id>` → pick a dimension + value → **Drill down**. API: `POST /api/sqlops/runs/<id>/drilldown` with `{"dimension", "value", "actor"}` |
| Snapshot a run | Web: `/project04/runs/<id>` → **Snapshot this result**. API: `POST /api/sqlops/runs/<id>/snapshot`; check with `GET /api/sqlops/snapshots/<id>/status` |
| Compare periods | Web: `/project04/compare` → pick a query + two periods. API: `POST /api/sqlops/compare` with `{"query_id", "period_a": [start, end], "period_b": [start, end], "actor"}` |
| Export a run | `GET /api/sqlops/runs/<id>/export?format=csv` or `?format=json` |
| Supersede a query | Web: `/project04/queries/<id>` → paste a new spec → **Save as vN+1**. API: `POST /api/sqlops/queries/<id>/supersede` with `{"spec", "actor"}` |
| See the history | `/project04/runs` (every execution, including failed ones) or `GET /api/sqlops/runs` |

## 4. Rollback procedure (migration 022)

The migration is reversible. The down-step (`src/mavenu/migrations/022_sqlops.down.sql`) drops all four `sqlops_*` tables.

**Tested rollback (exercised by `test_migration_022_down_step_rolls_back_for_real`):**

```python
from mavenu.db import run_migrations, rollback_migration
run_migrations(conn)          # applies 022, creates the 4 tables
rollback_migration(conn, "022_sqlops")   # drops all 4 tables
```

**Manual rollback** (if the app must be returned to the pre-P04 schema):

1. Stop the app.
2. Back up the database file (`cp data/app.db data/app.db.pre-p04-rollback`).
3. Run the down-step against the database:
   ```bash
   sqlite3 data/app.db < src/mavenu/migrations/022_sqlops.down.sql
   ```
   (The down-step is idempotent — `DROP TABLE IF EXISTS`.)
4. Record the rollback: `DELETE FROM schema_migrations WHERE version = '022_sqlops';`
5. Restart the app and confirm `/project04` is gone (404) and the other projects still render.

**Data loss note:** rollback destroys all saved queries, runs, snapshots, and audit rows. There is no partial rollback. In the demo this is acceptable — all data is synthetic and re-seedable from `seed_demo_data`, and every query spec is re-creatable from its JSON.

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `sqlite3.OperationalError: database or disk is full` | `/tmp` (512 MB tmpfs) filled with pytest debris. `rm -rf /tmp/pytest-of-root` and rerun in smaller chunks. |
| Create query returns `422` | The spec failed validation — read the error message; it names the rule (unknown table/column, bad grain, metric on a text column, filter value outside the enum, too many metrics, …). |
| Run returns `422` with a `run_id` | The run was recorded as `error` — fetch `GET /api/sqlops/runs/<run_id>` and read `error_text` (usually a bad period: start after end, or longer than 366 days). |
| Drill-down returns `422` | The dimension is not one of the run's dimensions (or the grain's `period` bucket) — or it is a column the allow-list does not expose. |
| Snapshot status is `stale` | The underlying data changed since the snapshot — re-run the query and snapshot again. That is the feature working, not a bug. |
| Compare shows `b: null` for a group | The group exists in period A only. Percent change is null by design — no percent is invented for a missing baseline. |
