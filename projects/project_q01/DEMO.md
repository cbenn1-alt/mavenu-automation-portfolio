# Q01 — Demo Script

A 5-minute guided walkthrough. All data is synthetic. Start the app:

```bash
cd mavenu-portfolio
MAVENU_DB_PATH=/tmp/q01-demo.db python3 run.py --port 8123
```

## 1. Ingest a batch of missed calls (1 min)

Open `http://localhost:8123/project_q01`. Paste this CSV and import:

```
timestamp,caller_id,ring_count,duration_seconds,transcript
2026-10-23T21:15:00,7015550142,9,0,No heat in the house since last night
2026-10-23T14:05:00,7015550199,3,0,Looking for a quote on a new furnace
2026-10-23T09:40:00,7015550117,11,0,
```

Narrate: "Three missed calls. The first is after-hours, waited 9 rings,
and left a voicemail saying 'no heat' — the scorer gives it 0.75 with
every point explained. The second is a daytime quote request at 0.35.
The third waited 11 rings but said nothing: 0.30. Nobody's phone number
is stored raw — the queue shows `••••••0142`."

## 2. Work the priority queue (2 min)

Open `/project_q01/queue`. Point out the ordering: urgency × age decay,
so the after-hours no-heat call sits on top.

Open the top call, claim it ("Assign to: Rosa"), then log outcomes in
order: `attempted → connected → booked`. Narrate each step:

- "Claiming assigns a human without changing state — it's in the audit
  trail as `call.claimed`."
- "Each outcome is a state-machine transition. Try jumping
  `pending → booked` on another call — the system rejects it with a 409.
  Callbacks happen in order, on the record."

## 3. Show the failure analysis (1 min)

Ingest this row twice to show dedup:

```
2026-10-23T21:15:00,7015550142,9,0,No heat in the house since last night
```

"The duplicate is detected — same caller, same timestamp — no second
row, and the audit trail records `call.duplicate_received`."

Then hit the SLA sweep: `POST /api/missed-calls/sla-sweep` (or via the
test). "Any high-urgency call still pending past the 2-hour SLA gets
escalated and an owner-notification **stub** is queued — a database row,
not a sent message. The sweep is idempotent: run it twice, one stub."

## 4. Close on the dashboard (1 min)

Open `/project_q01/dashboard`: "Recovery rate — what fraction of missed
calls turned into booked jobs. Median time-to-callback. Every number is
computed from the database, and the test suite re-computes them with
independent SQL to prove they reconcile."

## Talking points for the honest-status questions

- "The urgency scorer is a **ruleset, not a model** — the weights are on
  the screen and the protocol is replaceable."
- "There is **no telephony integration** — this processes call records.
  A real deployment plugs a provider's webhook into `POST
  /api/missed-calls`."
- "**No TCPA review** has been done — real deployments need telecom
  counsel before placing callbacks. That's documented in SECURITY.md."
