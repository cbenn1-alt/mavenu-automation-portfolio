# Project P05 — Demo

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## Setup (2 minutes)

```bash
cd ~/workspace/mavenu-portfolio
python3 run.py --port 8000 --db /tmp/p05-demo.db
```

## Script

### 1. Seed the demo data

Open `http://localhost:8000/project05` and click **Seed demo data** (or `POST /project05/seed`). The seed inserts 5 checks, 2 policies, 4 rules, 2 runbooks, one run of each check, one demo job, and one demo incident — all invented. Click it again: nothing is inserted twice. The status summary reads **pass**, 0 open alerts, 1 open incident (the demo review incident).

### 2. Run a check — and watch nothing alert

Open the `QUEUE-MISSED-CALLS` check and click **Run check now**. The queue is empty, so the value is 0 and the status is `pass`. The rule `QUEUE-DEPTH-HIGH` (fires above 20) does not fire — a run that fires nothing is still recorded, and the run history shows it.

### 3. Fire an alert — on purpose

The demo has no missed calls, so the queue rule will not fire on its own. Instead, create a rule that fires on the DB check's value (`0`) with operator `lt` and threshold `1`, then re-run `DB-REACHABLE`. The run returns `alerts: [1]` — a low-severity alert is now open. Open `/project05/alerts` and ack it, then resolve it. The alert was **recorded only** — nothing was sent anywhere, and the page says so. (To see the seeded queue rule fire for real, import missed calls through Q01 until more than 20 are pending, then re-run `QUEUE-MISSED-CALLS`.)

### 4. Fail a job twice and watch it dead-letter

On `/project05/jobs`, the demo job `DEMO-WEBHOOK-DELIVERY` is pending under `STANDARD-RETRY` (max 5, base 30 s). Create a job under `FAST-RETRY` (max 3, base 5 s) and report two failures: after the first, the job is `scheduled` with `next_run_at` 5 seconds out; after the second, still scheduled (limit is 3); after the third, it is `dead_lettered` and a dead-letter row appears. Click **Replay**: a fresh job with the same name and payload appears, `pending`, attempts 0 — and the dead-letter row is marked `replayed`.

### 5. Walk an incident through its lifecycle

Open the demo incident ("Demo: weekly governance review") and transition it open → triaged → mitigating. Try to resolve it with an empty note: the form returns an error — resolving requires a resolution note. Fill in "Queue drained; checks pass." and resolve it, then close it, then reopen it. The timeline shows every transition with its actor and timestamp.

### 6. Walk a runbook

Open `RB-CRITICAL` and click **Run walkthrough**. All four steps report elapsed times in microseconds against time boxes of 900 s to 28,800 s — all within timebox. The walkthrough times the steps as written; it does not perform the procedure, and the page does not claim otherwise.

### 7. Try to break the governance layer

Create a check with probe `queue_depth` and params `{"table": "missed_calls; DROP TABLE leads", "value": "pending"}`. It is rejected with `422` at creation, before any SQL is built — and `leads` is still there afterwards. The allow-list is the whole defence, and it is small enough to read in one sitting (`_QUEUE_TABLES` in `src/mavenu/governance.py`).

## Talking points

- Governance is data, not hardcoded procedure: checks, policies, rules, and runbooks are rows you can create, version, and silence.
- Alerts are recorded only — by construction, not by configuration. There is no send path in the module.
- A job that fails is a schedule decision, not a crash: backoff is deterministic, the limit is explicit, and the dead letter is a first-class record with a replay path.
- Resolving an incident requires a note. An incident is not resolved by silence.
