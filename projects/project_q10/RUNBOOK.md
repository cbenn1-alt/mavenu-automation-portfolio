# Q10 — Webhook Integration Hub: Runbook

## Start the demo

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py          # serves the portfolio hub (see run.py --help)
# open /project_q10 for the dashboard + curl walkthrough,
# /project_q10/dead-letters for the dead-letter queue
```

Zero cost: stdlib only (`wsgiref`, `sqlite3`, `hmac`); no network calls —
stub endpoints are in-process.

## Send a signed event

```bash
BODY='{"source":"demo-form","event_type":"lead.created","event_id":"demo-001","payload":{"name":"Sample Lead","amount":1500}}'
SIG=$(python3 -c "import hmac,hashlib,sys; print('sha256='+hmac.new(b'test-secret-demo-form-001', sys.argv[1].encode(), hashlib.sha256).hexdigest())" "$BODY")
curl -s -X POST http://localhost:8080/api/webhooks/events \
  -H 'Content-Type: application/json' \
  -H "X-Webhook-Signature: $SIG" -d "$BODY" | python3 -m json.tool
```

`test-secret-demo-form-001` is the documented **test-only** secret for the
`demo-form` source (see SECURITY.md — real deployments must use real
secrets from the environment).

## Seed the demo routing rules

Click **"Seed demo routing rules"** on `/project_q10`, or:

```bash
curl -s -X POST http://localhost:8080/api/webhooks/routes/seed
```

Idempotent — already-seeded rules are skipped. The three demo rules:

| Rule | Matches | Actions |
|---|---|---|
| `form-leads-to-crm` | `lead.created` from `demo-form` | log + forward `stub:crm-sink` |
| `bookings-to-calendar` | `booking.created` | transform (booking_ref/when) + forward `stub:calendar-sink` |
| `high-value-leads-to-sheet` | `lead.created` with `payload.amount >= 1000` | log + forward `stub:sheet-sink` |

## Run the delivery loop

Deliveries are attempted when the loop runs (a real deployment would run
this on a scheduler/worker):

```bash
curl -s -X POST http://localhost:8080/api/webhooks/deliver/run | python3 -m json.tool
```

## Dry-run a rule change before it touches anything

```bash
curl -s -X POST http://localhost:8080/api/webhooks/routes/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"source":"demo-form","event_type":"lead.created","event_id":"dry-1","payload":{"amount":5000}}' \
  | python3 -m json.tool
```

Compare `actions` / `would_forward_to` against the intended behavior, then
create the rule via `POST /api/webhooks/routes`.

## Work the dead-letter queue

1. Open `/project_q10/dead-letters` (or `GET /api/webhooks/dead-letters`).
2. Reasons and what they mean:
   - `malformed_envelope` — body couldn't normalize; **inspection only**,
     replay is refused. Fix the sender.
   - `routing_error` — a rule/action raised; fix or disable the rule, then
     replay: `POST /api/webhooks/dead-letters/<id>/replay`.
   - `max_attempts_exceeded` — endpoint failed 5 times; check the endpoint,
     then replay to re-queue (attempts reset, circuit state respected).
   - `unknown_endpoint` — rule forwards to an unregistered endpoint; fix
     the rule's `endpoint` (or register the stub), then replay.

## Incidents

- **Circuit open on an endpoint** (`GET /api/webhooks/endpoints`): the
  endpoint failed 3+ times consecutively. Deliveries are safely queued
  with backoff — nothing is lost. Fix the downstream, wait out the 60s
  cooldown (or replay a dead letter after fixing), and the half-open probe
  will close the circuit on success.
- **Dead-letter growth**: alert threshold is a deployment concern; query
  `SELECT reason, COUNT(*) FROM webhook_dead_letters GROUP BY reason`.
- **Suspected forged webhooks**: rejected attempts are already stored with
  `rejected` lineage — query `webhook_lineage` for `to_state='rejected'`
  grouped by `event_id`/`detail_json`.

## Rollback procedure

The Q10 schema is migration `007_webhook_hub.sql` with a tested down-step
`007_webhook_hub.down.sql`. Rollback drops all 8 Q10 tables
(`webhook_events`, `webhook_lineage`, `webhook_routes`,
`webhook_derived`, `webhook_deliveries`, `webhook_attempts`,
`webhook_dead_letters`, `webhook_endpoint_state`) and removes the
migration record so it can be re-applied later.

```python
from mavenu.db import get_connection, run_migrations, rollback_migration
conn = get_connection("data/mavenu.db")
rollback_migration(conn, "007_webhook_hub.sql")  # True when rolled back
conn.close()
```

```bash
# re-apply later (e.g. after fixing a bad migration edit):
.venv/bin/python -c "
from mavenu.db import get_connection, run_migrations
import sys; sys.path.insert(0, 'src')
conn = get_connection('data/mavenu.db')
print(run_migrations(conn))
"
```

**Tested for real** 2026-10-23
(`test_migration_007_down_step_rolls_back_for_real`): tables dropped,
record removed, re-apply returns `["007_webhook_hub.sql"]` with all 8
tables back. Application code rollback: `git log`/`git show` the Q10
commit; the service modules are additive (`webhooks.py`, `router.py`,
`delivery.py`) and `web.py` additions are a self-contained section —
revert the commit to remove the feature without touching P01–Q04.

**Data-loss note:** rollback destroys Q10 demo data (events, lineage,
dead letters). This is synthetic demo data by design; a real deployment
must snapshot the SQLite file before rolling back.
