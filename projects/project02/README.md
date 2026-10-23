# Project 02 — Enterprise Request & Approval Automation

**Status: Implemented · Tested** — 101 automated tests, all passing
(152/152 with Project 01; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | HTML intake form, JSON API, server-side validation, role-based multi-step approval routing, state machine enforced in code, deterministic SLA-breach escalation, actor-stamped audit trail, SQLite persistence, idempotency-key duplicate protection, DB-computed dashboard |
| What is SIMULATED | **Simulated** | The intake → approval → document-store → SQL-reporting chain (the real-world analogue of Power Apps → Power Automate → SharePoint → SQL). Approver identity is asserted, not authenticated. The SLA sweep is triggerable, not yet scheduled |
| What is SYNTHETIC | **Demo** | Every name, email, amount, cost center, and justification in fixtures, tests, and demos is invented. No real people, no real businesses |
| What is NOT claimed | — | No production deployment. No bank, employer, or platform endorsement. No Power Automate / Power Apps / SharePoint / UiPath implementation or proficiency — the code is a custom Python stack and is labeled as such everywhere |

## Business problem

Internal requests (purchases, travel, access, HR changes, vendor
onboarding, budget transfers) stall in inboxes: nobody can say who owns the
next approval, SLAs slip silently, and the audit trail lives in email
threads. This project is a working request-and-approval engine: intake is
validated server-side, the system builds a role-based approval chain from
the request amount, each decision is role-enforced and recorded, approvals
stalled past their SLA escalate to a director automatically, and every step
lands in a queryable audit trail with an operations dashboard on top.

## Implemented capabilities

- Request-intake form (HTML) and JSON API (`POST /api/requests`)
- Server-side validation (never trusts the client): request type, amount
  (dollars → cents), cost center pattern, justification 20–2000 chars,
  requester name + valid email
- Duplicate-submission protection via client `Idempotency-Key`
  (header or hidden form field); replays return the original response —
  retries never create duplicate business records
- Approval routing in code: every request needs its `manager`; amounts over
  the finance threshold (default $1,000, `MAVENU_FINANCE_THRESHOLD_CENTS`)
  additionally need `finance`
- Role enforcement: a decision from any role other than the step's owner is
  rejected and changes nothing
- Request lifecycle states in code:
  `draft → submitted → in_review → approved / rejected → fulfilled`, with
  `changes_requested`, `escalated`, `cancelled`; illegal transitions raise
- Deterministic SLA-breach escalation: `sweep_sla()` reroutes stalled
  approvals to `director` with a fresh deadline; the clock is injectable so
  tests freeze time
- Reviewer UI + API for submit / decide / resubmit / cancel / fulfill, every
  action actor-stamped
- Operations dashboard whose totals are computed from the database
  (test asserts reconciliation via an independent SQL re-computation)
- Structured audit log: every transition is a `request_events` row and a
  JSON stdout line
- Migration rollback: `002_approvals.down.sql` + `db.rollback_migration()`,
  tested for real (apply → use → roll back → re-apply)

## What is simulated (labeled, not hidden)

- **Platform mapping**: the chain mirrors Power Apps → Power Automate →
  SharePoint → SQL conceptually, but every line runs on the custom Python
  stack. No Power Platform access exists; the docs say so.
- **Approver identity**: roles are asserted by the caller (`reviewer:mara`
  acting as `manager`), not authenticated — demo scope, see SECURITY.md.
- **Scheduling**: the SLA sweep runs when triggered
  (`POST /api/requests/sla-sweep`); a real deployment would call it from a
  scheduler (documented in RUNBOOK.md).

## Technology stack

Python 3.12 stdlib (`wsgiref`, `sqlite3`), pytest (dev only).
Zero runtime dependencies, zero cost.

## Repository map

- Service logic: `src/mavenu/requests_approval.py`
- State machines: `src/mavenu/workflow.py` (`REQUEST_WORKFLOW`)
- Web/API: `src/mavenu/web.py` (`/project02*`, `/api/requests*`)
- Schema: `src/mavenu/migrations/002_approvals.sql` (+ `.down.sql` rollback)
- Migration runner + rollback: `src/mavenu/db.py`
- Config: `src/mavenu/config.py` (`MAVENU_FINANCE_THRESHOLD_CENTS`,
  `MAVENU_APPROVAL_SLA_HOURS`)
- Tests: `tests/test_{approval_workflow,request_validation,approval_service,requests_api}.py`

## Docs in this folder

- `REQUIREMENTS.md` — spec (nine sections) + traceable requirements
- `ARCHITECTURE.md` — how it is built
- `TEST_PLAN.md` — what the tests cover
- `TEST_RESULTS.md` — actual results from real runs (2026-10-23)
- `SECURITY.md` — threat model and controls
- `RUNBOOK.md` — operating the demo, including rollback
- `DEMO.md` — guided demonstration script for a reviewer
- `EVIDENCE_MATRIX.md` — every public claim mapped to evidence

## Known limitations

- Single-process demo server (`wsgiref`); not for production traffic.
- SQLite single-file database; no multi-user concurrency story.
- No authentication on approver actions (demo scope; see SECURITY.md).
- No approver notifications (email/SMS); escalation is the mechanism.
- No delegation/reassignment of steps; no parallel approval branches.
- Approver roles are asserted, not verified against an identity provider.
