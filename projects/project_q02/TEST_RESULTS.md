# Q02 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23

```
374 passed in 3.91s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_estimates.py` | 74 | 74 passed |
| `tests/test_estimate_templates.py` | 12 | 12 passed |
| `tests/test_cadence.py` | 21 | 21 passed |
| `tests/test_estimate_reports.py` | 7 | 7 passed |
| `tests/test_estimates_api.py` | 19 | 19 passed |
| **Q02 total** | **133** | **133 passed, 0 failed** |
| P01 regression (6 files) | 51 | 51 passed |
| P02 regression (4 files) | 101 | 101 passed |
| Q01 regression (3 files) | 89 | 89 passed |
| **Full suite** | **374** | **374 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_estimates.py::test_migration_004_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `004_estimates.sql` applied (in the migrations table).
2. `rollback_migration(conn, "004_estimates.sql")` → returned True;
   `estimates`, `estimate_events`, `cadence_rules`, `message_templates`,
   `estimate_outbox`, `send_log`, `estimate_idempotency_keys` dropped;
   migration record removed.
3. Verified P01 (`leads`), P02 (`requests`), and Q01 (`missed_calls`)
   tables still present.
4. `run_migrations(conn)` re-applied `004_estimates.sql` cleanly,
   including the seeded day-2/7/14 rules and three templates.

## Measured performance criteria (spec §2)

| Criterion | Target | Measured | Verdict |
|---|---|---|---|
| Illegal transitions rejected | 100% (34/34) | 34/34 raise `InvalidTransition`, state unchanged | ✅ PASS |
| Duplicate outbox rows across scheduler replays | zero across 1k replays | 1,001 runs → 3 rows, 3 unique keys, 0 new rows | ✅ PASS |
| Aging report reconciles to estimate rows | zero unexplained deltas | open count/value and every bucket match independent raw-SQL re-computation | ✅ PASS |
| Template render p95 | < 2 ms | p50 0.014 ms, **p95 0.026 ms**, p99 0.075 ms (5,000 renders) | ✅ PASS |

## Acceptance criteria verdict (spec §2, Q02)

| Criterion | Verdict |
|---|---|
| Estimate lifecycle `draft → sent → viewed → followed_up → accepted \| declined \| expired`, transitions enforced in code with timestamps + actor stamps | ✅ PASS |
| Configurable follow-up cadence (day 2 / 7 / 14) with per-step message templates | ✅ PASS |
| Stop rules (accepted / declined / unsubscribed) | ✅ PASS |
| Decline-reason capture | ✅ PASS |
| Win/loss reporting by service type and estimator | ✅ PASS |
| Failure analysis: idempotency keys on outbox rows; UTC storage; render-time template validation | ✅ PASS |
| Migration rollback tested for real | ✅ PASS |
| P01/P02/Q01 regression-free | ✅ PASS |

## Known defects

None open. Two test-fixture bugs were found during development (a
hand-computed accept-rate that miscounted a bucket, and a timezone test
that measured elapsed time against the wrong anchor) — both fixed in the
tests, none in production code.
