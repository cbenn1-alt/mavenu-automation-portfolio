# Project 02 — Runbook

## Start the app

```bash
cd mavenu-portfolio
python3 run.py                 # http://localhost:8080/
python3 run.py --port 8137 --db /tmp/p02-demo.db   # isolated demo database
```

Environment overrides (all optional; see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MAVENU_DB_PATH` | `./data/mavenu.db` | SQLite file (created on first run) |
| `MAVENU_PORT` | `8080` | HTTP port |
| `MAVENU_IDEMPOTENCY_TTL_HOURS` | `72` | Idempotency-key lifetime |
| `MAVENU_FINANCE_THRESHOLD_CENTS` | `100000` | Amount above which `finance` joins the chain ($1,000) |
| `MAVENU_APPROVAL_SLA_HOURS` | `48` | Hours before a pending step escalates to `director` |
| `MAVENU_LOG_LEVEL` | `INFO` | Log verbosity |

## Run the tests

```bash
.venv/bin/python -m pytest tests/ -q     # expect: 152 passed
.venv/bin/python -m pytest tests/test_approval_workflow.py tests/test_request_validation.py tests/test_approval_service.py tests/test_requests_api.py -q  # P02 only: 101 passed
```

## Operate the demo

- **Submit a request:** open `/project02`, fill the form, submit → lands in
  `draft`. Use the detail page's "Submit for approval" to route it.
- **Approve:** on the request detail page, pick your role (must match the
  pending step — try the wrong role to see the rejection) and record a
  decision.
- **Force an escalation:** start the server with
  `MAVENU_APPROVAL_SLA_HOURS=0`, submit a request, then
  `POST /api/requests/sla-sweep` — the request escalates to `director`
  immediately.
- **Schedule the sweep (ops step):** in a real deployment, call the sweep
  endpoint on a schedule, e.g.:
  `*/15 * * * * curl -s -X POST http://localhost:8080/api/requests/sla-sweep`
- **Dashboard:** `/project02/dashboard` — counts by state and type,
  SLA-breach and escalation counts, pending steps by deadline.
- **API:** `POST /api/requests` (JSON, optional `Idempotency-Key` header),
  `POST /api/requests/<id>/submit`, `.../decision`
  (`{"decision","role","actor"}`), `.../resubmit`, `.../cancel`,
  `.../fulfill`, `GET /api/requests/<id>`,
  `POST /api/requests/sla-sweep`.
- **Logs:** structured JSON lines on stdout; every request event is also a
  row in `request_events` (queryable audit trail).

## Reset the demo

Delete the SQLite file (default `./data/mavenu.db`, git-ignored) and restart;
migrations re-apply automatically.

## Rollback procedure

Two supported rollback paths, both tested or testable:

### A. Migration down-step (tested 2026-10-23)

Removes Project 02's schema while leaving Project 01 intact:

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from mavenu.db import get_connection, rollback_migration
conn = get_connection("./data/mavenu.db")
print("rolled back:", rollback_migration(conn, "002_approvals.sql"))
conn.close()
EOF
# Restart the app; run_migrations() re-applies 002 on next start,
# or re-apply deliberately: run_migrations() returns ["002_approvals.sql"].
```

Automated coverage:
`tests/test_approval_service.py::test_migration_down_step_rolls_back_002`
runs this for real (apply → use → roll back → re-apply) — **passed
2026-10-23** (Python 3.12.3, pytest 9.1.1, Linux). See TEST_RESULTS.md.

### B. Config revert (no schema change)

If a bad threshold or SLA value causes misbehavior, revert without
touching the database:

```bash
unset MAVENU_FINANCE_THRESHOLD_CENTS MAVENU_APPROVAL_SLA_HOURS
# restart the app; defaults (100000¢ / 48h) take effect immediately.
# In-flight chains keep the chain built at submit time; only new
# submissions and new SLA deadlines use the reverted values.
```

Config revert is the preferred first step for behavior issues; use the
migration down-step only when the P02 schema itself must go.

## Failure drill (for the reviewer)

1. Submit a request and approve it as the wrong role via the API — observe
   the 409 and that the state did not change.
2. Run the suite's escalation test with a visible clock:
   `.venv/bin/python -m pytest tests/test_approval_service.py -q -k "sla or escalat"`
3. Run the rollback test:
   `.venv/bin/python -m pytest tests/test_approval_service.py::test_migration_down_step_rolls_back_002 -q`

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Address already in use` | Another instance holds the port — use `--port` |
| Decision returns 409 `decision_rejected` | Role does not own the current step — check the chain on the detail page |
| Sweep escalates nothing | No `in_review` request is past its `sla_due_at`; check `/project02/dashboard` SLA watch |
| Tests fail on first run | Ensure the venv install completed: `.venv/bin/pip install -r requirements-dev.txt` |
| Stale demo data | Delete the DB file and restart |
