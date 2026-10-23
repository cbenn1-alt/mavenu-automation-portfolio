# Project 01 — Runbook

## Start the app

```bash
cd mavenu-portfolio
python3 run.py                 # http://localhost:8080/
python3 run.py --port 8123 --db /tmp/demo.db   # custom port / database
```

Environment overrides (all optional; see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MAVENU_DB_PATH` | `./data/mavenu.db` | SQLite file (created on first run) |
| `MAVENU_PORT` | `8080` | HTTP port |
| `MAVENU_IDEMPOTENCY_TTL_HOURS` | `72` | Idempotency-key lifetime |
| `MAVENU_REVIEW_CONFIDENCE_THRESHOLD` | `0.65` | Below this → human review |
| `MAVENU_LOG_LEVEL` | `INFO` | Log verbosity |

## Run the tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q     # expect: 51 passed
```

## Operate the demo

- **Submit a lead:** open `/project01`, fill the form, submit. Strong
  contact details → `booked`. Thin details → `needs_review`.
- **Review queue:** open a lead in `needs_review`, use the reviewer form to
  move it to `qualified` / `rejected`, with your name as actor.
- **Dashboard:** `/project01/dashboard` — counts by state + recent leads.
- **API:** `POST /api/leads` (JSON, optional `Idempotency-Key` header),
  `GET /api/stats`, `GET /api/leads/<id>`,
  `POST /api/leads/<id>/transition` with `{"to_state": "...", "actor": "..."}`.
- **Logs:** structured JSON lines on stdout; every lead event is also a row
  in `lead_events` (queryable audit trail).

## Reset the demo

Delete the SQLite file (default `./data/mavenu.db`, git-ignored) and restart;
migrations re-apply automatically.

## Failure drill (for the reviewer)

1. In `src/mavenu/web.py`, the app wires `FakeBookingAdapter()`. To simulate
   an outage, a test already does it — or run:
   `.venv/bin/python -m pytest tests/test_leads.py::test_booking_failure_preserves_lead_in_review -q`
2. Observe: the lead lands in `needs_review`, a `lead.booking_failed` event
   records the error, and the lead record is intact.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Address already in use` | Another instance holds the port — use `--port` |
| Tests fail on first run | Ensure the venv install completed: `.venv/bin/pip install -r requirements-dev.txt` |
| Stale demo data | Delete the DB file and restart |
