# Q07 — Runbook

## Prerequisites

- Repo at `~/workspace/mavenu-portfolio`, venv at `.venv` (`bin/python`, `bin/pytest`).
- Python 3.12, stdlib only at runtime. $0 spend, no network calls.

## Start the app

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py        # serves the WSGI app (default port 8080)
```

Open `/project_q07`.

## Normal operation

1. **Register a location** — `/project_q07/locations` (or
   `POST /api/kpi/locations`): code, name, schema version, and the JSON
   schema map (canonical field → the location's CSV column). All six
   canonical fields required: `job_id, completed_date, revenue, costs,
   is_callback, tech_days`.
2. **Upload a CSV** — `/project_q07` upload form (or
   `POST /api/kpi/upload` with `location_code`, `period` (`YYYY-MM`),
   `csv`). Re-uploading the same file is a safe no-op.
3. **Compute** — `/project_q07` compute form (or `POST /api/kpi/compute`
   with `period`). Computes per-location KPIs and the rollup.
4. **Review** — `/project_q07/kpi?period=YYYY-MM` dashboard; click
   "drill down" on any value to see its source rows.
5. **Triage** — `/project_q07/quarantine`: bad rows with reasons,
   schema-drift alerts (resolve when handled).

## Schema drift procedure

- **Unknown column alert**: the column's values are held in quarantine
  (column-level entry, reason `unknown_column:<name>`); good rows already
  flowed. Decide: (a) the column is junk — resolve the alert; (b) the
  column matters — register a new schema version mapping it (canonical
  fields can't change, so extend downstream handling first), then resolve.
- **Missing mapped column alert**: the whole batch is quarantined with
  `missing_mapped_column:<cols>` and nothing was staged. Fix the CSV or
  register a corrected schema version, re-upload (new batch), resolve.

## Restatement procedure (KPI definition change)

1. `POST /api/kpi/definitions` with `name`, `new_version`, `formula`,
   `includes`, `excludes` — supersedes the old version (never edits it).
2. `POST /api/kpi/restate` with `period` and a **reason** (required).
   Old values are preserved (status `superseded`, linked to the restatement
   row); new values are recomputed with full lineage.
3. Review `/project_q07/restatements` and spot-check one drill-down.

## Rollback procedure

Rolls back migration `010_kpi_rollup.sql` using its down-step. **This
deletes all Q07 data** (locations, maps, staged rows, quarantine, alerts,
definitions, values, lineage, restatements, events). Do not run it against
a database whose Q07 records you need to keep.

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python - <<'EOF'
from mavenu.db import get_connection, rollback_migration, run_migrations
conn = get_connection("src/mavenu/data/mavenu.db")  # or $MAVENU_DB_PATH
print("rolled back:", rollback_migration(conn, "010_kpi_rollup.sql"))
conn.close()
EOF
```

To re-apply: `run_migrations(conn)` (or just restart the app — it runs
pending migrations on boot). The rollback path is tested for real in
`tests/test_kpi_rollup.py::test_migration_010_down_step_rolls_back_for_real`
(apply → use → roll back → verify other tables intact → re-apply).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Unknown or inactive location` on upload | register the location first (`/project_q07/locations`) |
| `period must be 'YYYY-MM'` | use e.g. `2026-09` |
| Upload stages 0 rows, all quarantined | open `/project_q07/quarantine` — the reason column says why (usually `missing_mapped_column` = schema drift) |
| KPI shows `n/a` | formula undefined for the inputs (e.g. gross margin with zero revenue) — by design, not an error |
| Restate says 0 restatements | no definition changed since values were computed — values were recomputed in place under the same definition |
