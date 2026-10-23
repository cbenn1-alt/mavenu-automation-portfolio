# Project 02 — Test Plan

**Scope:** 101 tests across four files, all run with the project venv
pytest. P01's 51 tests must keep passing (regression gate).

## Coverage map

| Area | File | Tests | What is asserted |
|---|---|---|---|
| State machine | `test_approval_workflow.py` | 33 | All 16 legal transitions permitted; 13 illegal transitions raise `InvalidTransition`; terminal states have no outgoing moves; unknown states raise; transition table is a defensive copy |
| Validation | `test_request_validation.py` | 19 | Valid payload cleans (dollars→cents, uppercase cost center, lowercased email); all 6 request types accepted; monetary types require amount > 0; non-monetary types allow 0; garbage/negative/over-cap amounts rejected; justification 20–2000 chars; cost-center pattern; requester identity required; multiple field errors reported together |
| Chain routing | `test_approval_service.py` | 5 of 33 | `approval_chain_for`: below/at/above threshold; `submit_for_review` builds the right chain and arms the SLA deadline |
| Decisions | `test_approval_service.py` | 9 of 33 | Two-step approve (manager → finance → approved); single-step immediate approval; wrong role rejected with no state change; reject terminates; request_changes → resubmit reroutes with fresh SLA; decisions in wrong state / unknown id / unknown decision value rejected |
| Fulfill / cancel | `test_approval_service.py` | 4 of 33 | Fulfill after approval; fulfill before approval illegal; cancel from in_review; cancel after decision rejected |
| SLA escalation | `test_approval_service.py` | 5 of 33 | Breach escalates to director with fresh deadline (fake clock); unbreached requests untouched; sweep idempotent for already-escalated; director can decide; manager cannot decide after escalation |
| Audit trail | `test_approval_service.py` | 2 of 33 | Full lifecycle event sequence + actor stamps + from/to linkage + role on approval events; escalation event recorded with actor `system` |
| Dashboard reconciliation | `test_approval_service.py` | 2 of 33 | `request_stats()` totals reconcile; independent raw-SQL re-computation with no shared code path; `sla_breached`/`escalated` counts follow the fake clock |
| Idempotency | `test_approval_service.py` | 3 of 33 | Replay without duplicate; invalid payload stores nothing |
| Migration rollback | `test_approval_service.py` | 3 of 33 | Down-step rolls back 002 for real (tables dropped, record removed, P01 untouched, re-apply works); rollback of unapplied migration is a no-op; rollback without a down-step raises |
| HTTP API | `test_requests_api.py` | 16 | Intake 201; idempotent replay 200; 422 with field errors; 422 on bad JSON; GET includes chain + events + allowed transitions; 404; full approval flow via API; wrong role → 409; double submit → 409; cancel; resubmit; SLA sweep endpoint escalates (zero-hour SLA fixture); HTML form renders/redirects/re-renders-422; dashboard 200; hub lists P02 |

## Test doubles and determinism

- **Clock:** `T0 = 2026-10-23T12:00:00Z`; every service call passes `now=`.
  SLA deadlines are exact ISO strings, so assertions are equality checks,
  not ranges.
- **No network, no randomness in assertions:** public IDs are sequential
  (`RQ-000001`…); UUIDs appear only in HTML hidden form fields.
- **Fixtures are synthetic:** invented names (`Dana Rivera`, `Sam Chen`),
  `example.com` emails, invented cost centers.

## What is not tested (documented gaps)

- Concurrency (single-process demo; SQLite WAL only).
- Real scheduler invocation of the sweep (endpoint tested; cron wiring is
  an ops step).
- Authentication (none exists by design; see SECURITY.md).

## Regression gate

Full suite: `.venv/bin/python -m pytest tests/ -q` → **152 passed**
(51 P01 + 101 P02), recorded in TEST_RESULTS.md with date and environment.
