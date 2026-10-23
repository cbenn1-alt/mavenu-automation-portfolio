# Q01 — Runbook

## Start the app

```bash
cd mavenu-portfolio
python3 run.py                                   # http://localhost:8080/
python3 run.py --port 8123 --db /tmp/q01.db     # custom port / database
```

Environment overrides (all optional; see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MAVENU_DB_PATH` | `./data/mavenu.db` | SQLite file (created on first run) |
| `MAVENU_PORT` | `8080` | HTTP port |
| `MAVENU_IDEMPOTENCY_TTL_HOURS` | `72` | Idempotency-key lifetime |

Migrations (001, 002, 003) apply automatically on startup.

## Run the tests

```bash
.venv/bin/python -m pytest tests/test_urgency_scorer.py \
  tests/test_missed_calls.py tests/test_recovery_queue.py -q   # expect: 89 passed
.venv/bin/python -m pytest tests/ -q                           # expect: 241 passed
```

## Operate the demo

- **Ingest calls:** open `/project_q01` — submit a single event or paste
  CSV. Example CSV:
  ```
  timestamp,caller_id,ring_count,duration_seconds,transcript
  2026-10-23T21:15:00,7015550142,9,0,No heat in the house
  2026-10-23T14:05:00,7015550199,3,0,Looking for a quote
  ```
- **Work the queue:** `/project_q01/queue` — pending calls by priority.
  Open a call, claim it (assign to a person), then log outcomes:
  `attempted → connected → booked` (or `lost`).
- **Dashboard:** `/project_q01/dashboard` — recovery rate, contact rate,
  median time-to-callback, escalation and lag status.
- **API:** `POST /api/missed-calls` (JSON event, optional `Idempotency-Key`
  header), `POST /api/missed-calls/import` (`{"csv": "..."}`),
  `GET /api/missed-calls/queue`, `GET /api/missed-calls/<id>`,
  `POST /api/missed-calls/<id>/claim`, `POST /api/missed-calls/<id>/outcome`,
  `GET /api/missed-calls/dashboard`, `POST /api/missed-calls/sla-sweep`.
- **Logs:** structured JSON lines on stdout; every call event is also a row
  in `call_events` (queryable audit trail).

## Rollback procedure (migration 003)

If the Q01 schema must be removed (bad deploy, schema rework):

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from mavenu.db import get_connection, rollback_migration
conn = get_connection("/path/to/mavenu.db")   # the affected database
print(rollback_migration(conn, "003_missed_calls.sql"))  # True when rolled back
conn.close()
EOF
```

Effects: drops `missed_calls`, `call_events`, `call_idempotency_keys`,
`owner_notifications`; removes the `003_missed_calls.sql` record from
`schema_migrations`. **P01 (`leads`) and P02 (`requests`) tables are not
touched.** Restarting the app re-applies the migration automatically
(idempotent forward path).

This exact procedure is exercised by
`tests/test_missed_calls.py::test_migration_003_down_step_rolls_back_for_real`
(apply → use → roll back → verify P01/P02 intact → re-apply).

### Rollback safety notes

- Rolling back **destroys Q01 data** (call records, outcomes, audit rows).
  Back up the SQLite file first if the data matters:
  `cp data/mavenu.db data/mavenu.db.bak-$(date +%F)`.
- The forward path is idempotent: after a rollback, the next app start
  re-applies 003 on a clean slate.
- `rollback_migration` raises `FileNotFoundError` if the down-step file is
  missing; it returns `False` (no-op) if the migration was never applied.

## Reset the demo

Delete the SQLite file (default `./data/mavenu.db`, git-ignored) and
restart; migrations re-apply automatically.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Address already in use` | Another instance holds the port — use `--port` |
| CSV import shows 0 accepted | Check the header row matches exactly: `timestamp,caller_id,ring_count,duration_seconds,transcript` |
| `409 action_rejected` on outcome | The transition is illegal in the current state (see `/api/missed-calls/<id>` `allowed_transitions`) |
| Stale demo data | Delete the DB file and restart |
