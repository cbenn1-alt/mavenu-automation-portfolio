# Q01 — AI Missed-Call Recovery Engine

**Status: Implemented · Tested** — 89 automated tests, all passing
(241/241 full suite: P01's 51 + P02's 101 + Q01's 89; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Missed-call event ingestion (CSV + JSON webhook shape), server-side validation, deterministic rule-based urgency scoring behind a replaceable `UrgencyScorer` protocol, priority callback queue (score × age decay), claim/assign, per-call outcome tracking (`pending → attempted → connected → booked \| lost`), SLA-escalation sweep, ingestion-lag alert, DB-computed recovery dashboard with reconciliation tests, migration rollback tested for real |
| What is SIMULATED | **Simulated** | The deterministic demo urgency scorer (documented weights — a transparent ruleset, NOT a trained ML model and never described as one). Ingestion is fixture-based: **no telephony integration exists in v1** — this is a processing engine for call *records*. Owner notifications are stubs (a DB row is written; nothing is ever sent). The SLA sweep is triggerable, not scheduled |
| What is SYNTHETIC | **Demo** | Every caller ID, timestamp, transcript, and name in fixtures, tests, and demos is invented. Caller IDs are masked (`••••••0142`) and SHA-256-hashed — the raw number is never stored |
| What is NOT claimed | — | No production deployment. No real users, no real call traffic, no telephony provider integration. **No TCPA-compliance review has been performed** — any real deployment that places callbacks needs telecom counsel first (see SECURITY.md). No platform or employer endorsement |

## Business problem

Home-service businesses (HVAC, plumbing, electrical, roofing) miss calls
while they're on jobs. Most missed callers never leave voicemail and call a
competitor within the hour — revenue leaks silently because there is no
systematic record of *who called, when, and whether anyone called back*.

This project is a working recovery engine: missed-call records are
ingested, scored for urgency by an explainable ruleset, worked through a
prioritized callback queue, tracked to an outcome (`booked` or `lost`), and
measured on a dashboard where every total reconciles to source rows.

## Implemented capabilities

- Event ingestion: CSV batch import (`timestamp, caller_id, ring_count,
  duration_seconds, transcript`) and JSON webhook-shape single events;
  row-level validation with per-row errors (bad rows never abort a batch)
- Duplicate protection two ways: natural dedup key (caller hash + timestamp)
  and client `Idempotency-Key` (header or hidden form field) with replay
- Deterministic urgency scoring: repeat caller +0.25, after-hours +0.15,
  emergency keyword +0.20, service keyword +0.05, voicemail +0.10,
  persistent caller (≥8 rings) +0.10 — every point explained in the reasons
- Priority callback queue: `priority = urgency_score × age decay` (halves
  every 24h); claim/assign to a person without changing state
- Outcome tracking enforced by a code-level state machine; illegal moves
  raise `InvalidTransition`; first-attempt and outcome timestamps stamped
- Failure analysis implemented: repeat-ID anomaly flag (3rd call from one ID
  in 24h is flagged, never auto-trusted), SLA sweep escalates aging
  high-urgency calls to a notification **stub**, ingestion-lag alert stub
- Recovery dashboard: recovery rate (booked/total), contact rate, median
  time-to-callback — all computed from the database, reconciliation asserted
- Migration rollback: `003_missed_calls.down.sql` + `db.rollback_migration()`,
  tested for real (apply → use → roll back → re-apply)

## What is simulated (labeled, not hidden)

- **Urgency scoring**: a deterministic rule engine with documented weights.
  The `UrgencyScorer` protocol is the seam where a real model would plug in;
  nothing here learns or predicts.
- **Ingestion source**: fixture CSV and JSON payloads. There is no
  connection to any phone system, carrier, or VoIP provider.
- **Notifications**: `owner_notifications` rows are stubs (`status =
  'queued-stub'`). The escalation *path* is real and tested; delivery is not.
- **Scheduling**: the SLA sweep runs when triggered
  (`POST /api/missed-calls/sla-sweep`); a real deployment would call it from
  a scheduler (documented in RUNBOOK.md).

## Technology stack

Python 3.12 stdlib (`wsgiref`, `sqlite3`, `hashlib`), pytest (dev only).
Zero runtime dependencies, zero cost, no network calls.

## Quick start

```bash
cd mavenu-portfolio
.venv/bin/python -m pytest tests/test_urgency_scorer.py tests/test_missed_calls.py tests/test_recovery_queue.py -q
# expect: 89 passed
MAVENU_DB_PATH=/tmp/q01-demo.db python3 run.py --port 8123
# open http://localhost:8123/project_q01
```

See DEMO.md for a guided walkthrough and RUNBOOK.md for operations.
