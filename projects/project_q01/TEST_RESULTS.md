# Q01 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23

```
241 passed in 2.04s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_urgency_scorer.py` | 20 | 20 passed |
| `tests/test_missed_calls.py` | 41 | 41 passed |
| `tests/test_recovery_queue.py` | 28 | 28 passed |
| **Q01 total** | **89** | **89 passed, 0 failed** |
| P01 regression (6 files) | 51 | 51 passed |
| P02 regression (4 files) | 101 | 101 passed |
| **Full suite** | **241** | **241 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_missed_calls.py::test_migration_003_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `003_missed_calls.sql` applied (in the migrations table).
2. `rollback_migration(conn, "003_missed_calls.sql")` → returned True;
   `missed_calls`, `call_events`, `call_idempotency_keys`,
   `owner_notifications` dropped; migration record removed.
3. Verified P01 (`leads`) and P02 (`requests`) tables still present.
4. `run_migrations(conn)` re-applied `003_missed_calls.sql` cleanly.

## Measured performance criteria (spec §2)

| Criterion | Target | Measured | Verdict |
|---|---|---|---|
| Ingestion p95/event (2,000 synthetic events) | < 5 ms | p50 0.162 ms, **p95 0.279 ms**, p99 0.871 ms | ✅ PASS |
| Scoring determinism across replays | 100% | 10,000/10,000 identical `UrgencyScore` | ✅ PASS |
| Dashboard reconciliation | zero unexplained deltas | all totals match independent raw-SQL re-computation | ✅ PASS |
| Recovery-rate / time-to-callback on seeded fixtures | correct | 1/3, median 60 min vs hand-computed 30/60/120 | ✅ PASS |

## Acceptance criteria verdict (spec §2, Q01)

| Criterion | Verdict |
|---|---|
| CSV + JSON ingestion of missed-call events | ✅ PASS |
| Deterministic, explainable urgency scoring (no black-box claims) | ✅ PASS |
| Prioritized callback queue (score × age decay) | ✅ PASS |
| Outcome tracking `pending → attempted → connected → booked \| lost` | ✅ PASS |
| Caller IDs masked/hashed; raw never stored | ✅ PASS |
| Failure analysis: stale-feed alert stub, repeat-ID anomaly flag, SLA escalation stub | ✅ PASS |
| Migration rollback tested for real | ✅ PASS |
| P01/P02 regression-free | ✅ PASS |

## Known defects

None open. Three test-fixture bugs were found during development
(wrong assumed urgency scores before checking the documented weights;
a queue-ordering assumption that ignored age decay; a rounding
comparison) — all fixed in the tests, none in production code.
