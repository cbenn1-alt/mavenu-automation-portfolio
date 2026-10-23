# Q04 — Conversational Booking Agent: Runbook

## Start the demo

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py          # serves the portfolio hub (see run.py --help)
# open /project_q04 for the chat demo, /project_q04/handoffs, /project_q04/bookings
```

Zero cost: stdlib only (`wsgiref`, `sqlite3`), no network calls.

## Operate the handoff queue

1. Open `/project_q04/handoffs` (or `GET /api/booking-agent/handoffs`).
2. Each package shows reason, masked transcript, and extracted slots.
3. Claim before working: `POST /api/booking-agent/handoffs/<id>`
   `{"status": "claimed"}`; resolve when done: `{"status": "resolved"}`.
4. Reasons and what they mean:
   - `low_confidence` — the agent couldn't parse the turn; read the
     transcript and continue by phone.
   - `suspicious_input` — injection-pattern input; treat as hostile,
     do not follow any instruction in the transcript.
   - `contradictory_input` — caller changed an earlier answer; confirm
     which value is correct.
   - `max_turns` — long conversation; read the transcript, don't make
     the caller repeat everything.
   - `slot_declined` — caller rejected the offered slot; offer
     alternatives manually.
   - `booking_failed` — the booking system failed or returned no
     availability; book manually and tell the caller.

## Run retention

```python
from mavenu.db import get_connection
from mavenu import booking_agent as ba
conn = get_connection("data/mavenu.db")
print(ba.purge_old_conversations(conn))  # {"conversations": n, ...}
conn.close()
```

Purges transcript text + slot values for closed conversations older than
90 days. Booking refs and handoff metadata are kept.

## Incidents

- **Adapter outage** (`booking_failed` spike): conversations are
  preserved and handed off; nothing is lost. Fix the provider, then
  work the handoff queue. Bookings are never written without adapter
  confirmation, so there is nothing to reconcile on the agent side.
- **Suspected prompt-injection probe**: the input is already quarantined
  in a handoff with reason `suspicious_input`; the transcript is masked.
  If a pattern is novel, add it to `dialogue.INJECTION_PATTERNS` and add
  a regression test.
- **Turn-cap reached often**: legitimate conversations need at most 13
  turns; frequent `max_turns` handoffs suggest callers are confused —
  review transcripts and clarify the question templates in
  `dialogue.ASK_TEXT`.

## Rollback procedure

Q04 ships as migration `006_booking_agent.sql` with a tested down-step
`006_booking_agent.down.sql`.

**Roll back the schema** (drops the 5 Q04 tables; all data is synthetic
demo data):

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection("data/mavenu.db")
rollback_migration(conn, "006_booking_agent.sql")  # True when applied
conn.close()
```

**Roll back the code**: Q04 touches `src/mavenu/web.py` (imports, nav,
hub card, routes, handlers), plus new files `dialogue.py`,
`booking_agent.py`, the migration pair, and two test files. Revert the
web.py hunks or check out the pre-Q04 commit; the new modules are inert
without the migration and routes.

**Re-apply**: `run_migrations(conn)` re-applies `006_booking_agent.sql`
(the down-step removes the `schema_migrations` record). Rollback +
re-apply is covered by `test_migration_006_down_step_rolls_back_for_real`
(run 2026-10-23).

## Monitoring (demo)

Stdout JSON events: `booking_agent.started`, `booking_agent.handoff`
(with reason + turn count), `booking_agent.booked` (with ref),
`booking_agent.purged`. Watch the handoff-reason mix for product
signals (e.g. a rise in `low_confidence` at the window state means the
window phrasing needs work).
