# Q02 — Demo Script

A guided walkthrough (~5 minutes). Everything below uses synthetic
fixtures; nothing is sent anywhere. Suggested talking points are in
*italics*.

## Setup

```bash
cd mavenu-portfolio
MAVENU_DB_PATH=/tmp/q02-demo.db python3 run.py --port 8124
# open http://localhost:8124/project_q02
```

## 1. The problem (30s)

*"Estimates go out and die in inboxes. The techs are on roofs, not doing
follow-up, and the owner can't see what's aging or why deals were lost.
This project gives every estimate a visible life."*

## 2. Create an estimate (60s)

On `/project_q02`, fill in: customer "Acme Test Co", service "hvac",
estimator "Rosa", amount "1250.00". Submit → redirected to the detail
page showing state **draft**.

*"Server-side validation runs on every field. Submitting twice with the
same idempotency key returns the original — no duplicate."*

## 3. Walk the lifecycle (60s)

On the detail page, move the estimate **draft → sent**. The allowed
transitions update; try jumping draft → accepted on a second estimate and
watch it fail.

*"Fifteen legal moves, thirty-four illegal ones — every illegal move is
rejected by the state machine, and the rejection is tested. Each move is
timestamped, actor-stamped, and audit-logged."*

## 4. Run the cadence (90s)

The estimate was just sent, so nothing is due yet. Via the API with a
frozen clock you can see the real behavior — or simpler: on the detail
page, note the outbox section is empty, then hit **Run cadence now** on
the outbox page.

*"The scheduler computes which steps are due from the rules — day 2, 7,
14 — renders the versioned template, and queues exactly one outbox row
per (estimate, step). Run it again: nothing new is queued. We replayed it
1,001 times in tests with zero duplicates."*

Open an outbox row's rendered body: the amount, name, and estimator are
substituted; the footer says plainly that nothing was sent.

## 5. Decline with a reason (45s)

Move the estimate **sent → declined**, picking reason `price`. Watch the
win/loss report at `/project_q02/reports` pick it up under decline
reasons.

*"Declining requires a reason from a closed set — that's what makes the
win/loss report groupable instead of a pile of free text."*

## 6. Reports (45s)

`/project_q02/reports`: aging buckets by days since sent, win rate by
service type and estimator, follow-up effectiveness.

*"Every total is computed from the database, and the tests reconcile each
report against an independent SQL re-computation — zero unexplained
deltas."*

## 7. The honest close (30s)

*"What you saw is real: the state machine, the cadence computation, the
idempotent outbox, the audit trail. What you didn't see is also labeled:
v1 sends nothing — the adapter is a stub, and the outbox is not a mail
server. The automation is the cadence computation and the audit trail.
Before any real deployment sends a message, it needs telecom counsel —
that's documented, not hand-waved."*

## API-only path (for reviewers who prefer curl)

```bash
# create
curl -X POST localhost:8124/api/estimates -H 'Content-Type: application/json' \
  -d '{"customer_name":"Acme Test Co","service_type":"hvac","estimator":"Rosa","amount_cents":125000}'
# lifecycle
curl -X POST localhost:8124/api/estimates/EST-000001/transition \
  -H 'Content-Type: application/json' -d '{"to_state":"sent","actor":"demo"}'
# cadence + outbox + flush
curl -X POST localhost:8124/api/cadence/run
curl localhost:8124/api/estimates/outbox
curl -X POST localhost:8124/api/cadence/flush
# reports
curl localhost:8124/api/estimates/reports/aging
curl localhost:8124/api/estimates/reports/win-loss
curl localhost:8124/api/estimates/reports/effectiveness
# template validation gate
curl -X POST localhost:8124/api/estimate-templates/followup_step1/test-send \
  -H 'Content-Type: application/json' \
  -d '{"context": {"estimate_id":"EST-000001","customer_name":"Acme Test Co","service_type":"hvac","amount":"$1,250.00","estimator":"Rosa"}}'
```
