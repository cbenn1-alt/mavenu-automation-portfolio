# Project 02 — Architecture

## Shape

P02 reuses P01's proven shape (intake → validation → state machine →
SQLite → dashboard), extended with an approval layer:

```
                    ┌──────────────┐
                    │  HTML form   │  /project02
                    │  JSON API    │  POST /api/requests
                    └──────┬───────┘
                           ▼
              ┌─────────────────────────┐
              │ validate_request_payload│  request type, amount→cents,
              │ (server-side only)      │  cost center, justification,
              └───────────┬─────────────┘  requester identity
                          ▼
              ┌─────────────────────────┐
              │ idempotency check       │  request_idempotency_keys
              │ (key → replay)          │  (P01 pattern reused)
              └───────────┬─────────────┘
                          ▼
              ┌─────────────────────────┐
              │ requests table          │  state = draft
              │ + request.created event │
              └───────────┬─────────────┘
                          ▼  submit_for_review()
              ┌─────────────────────────┐
              │ approval_chain built    │  [manager] (+ [finance] if
              │ from amount; SLA armed  │  amount > threshold)
              │ draft→submitted→in_review
              └───────────┬─────────────┘
                          ▼
              ┌─────────────────────────┐
              │ record_decision()       │  role must own current step
              │  approve → next step /  │  (ApprovalRoleError otherwise)
              │    approved             │
              │  reject → rejected      │
              │  request_changes →      │
              │    changes_requested    │
              └───────────┬─────────────┘
                          ▼
              ┌─────────────────────────┐
              │ sweep_sla()             │  in_review + sla_due_at <= now
              │  → escalated to        │  → chain := [director],
              │    director, fresh SLA  │    fresh deadline
              └───────────┬─────────────┘
                          ▼
              ┌─────────────────────────┐
              │ request_stats() /       │  totals from the DB;
              │ /project02/dashboard    │  reconciliation asserted
              └─────────────────────────┘
```

Every arrow that changes state goes through `REQUEST_WORKFLOW.check()`
first; every state change writes a `request_events` row and prints a JSON
log line.

## Modules

| Module | Responsibility |
|---|---|
| `src/mavenu/requests_approval.py` | Validation, chain building, all state verbs (`submit_request`, `submit_for_review`, `record_decision`, `resubmit`, `fulfill`, `cancel`, `sweep_sla`), audit writer, `request_stats()` |
| `src/mavenu/workflow.py` | `REQUEST_TRANSITIONS` / `REQUEST_WORKFLOW` — the single source of truth for legal transitions; `InvalidTransition` |
| `src/mavenu/migrations/002_approvals.sql` | `requests`, `request_events`, `request_idempotency_keys` |
| `src/mavenu/migrations/002_approvals.down.sql` | Rollback: drops the three P02 tables |
| `src/mavenu/db.py` | `run_migrations()` (now ignores `*.down.sql`) + new `rollback_migration()` |
| `src/mavenu/config.py` | `finance_threshold_cents`, `approval_sla_hours` (env-overridable) |
| `src/mavenu/web.py` | `/project02*` pages, `/api/requests*` endpoints; maps domain errors to 404/409/422 |

## Key design decisions

1. **One state machine, in code.** `REQUEST_TRANSITIONS` is the only place
   that knows which moves are legal. The web layer and the service layer
   both funnel through it — there is no way to change state without the
   check.
2. **Chain as data.** `approval_chain` is a JSON list of roles on the row,
   with `current_step` pointing at the pending approver. Routing rules
   (`approval_chain_for`) are a pure function of amount — trivially
   testable, and easy to extend with per-type rules later.
3. **Escalation rewrites the chain.** On SLA breach the remaining chain
   becomes `["director"]` rather than adding a parallel path. One owner, one
   deadline, no ambiguity about who can decide next.
4. **Injectable clock.** Every time-touching function takes `now`. The
   service never calls `datetime.now()` except through `_now()`. SLA tests
   are deterministic; the HTTP sweep endpoint uses real time.
5. **Idempotency reuses P01's pattern** (`key → (status, body)` replay with
   TTL), on a separate table so the two projects' keys never collide.
6. **Audit is a separate table per project** (`request_events` vs
   `lead_events`) — same discipline, no cross-project coupling.
7. **Migration runner ignores `*.down.sql`** in the up-pass; down-steps are
   applied explicitly via `rollback_migration(name)`, which removes the
   `schema_migrations` record so re-apply works.

## Request lifecycle walkthrough ($2,450 purchase)

1. `POST /api/requests` → validated → `draft` (`RQ-000007`)
2. `POST /api/requests/RQ-000007/submit` →
   `submitted` → chain `["manager","finance"]` → `in_review`,
   `sla_due_at = now + 48h`
3. Manager approves → `approval.recorded`, `current_step = 1`, SLA re-armed,
   still `in_review`
4. Finance approves → `approved`, `decided_by`/`decided_at` stamped
5. Ops fulfills → `fulfilled` (terminal)

If step 3 never happens within 48h, `sweep_sla()` moves the request to
`escalated` with chain `["director"]`; only a director decision resolves it.

## Data flow for a decision

```
POST /api/requests/<id>/decision {"decision","role","actor"}
  → record_decision()
    → state must be in_review|escalated        (InvalidDecision)
    → role must equal chain[current_step]      (ApprovalRoleError)
    → approve + last step → approved (+ decided_by/at)
    → approve + more steps → current_step += 1, SLA re-armed, stay in_review
    → reject → rejected (+ decided_by/at)
    → request_changes → changes_requested
    → every path: request_events row + JSON log line
```

## Error mapping (HTTP)

| Domain error | HTTP |
|---|---|
| `ValidationError` | 422 + field errors |
| `KeyError` (unknown id) | 404 |
| `InvalidDecision`, `ApprovalRoleError`, `InvalidTransition` | 409 |
| Unexpected | 500 generic envelope (no internals leaked) |

## What the architecture deliberately does not include

Authentication, a scheduler for the sweep, notifications, delegation,
parallel branches — all documented non-goals in REQUIREMENTS.md §9.
