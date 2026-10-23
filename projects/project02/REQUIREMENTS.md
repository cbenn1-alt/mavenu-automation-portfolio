# Project 02 — Requirements & Specification

**Status: Implemented · Tested** (152/152 tests passing, 2026-10-23).

> **Honest-status banner.** This is a **portfolio SIMULATION** built on a
> custom Python stack. It mirrors the real-world chain
> intake form → approval automation → document store → SQL reporting (the
> analogue of Power Apps → Power Automate → SharePoint → SQL) but it is
> **not** a Power Platform, SharePoint, or UiPath implementation — no such
> access exists, and nothing here claims otherwise. All data is synthetic.
> No production deployment, no bank endorsement, no real users.

---

# P02 Specification (nine sections)

## 1. Purpose

Demonstrate a working enterprise request-and-approval workflow: a requester
submits a business request (purchase, travel, access, HR change, vendor
onboarding, budget transfer); the system validates it, routes it through a
role-based multi-step approval chain, escalates approvals that stall past an
SLA deadline, records every step in an actor-stamped audit trail, and
reports operations from the database. The transferable engineering is the
state machine, the approval routing, the deterministic SLA sweep, the
idempotency contract, and the audit discipline — the same concepts that
underpin Power Automate approval flows and SharePoint-backed tracking, on
the custom stack.

## 2. Scope

In scope:

- HTML intake form + JSON API (`POST /api/requests`)
- Server-side validation of request type, amount, cost center,
  justification length, and requester identity fields
- Multi-step approval routing by role and amount
  (requester → manager → finance over a configurable threshold)
- Request state machine enforced in code
- Deterministic SLA-breach escalation with an injectable clock
- Actor-stamped audit trail (DB row + structured log line per transition)
- SQLite persistence; idempotency-key duplicate protection (P01's pattern)
- Operations dashboard computed from the DB, reconciled to source rows

Out of scope: see §9 (non-goals).

## 3. States

`draft → submitted → in_review → approved / rejected → fulfilled`, plus
exception states `escalated`, `cancelled`, `changes_requested`.

Full transition table (enforced by `mavenu.workflow.REQUEST_WORKFLOW`):

| From | To |
|---|---|
| `draft` | `submitted`, `cancelled` |
| `submitted` | `in_review`, `cancelled` |
| `in_review` | `approved`, `rejected`, `changes_requested`, `escalated`, `cancelled` |
| `changes_requested` | `submitted`, `cancelled` |
| `escalated` | `approved`, `rejected`, `changes_requested`, `cancelled` |
| `approved` | `fulfilled` |
| `rejected`, `fulfilled`, `cancelled` | (terminal — no outgoing transitions) |

Any transition not in this table raises `InvalidTransition`; there is no
silent or ad-hoc state change anywhere in the system.

## 4. Roles

| Role | Meaning in the demo |
|---|---|
| `requester` | Creates and submits requests; resubmits after `changes_requested`; may cancel before a terminal decision |
| `manager` | Owns step 0 of every approval chain |
| `finance` | Owns step 1 when the request amount exceeds the finance threshold (default $1,000 = 100,000¢, `MAVENU_FINANCE_THRESHOLD_CENTS`) |
| `director` | Owns escalated requests after an SLA breach |
| `ops` | Marks approved requests `fulfilled` |
| `system` | Runs the SLA sweep; emits routing events |

Role enforcement is in code: `record_decision()` rejects a decision when
the caller's role does not own the current step (`ApprovalRoleError`).
**Demo scope:** roles are asserted by the caller, not authenticated
(see SECURITY.md).

## 5. SLA rules

- When a request enters `in_review` (or advances a step), the pending step
  gets `sla_due_at = now + approval_sla_hours` (default 48h,
  `MAVENU_APPROVAL_SLA_HOURS`).
- `sweep_sla(conn, now=...)` finds every `in_review` request with
  `sla_due_at <= now` and escalates it: state → `escalated`, the remaining
  chain is replaced by `["director"]`, and a fresh SLA deadline is armed.
- The sweep is deterministic: every time-touching function accepts an
  injectable `now`, so tests freeze the clock. The public endpoint
  `POST /api/requests/sla-sweep` runs the sweep with real time (an ops
  trigger, analogous to a scheduled flow run).
- Already-escalated requests are not re-escalated by the sweep.

## 6. Simulation mapping

What the custom stack stands in for, and where the analogy ends:

| Real-world component | P02 analogue | Label |
|---|---|---|
| Power Apps intake form | `/project02` HTML form + `POST /api/requests` | **Implemented** |
| Power Automate approval flow | `requests_approval.py` routing + state machine | **Implemented** (custom stack) |
| Approver assignment / AAD roles | `approval_chain` JSON + role assertion | **Simulated** (no real identity) |
| Scheduled SLA flow run | `POST /api/requests/sla-sweep` + `sweep_sla()` | **Implemented** (manual trigger; a real scheduler would call it) |
| SharePoint document store | `requests` table (SQLite) | **Simulated** (document-store semantics, not SharePoint) |
| SQL reporting | `request_stats()` + `/project02/dashboard` | **Implemented** |
| Demo fixtures | `GOOD_REQUEST`, clock-injected tests | **Demo** (deterministic) |

**Explicitly not claimed:** Power Automate, Power Apps, SharePoint Online,
Dataverse, or UiPath proficiency. Those platforms were not used and are not
available in this environment.

## 7. Data model

`src/mavenu/migrations/002_approvals.sql`:

- **`requests`** — `id`, `public_id` (`RQ-000123`), `request_type`,
  `title`, `amount_cents`, `cost_center`, `justification`,
  `requester_name`, `requester_email`, `state`, `approval_chain` (JSON role
  list), `current_step`, `sla_due_at`, `decided_by`, `decided_at`,
  `created_at`, `updated_at`. Indexes on `state`, `created_at`,
  `(state, sla_due_at)`.
- **`request_events`** — append-only audit: `request_id` (FK, cascade),
  `event_type`, `actor`, `role`, `from_state`, `to_state`, `detail` (JSON),
  `created_at`.
- **`request_idempotency_keys`** — `key` (PK), `request_id` (FK),
  `response_status`, `response_body` (JSON replay), `created_at`.

Rollback: `002_approvals.down.sql` drops the three P02 tables; applied by
`db.rollback_migration()` (tested — see TEST_RESULTS.md).

## 8. Acceptance criteria

1. Valid submissions create exactly one request record in `draft`.
2. Invalid submissions are rejected with field-level errors; nothing stored.
3. Repeated `Idempotency-Key` replays the original response; no duplicate
   business record.
4. Submission routes `draft → submitted → in_review` with the correct chain
   for the amount (finance added only above threshold).
5. A decision from the wrong role is rejected and changes nothing.
6. Final approval moves the request to `approved`; rejection and
   change-requests move to their states; approved requests can be fulfilled.
7. SLA breach escalates to `director` with a fresh deadline; only the
   director can then decide; the sweep is deterministic under a fake clock.
8. Every transition is an actor-stamped audit row plus a structured log line;
   the timeline is consistent (from/to states chain together).
9. Dashboard totals reconcile with the database (test re-computes with raw
   SQL through no shared code path).
10. Illegal transitions raise and never mutate state.
11. The migration down-step rolls back 002 cleanly and re-applies.

## 9. Non-goals

- Real authentication / authorization (actor labels only; documented gap).
- Real Power Platform, SharePoint, Dataverse, or UiPath integration.
- Email/SMS approver notifications (the sweep is the escalation mechanism;
  notifications are a documented future step).
- Delegation / reassignment of approval steps (out of this slice).
- Concurrent-approver / quorum rules; parallel branches.
- A background scheduler (the sweep endpoint is triggerable; wiring it to
  cron/systemd is an ops step documented in RUNBOOK.md).

---

## Functional requirements (traceable)

| ID | Requirement | Verified by |
|---|---|---|
| R1 | Intake form + `POST /api/requests` accept synthetic requests | API + HTML tests |
| R2 | Server-side validation: type, amount, cost center, justification (20–2000 chars), requester name/email | `test_request_validation.py` (19) |
| R3 | State machine from §3 enforced in code; illegal transitions raise | `test_approval_workflow.py` (33) |
| R4 | Approval routing: manager always; finance above threshold; director on escalation | service tests |
| R5 | Role enforcement on every decision | service + API tests |
| R6 | SLA escalation deterministic under injected clock; re-arms deadline | service tests |
| R7 | Actor-stamped audit trail: DB row + JSON log line per transition | service tests |
| R8 | Idempotency-key duplicate protection (P01 pattern) | service + API tests |
| R9 | Dashboard computed from DB; totals reconcile | service + API tests |
| R10 | Migration down-step rolls back cleanly | `test_migration_down_step_rolls_back_002` |

## Non-functional requirements

- Python 3.12 stdlib only at runtime; $0 spend; no network calls.
- P01's 51 tests keep passing (no regressions).
- UTF-8 text files only; no binaries; commit locally only (no push).
- All data synthetic; no real PII anywhere.
