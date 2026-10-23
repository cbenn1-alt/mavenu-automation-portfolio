# Project 01 — Architecture

Modular monolith, Python stdlib only. One process serves pages and the API;
one SQLite file holds business records, the audit trail, and idempotency keys.

```
                    ┌─────────────────────────────────────────┐
                    │            web.py (WSGI app)             │
                    │  pages: / /project01 /dashboard /leads  │
                    │  api:   /api/leads /api/stats /health   │
                    └───────────────┬─────────────────────────┘
                                    │ calls
                    ┌───────────────▼─────────────────────────┐
                    │         leads.py (service layer)        │
                    │  submit_lead: validate → dedupe →       │
                    │  insert → classify → qualify → route →  │
                    │  book (adapter) ; transition_lead       │
                    └─┬─────────┬───────────────┬─────────────┘
                      │         │               │
            ┌─────────▼──┐ ┌────▼────────┐ ┌────▼──────────┐
            │validation  │ │ classifier  │ │booking adapter│
            │  .py       │ │  .py        │ │ (interface)   │
            └────────────┘ └─────────────┘ └───────────────┘
                      ┌────────▼────────┐
                      │  db.py + sqlite │
                      │  leads          │
                      │  lead_events    │◄── events.py (JSON log)
                      │  idempotency_keys
                      └─────────────────┘
```

## Key design decisions

1. **WSGI on stdlib (`wsgiref`-compatible callable).** No framework to
   install, audit, or pay for. Routing is explicit pattern matching;
   adding a framework later would not change the service layer.
2. **Service layer separated from HTTP.** `leads.py` knows nothing about
   requests/responses, so business rules are tested without HTTP.
3. **State machine in one place.** `workflow.py` owns `LEAD_TRANSITIONS`;
   the service calls `check()` before every change. There is no other path
   to a state change.
4. **Classifier behind a protocol.** `LeadClassifier` is the seam for a real
   model. The demo implementation is pure rules and deterministic — the
   same features always produce the same classification (tested).
5. **Booking behind an interface.** `BookingAdapter` lets the failure path be
   exercised deterministically. Production would inject a real adapter.
6. **Idempotency keys stored with the response.** Replays return byte-identical
   semantics without re-executing business logic.
7. **Audit-first events.** `record_event()` writes the DB row and commits
   immediately, then emits the JSON log line. (A test caught a missing
   commit here during development — the suite now guards it.)
8. **Migrations are versioned SQL files** applied in filename order and
   recorded in `schema_migrations`. Fresh DBs and upgrades take the same path.

## Data model

- `leads` — business record + lifecycle state + classification outcome +
  booking reference + `possible_duplicate_of` self-reference.
- `lead_events` — append-only audit: event type, actor, from/to state,
  JSON detail, timestamp. Never updated or deleted by the app.
- `idempotency_keys` — key → lead, stored response, created-at (TTL enforced).

## Request flows

**Happy path:** `POST /api/leads` → validate → dedupe check → insert
(`received`) → classify (≥ threshold, in area) → `qualified` → `routed` →
booking adapter → `booked`. Each arrow is an audited transition.

**Review path:** low confidence, out-of-area, or booking failure →
`needs_review` with a recorded cause → reviewer transitions via UI/API.

**Retry path:** known idempotency key → stored response replayed, 200,
no new record, no new events.
