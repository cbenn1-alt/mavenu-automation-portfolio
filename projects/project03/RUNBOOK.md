# Project P03 — Runbook

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Run the app

```bash
cd ~/workspace/mavenu-portfolio
python3 run.py --port 8000 --db data/app.db
```

Migrations (including `021_docintel`) apply automatically on startup.

## 2. Run the tests

```bash
# P03 only (fast, ~2s)
.venv/bin/python -m pytest tests/test_docintel.py tests/test_docintel_api.py -q

# Full suite, chunked (the /tmp tmpfs is 512 MB and fills during big runs)
.venv/bin/python -m pytest tests/test_docintel.py tests/test_docintel_api.py \
    tests/test_reconciliation.py tests/test_reconciliation_api.py -q
rm -rf /tmp/pytest-of-root
# …then the remaining chunks; see BUILD_LOG.md for the chunk list.
```

Two tests in the full suite currently fail on the pristine tree for a date reason (fixtures were written for 2026-10-23; today is later): `test_reconciliation_api.py::test_aging_endpoint` and `tests/test_estimates_api.py::test_api_cadence_run_queues_due_steps`. Both reproduce via `git stash` with P03 removed. Do not "fix" them by changing other projects — see `TEST_RESULTS.md` §1.

## 3. Operate

| Task | How |
|---|---|
| Upload documents | Web: `/project03` → paste JSON/CSV → Upload. API: `POST /api/docintel/upload` with `{"format": "json" \| "csv", "payload": "<text>", "actor": "<name>"}` |
| Run extraction | Web: `/project03` → Extract. API: `POST /api/docintel/extract` with `{"actor": "<name>"}` |
| Review a document | `/project03/documents/<doc_id>` — Accept / Correct / Reject per field; Reject document |
| Work the exception queue | `/project03/exceptions` — filter by kind/state; open an exception to see history and the suggested next action; transition `open → investigating → resolved \| written_off` |
| See the numbers | `/project03/reports` or `GET /api/docintel/summary` |

## 4. Rollback procedure (migration 021)

The migration is reversible. The down-step (`src/mavenu/migrations/021_docintel.down.sql`) drops all seven `docintel_*` tables.

**Tested rollback (exercised by `test_migration_021_down_step_rolls_back_for_real`):**

```python
from mavenu.db import run_migrations, rollback_migration
run_migrations(conn)          # applies 021, creates the 7 tables
rollback_migration(conn, "021_docintel")   # drops all 7 tables
```

**Manual rollback** (if the app must be returned to the pre-P03 schema):

1. Stop the app.
2. Back up the database file (`cp data/app.db data/app.db.pre-p03-rollback`).
3. Run the down-step against the database:
   ```bash
   sqlite3 data/app.db < src/mavenu/migrations/021_docintel.down.sql
   ```
   (The down-step is idempotent — `DROP TABLE IF EXISTS`.)
4. Record the rollback: `DELETE FROM schema_migrations WHERE version = '021_docintel';`
5. Restart the app and confirm `/project03` is gone (404) and the other projects still render.

**Data loss note:** rollback destroys all ingested documents, fields, exceptions, and audit rows. There is no partial rollback. In the demo this is acceptable — all data is synthetic and re-ingestible from the fixture in `tests/test_docintel.py`.

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `sqlite3.OperationalError: database or disk is full` | `/tmp` (512 MB tmpfs) filled with pytest debris. `rm -rf /tmp/pytest-of-root` and rerun. |
| Upload returns `422` | Payload is not a JSON list / CSV with the three columns, or `format` is not `json`/`csv`. Check the `errors` array in the response. |
| Field review returns `409` | The action is illegal for the field's current status (e.g. accepting a missing field, correcting a locked accepted field with no open validation exception). Read the error message — it names the rule. |
| Document stays `needs_review` after all fields look fine | An open `validation_failed` exception blocks acceptance, or a field is `rejected`. Resolve the exception (correct the field, or transition it) or reject the document. |
