# Q02 — Architecture

## Module map

```
src/mavenu/
  estimates.py      CRUD + lifecycle (transition_estimate, set_unsubscribed,
                    create_with_idempotency, estimate_events, template_context)
  cadence.py        rules (list/replace), run_cadence, sweep_expired,
                    outbox(), flush_outbox, MessageAdapter protocol,
                    StubMessageAdapter
  templates.py      create_template (versioned), render_template,
                    test_send, template_history, list_templates
  reports.py        aging_report, win_loss_report, followup_effectiveness
  workflow.py       ESTIMATE_TRANSITIONS / ESTIMATE_WORKFLOW (code-level machine)
  web.py            /project_q02* pages + /api/estimates*, /api/estimate-templates*,
                    /api/cadence* endpoints
  migrations/
    004_estimates.sql        estimates, estimate_events, cadence_rules,
                             message_templates, estimate_outbox, send_log,
                             estimate_idempotency_keys (+ seeded day 2/7/14
                             rules and three templates)
    004_estimates.down.sql   drops the seven Q02 tables
```

## Data flow

```
create (draft) ──transition──▶ sent ──▶ viewed ──▶ followed_up ──▶ accepted
   │                              │         │            │            declined
   │                              │         │            │            expired
   │                              ▼         ▼            ▼
   │                         run_cadence(now, rules)
   │                              │ render active template version
   │                              ▼
   │                    estimate_outbox (queued, idempotency key
   │                     est:<id>:step:<n> UNIQUE)
   │                              │ flush_outbox(StubMessageAdapter)
   │                              ▼
   │                         send_log (status='stub-logged')
   │
   └─ every state change ──▶ estimate_events (actor, from/to, detail)
                             + JSON stdout log line
```

## Key decisions

- **State machine in code, CHECK constraint in SQL.** `ESTIMATE_WORKFLOW`
  is the single source of truth; the CHECK constraint is defense in depth
  so no ad-hoc SQL can smuggle an estimate into an unknown state.
- **Idempotency keys, not "don't run twice".** The scheduler is designed
  to be re-run freely: `ON CONFLICT DO NOTHING` on the UNIQUE
  `idempotency_key` makes replays safe by construction, and a test replays
  the scheduler 1,001 times asserting zero new rows.
- **Outbox, not a mailer.** v1 deliberately stops at a rendered queue.
  The `MessageAdapter` protocol is the only seam that could ever touch a
  network, and the only implementation is a stub. This keeps the honest
  claim small: "the automation is the cadence computation and the audit
  trail."
- **Versioned templates, preserved history.** Cadence rules reference
  templates by name; the scheduler renders the *active* version while the
  outbox row pins `template_version`, so a queued message is forever
  traceable to the exact copy that produced it.
- **Injectable clock everywhere time matters.** `create_estimate`,
  `transition_estimate`, `run_cadence`, `sweep_expired`, `flush_outbox`,
  and all three reports accept `now=`; production passes nothing (wall
  clock), tests pass a frozen datetime. All storage/comparison is UTC.
- **Stop rules as query predicates.** Accepted/declined/expired/
  unsubscribed are excluded in `_open_estimates()` itself, so no future
  scheduler path can forget to check them.
- **Closed decline-reason set.** Free text can't be grouped; the closed
  set plus an optional note gives both reportability and nuance.
- **Fail closed on template errors.** A bad template skips the step with
  an audit event instead of queueing a broken message — the failure the
  spec's threat analysis calls out.

## Table summary

| Table | Purpose |
|---|---|
| `estimates` | Estimate records + lifecycle state (CHECK-constrained) |
| `estimate_events` | Append-only audit trail (actor, from/to, detail JSON) |
| `cadence_rules` | Configurable steps; old sets deactivated, never deleted |
| `message_templates` | Versioned templates; UNIQUE(name, version); history preserved |
| `estimate_outbox` | Queued rendered follow-ups; UNIQUE idempotency key |
| `send_log` | Adapter outcomes; UNIQUE(outbox_id) — one log row per outbox row |
| `estimate_idempotency_keys` | Duplicate protection for the create API |

## Why not a real mailer

The failure modes that kill follow-up systems are silent ones: a step
queued twice, a cadence computed in local time that misfires after a
clock change, a template rendered with a missing variable. All three are
handled and tested here. Actual delivery is a solved, commoditized
problem (SMTP/API providers) with legal consequences (CAN-SPAM/TCPA)
that a portfolio demo must not pretend to solve — hence the adapter
seam, the stub, and the honest labels.
