# Q01 — Architecture

## Shape

Q01 reuses P01's proven shape (intake → validation → scoring → state
machine → SQLite → dashboard), replacing lead qualification with
missed-call urgency scoring and recovery tracking:

```
        ┌──────────────┐
        │  HTML form   │  /project_q01  (single event + CSV paste)
        │  JSON API    │  POST /api/missed-calls · POST /api/missed-calls/import
        └──────┬───────┘
               ▼
  ┌─────────────────────────┐
  │ normalize_event()       │  timestamp, caller_id, ring_count,
  │ (server-side only)      │  duration_seconds, transcript
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ dedup + idempotency     │  natural dedup key (hash+timestamp);
  │ (no duplicate rows)     │  client Idempotency-Key → replay
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ caller-ID privacy       │  store masked (••••••0142) + SHA-256 hash;
  │ mask + hash             │  raw number never touches the DB
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ DeterministicDemoScorer │  UrgencyScorer protocol; documented weights;
  │ (rules, not a model)    │  reasons + flags stored on the call
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ priority_queue()        │  pending only; priority = urgency × age decay
  │ claim_call()            │  (halves every 24h); assign without state change
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ log_outcome()           │  CALL_WORKFLOW.enforced: pending→attempted→
  │                         │  connected→booked|lost; attempts/outcomes stamped
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ sweep_sla() /           │  escalation stubs + ingestion-lag alert
  │ ingestion_lag_report()  │
  └───────────┬─────────────┘
               ▼
  ┌─────────────────────────┐
  │ dashboard_stats()       │  recovery rate, contact rate, median TTCB;
  │ /project_q01/dashboard  │  every total reconciles to source rows
  └─────────────────────────┘
```

Every arrow that changes state goes through `CALL_WORKFLOW.check()`
first; every state change writes a `call_events` row and prints a JSON log
line.

## Modules

| Module | Responsibility |
|---|---|
| `src/mavenu/urgency.py` | `UrgencyScorer` protocol; `DeterministicDemoScorer` (documented weights, pure function); `is_after_hours()`; keyword lexicons |
| `src/mavenu/missed_calls.py` | `normalize_event`, `ingest_event`, `ingest_csv`, `ingest_with_idempotency`, `mask_caller_id`, `hash_caller_id`, `priority_queue`, `claim_call`, `log_outcome`, `sweep_sla`, `ingestion_lag_report`, `dashboard_stats`, call-scoped audit writer |
| `src/mavenu/workflow.py` | `CALL_TRANSITIONS` / `CALL_WORKFLOW` — the single source of truth for legal call transitions; `InvalidTransition` |
| `src/mavenu/migrations/003_missed_calls.sql` | `missed_calls`, `call_events`, `call_idempotency_keys`, `owner_notifications` (stub) |
| `src/mavenu/migrations/003_missed_calls.down.sql` | Rollback: drops the four Q01 tables |
| `src/mavenu/web.py` | `/project_q01*` pages, `/api/missed-calls*` endpoints; domain errors mapped to 404/409/422 envelopes |

## Schema (003)

- `missed_calls`: `public_id` (MC-000001…), `missed_at`, `caller_id_masked`,
  `caller_id_hash`, `ring_count`, `duration_seconds`, `transcript` (capped),
  `urgency_score` + `urgency_reasons` (JSON) + `urgency_scorer`,
  `flags` (JSON), `state` (CHECK constraint), `assigned_to`,
  `escalated`, `source`, `dedup_key` (UNIQUE), `attempted_at`,
  `outcome_at`, `created_at`, `updated_at`. Indexes on state, hash,
  missed_at, (state, urgency_score).
- `call_events`: append-only audit (`call_id`, `event_type`, `actor`,
  `from_state`, `to_state`, `detail` JSON, `created_at`).
- `call_idempotency_keys`: client key → replayed response.
- `owner_notifications`: escalation **stubs** (`status = 'queued-stub'`).

## Key design decisions

1. **Privacy before persistence.** Masking and hashing happen before the
   INSERT; there is no code path that writes a raw caller ID. A test scans
   every text column of both data tables for a fixture number and fails if
   it appears.
2. **One state machine, in code.** `CALL_TRANSITIONS` is the only place that
   knows which outcome moves are legal. The web layer and service layer both
   funnel through it.
3. **Priority is computed, not stored.** `urgency_score` is stored (a fact
   about the call); `priority` is computed from score and age at read time,
   so aging is always honest — stale scores can't linger.
4. **Flags inform, never decide.** The repeat-ID anomaly flag is stored and
   displayed; it neither boosts nor suppresses the call. The queue can be
   gamed by spoofed IDs only if a human chooses to trust the flag — the
   system never auto-trusts.
5. **Stubs are labeled as stubs.** `owner_notifications` rows say
   "STUB — … No real message was sent" in the message body and
   `status = 'queued-stub'`. The escalation *decision path* is tested; no
   delivery is claimed.
6. **Clock injection.** `ingest_event`, `log_outcome`, `priority_queue`,
   `sweep_sla`, `ingestion_lag_report`, and `dashboard_stats` all accept
   `now=`; tests freeze time at T0 = 2026-10-23T12:00:00Z.
