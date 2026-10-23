# Project 02 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23 (19:24 UTC)

```
152 passed in 0.46s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_workflow.py` (P01) | 6 | 6 passed |
| `tests/test_validation.py` (P01) | 16 | 16 passed |
| `tests/test_classifier.py` (P01) | 5 | 5 passed |
| `tests/test_leads.py` (P01) | 10 | 10 passed |
| `tests/test_web.py` (P01) | 14 | 14 passed |
| `tests/test_approval_workflow.py` (P02) | 33 | 33 passed |
| `tests/test_request_validation.py` (P02) | 19 | 19 passed |
| `tests/test_approval_service.py` (P02) | 33 | 33 passed |
| `tests/test_requests_api.py` (P02) | 16 | 16 passed |
| **Total** | **152** | **152 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, Linux,
stdlib-only app, project-local venv (`~/workspace/mavenu-portfolio/.venv`).

**Regression gate: PASS.** P01's 51 tests all pass unchanged alongside the
101 new P02 tests.

## Live smoke test — 2026-10-23 (real server, `python run.py --port 8137`)

| Check | Result |
|---|---|
| `POST /api/requests` valid purchase ($2,450) | 201 → `{"public_id":"RQ-000001","state":"draft"}` |
| `POST /api/requests` with `Idempotency-Key: smoke-1` twice | 201 then 200 → `{"replayed":true}` (one record) |
| `POST /api/requests/RQ-000001/submit` | 200 → `in_review` |
| manager approves | 200 → `in_review` (finance step pending) |
| finance approves | 200 → `approved` |
| `POST /api/requests/RQ-000001/fulfill` | 200 → `fulfilled` |
| `GET /project02/dashboard` | 200 |
| `GET /` hub | 200, lists Project 02 as implemented + tested (Gate B) |

## Rollback test — 2026-10-23 (run for real)

`tests/test_approval_service.py::test_migration_down_step_rolls_back_002`
**passed** in the run above (environment: Python 3.12.3, pytest 9.1.1,
Linux). The test:

1. Applied migrations on a fresh DB (`001_core.sql`, `002_approvals.sql`).
2. Created a request through the service layer (schema live).
3. Ran `rollback_migration(conn, "002_approvals.sql")` → tables
   `requests`, `request_events`, `request_idempotency_keys` dropped;
   `002_approvals.sql` removed from `schema_migrations`; P01 tables
   (`leads`, …) untouched.
4. Re-applied via `run_migrations()` → `["002_approvals.sql"]`; engine works
   again.

Also passing: rollback of an unapplied migration returns `False`
(no-op); rollback of `001_core.sql` (no down-step shipped) raises
`FileNotFoundError`.

## Acceptance criteria verdict (REQUIREMENTS.md §8)

| Criterion | Verdict |
|---|---|
| Valid submissions create one request in `draft` | ✅ PASS |
| Invalid submissions rejected with field errors; nothing stored | ✅ PASS |
| Idempotency-key replays; no duplicate records | ✅ PASS |
| Submit routes with the correct amount-based chain | ✅ PASS |
| Wrong-role decisions rejected, state unchanged | ✅ PASS |
| Final approval → `approved`; reject/changes → their states; fulfill works | ✅ PASS |
| SLA breach escalates to `director`; deterministic under fake clock | ✅ PASS |
| Every transition actor-stamped (DB row + log line); timeline consistent | ✅ PASS |
| Dashboard totals reconcile (independent SQL re-computation) | ✅ PASS |
| Illegal transitions raise, never mutate | ✅ PASS |
| Migration down-step rolls back and re-applies | ✅ PASS |

**Gate B verdict: MET.** A synthetic request can be submitted, validated,
routed through role-based approvals, escalated on SLA breach, fulfilled,
and reported on — demonstrated by tests and by the live server above.

## Known defects

None open. Two defects were found and fixed during development:
(1) the migration runner globbed `*.down.sql` as an up-migration
(`db.py` now excludes them); (2) the web settings helper passed
`sla_hours`/`idempotency_ttl_hours` to service functions that do not accept
them (split into per-operation helpers).
