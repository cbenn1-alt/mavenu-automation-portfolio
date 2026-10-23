# Q10 — Webhook Integration Hub: Architecture

```
                        ┌──────────────┐
                        │  sender (any │
                        │  form/calendar│
                        │  /sheet tool) │
                        └──────┬───────┘
                               │ POST /api/webhooks/events
                               │ X-Webhook-Signature: sha256=<hex>
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ INGEST  (src/mavenu/webhooks.py)                             │
│  verify signature ──► normalize envelope ──► append-only      │
│  (strict: reject    (EnvelopeError →        event store      │
│   unsigned)          poison path)           webhook_events   │
│                                                     │        │
│                              idempotent on event_id  │        │
└─────────────────────────────────────────────────────┼────────┘
                                                      ▼
┌─────────────────────────────────────────────────────────────┐
│ ROUTES  (src/mavenu/router.py)                               │
│  versioned rules: event_type + conditions → actions          │
│  log → structured stdout (redacted)                          │
│  transform → webhook_derived (NEVER re-routed: loop guard)    │
│  forward → delivery.enqueue_delivery (idempotent)            │
│  dry_run() shows the plan with zero side effects             │
│  lineage: received → routed → queued                         │
└─────────────────────────────────────────────────────┼────────┘
                                                      ▼
┌─────────────────────────────────────────────────────────────┐
│ DELIVER (src/mavenu/delivery.py)                             │
│  retry queue: exponential backoff 30s·2^(n-1), cap 1h        │
│  dead-letter after max_attempts (5); unknown endpoints       │
│  dead-letter immediately (permanent config error)            │
│  per-endpoint circuit breaker:                               │
│    closed ─3 consecutive failures─► open ─60s─► half_open     │
│    half_open: exactly ONE probe per loop run                 │
│    probe ok → closed · probe fail → open                     │
│  every attempt → append-only webhook_attempts                │
│  stub endpoints: in-process callables, NEVER real HTTP        │
└─────────────────────────────────────────────────────┼────────┘
                                                      ▼
┌─────────────────────────────────────────────────────────────┐
│ AUDIT                                                       │
│  webhook_lineage: append-only per-event state transitions    │
│  received → routed → queued → delivered | dead_lettered      │
│                      └────────► rejected (strict mode)        │
│  current status is DERIVED from latest lineage row —         │
│  webhook_events rows are never UPDATEed                      │
└─────────────────────────────────────────────────────────────┘
```

## Module map

| Module | Responsibility | Key functions |
|---|---|---|
| `webhooks.py` | ingest, HMAC, envelope, idempotency, batch isolation | `sign`, `verify_signature`, `normalize_envelope`, `ingest_event`, `process_batch`, `process_envelope`, `record_lineage`, `event_status`, `redacted_summary` |
| `router.py` | versioned rules, conditions, actions, dry-run | `create_rule`, `update_rule`, `delete_rule`, `match_rules`, `plan_actions`, `dry_run`, `apply_routes`, `seed_demo_rules` |
| `delivery.py` | retry queue, backoff, dead-letter, circuit breaker, replay | `enqueue_delivery`, `run_delivery_loop`, `dead_letter`, `replay_dead_letter`, `settle_event`, `backoff_delay_seconds` |
| `web.py` (Q10 section) | `/project_q10*` pages, `/api/webhooks*` endpoints, stub sink registry | `api_wh_receive`, `api_wh_route_*`, `api_wh_deliver_run`, … |

## Database (migration `007_webhook_hub.sql`)

| Table | Mutability | Purpose |
|---|---|---|
| `webhook_events` | **append-only** | canonical envelopes as received |
| `webhook_lineage` | **append-only** | per-event state transitions (the audit trail) |
| `webhook_attempts` | **append-only** | every delivery attempt, ok or failed |
| `webhook_routes` | mutable (versioned) | routing rules; updates bump `version` |
| `webhook_derived` | append-only | transform-action projections |
| `webhook_deliveries` | mutable queue | retry state: `queued → delivered \| dead_lettered` |
| `webhook_dead_letters` | append-only (+`replayed` flag) | poison / routing-error / exhausted-retry events |
| `webhook_endpoint_state` | mutable | circuit-breaker state per endpoint |

## Design decisions

1. **Append-only event store + derived status.** The spec asked for an
   append-only store; status is derived from the latest lineage row instead
   of an UPDATEable column. Tampering with history would require rewriting
   the lineage log, which is itself append-only — the audit trail is the
   state.
2. **Transforms never re-enter routing.** A transform that fed back into
   routing could loop forever on a misconfigured rule. The derived envelope
   is stored as data, not as a new event. Documented loop guard.
3. **Unknown endpoints dead-letter immediately.** A wrong endpoint name is
   a config error, not flakiness — retrying it five times with backoff
   wastes cycles and pollutes the circuit breaker. It also doesn't count
   against the circuit.
4. **One half-open probe per loop run.** Without this, a retry storm queued
   behind an open circuit would slip dozens of attempts through the
   half-open window. The `probes` set in `run_delivery_loop` bounds it.
5. **Idempotency at two levels.** Ingest dedupes on `event_id`; forwarding
   dedupes on `(event_id, endpoint)` via `INSERT OR IGNORE`. The same event
   can never be delivered twice, even if re-ingested.
6. **Redaction at the boundary.** `redacted_summary()` is the only
   payload-derived content allowed in logs, lineage detail, dead-letter
   detail, and API responses. Full envelopes live only in the event store
   (synthetic in v1).
7. **Injectable clock.** All time-dependent functions take `now=`; tests
   assert exact `next_attempt_at` datetimes. Same pattern as Q02's cadence.
