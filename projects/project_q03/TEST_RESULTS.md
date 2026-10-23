# Q03 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23

```
430 passed in 3.58s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_reactivation.py` | 37 | 37 passed |
| `tests/test_attribution.py` | 8 | 8 passed |
| `tests/test_reactivation_api.py` | 11 | 11 passed |
| **Q03 total** | **56** | **56 passed, 0 failed** |
| P01 regression (6 files) | 51 | 51 passed |
| P02 regression (4 files) | 101 | 101 passed |
| Q01 regression (3 files) | 89 | 89 passed |
| Q02 regression (5 files) | 133 | 133 passed |
| **Full suite** | **430** | **430 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_reactivation.py::test_migration_005_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `005_reactivation.sql` applied (in the migrations table), with real
   Q03 data (customer + job + score).
2. `rollback_migration(conn, "005_reactivation.sql")` → returned True;
   `reactivation_customers`, `reactivation_jobs`, `reactivation_outbox`,
   `reactivation_send_log`, `reactivation_holdouts`, `reactivation_events`
   dropped; migration record removed.
3. Verified P01 (`leads`), P02 (`requests`), Q01 (`missed_calls`), and
   Q02 (`estimates`) tables still present.
4. `run_migrations(conn)` re-applied `005_reactivation.sql` cleanly.

## Measured performance criteria (spec §2)

| Criterion | Target | Measured | Verdict |
|---|---|---|---|
| Scoring determinism | 100% across replays | 1,000 scorer replays + 50 full re-scoring runs, all identical | ✅ PASS |
| Suppression recall | 100% (zero leaks across adversarial cases) | 300 customers × mixed flags + mid-sequence flips: 0 suppressed customers with a queued/sent touch; mid-sequence complaint/DNC: adapter never called | ✅ PASS |
| RFM matches hand-computed fixtures | exact | recency 205.0d / freq 2 / monetary 40000¢; score 0.681 == hand computation | ✅ PASS |
| Attribution arithmetic vs hand-computed fixtures | reconcile | treated 1/3, control 1/3, lift 0.0, CI ±0.7544, 1 attributed booking — all match; untraced/post-dated touches excluded | ✅ PASS |
| Segment/dashboard reports reconcile to rows | zero unexplained deltas | per-segment counts + mean dormancy match independent raw-SQL re-computation | ✅ PASS |

## Acceptance criteria verdict (spec §2, Q03)

| Criterion | Verdict |
|---|---|
| Dormancy scoring from recency/frequency/monetary with documented, explainable weights | ✅ PASS |
| Segmented win-back sequences per segment | ✅ PASS |
| Suppression rules (recent complaint, do-not-contact flag, active job) honored absolutely | ✅ PASS |
| Attribution: bookings traced to reactivation touches vs. organic return via holdout comparison on synthetic data | ✅ PASS |
| Synthetic customer histories only | ✅ PASS |
| Migration rollback tested for real | ✅ PASS |
| P01/P02/Q01/Q02 regression-free | ✅ PASS |

## Known defects

None open. Three test-fixture bugs were found during development (a
hand-computed score that used the wrong frequency, a segment-report
fixture whose "active" customer scored 0.414 under the documented
weights, and an event-list index that pointed at the wrong audit event)
— all fixed in the tests, none in production code.
