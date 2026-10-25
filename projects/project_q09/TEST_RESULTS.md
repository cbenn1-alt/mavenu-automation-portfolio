# Q09 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/test_dispatch.py tests/test_dispatch_api.py -q`
from the repo root.

## Latest full run — 2026-10-23

The suite was run in three chunks on 2026-10-23 (Q09 files; baseline
files half 1; baseline files half 2), because a single full run's
per-test `tmp_path` databases exceed this host's 512 MB /tmp tmpfs —
an environment limit, not a code issue (same recurring /tmp pressure
recorded in `AGENTS.md`; a disk-backed tmp dir previously wedged a
pytest process in a btrfs writeback stall, so chunking is the standing
procedure).

| Chunk | Result |
|---|---|
| Q09: `test_dispatch.py` + `test_dispatch_api.py` | **36 passed** |
| Baseline files (half 1: approval→kpi_rollup) | **490 passed** |
| Baseline files (half 2: leads→workflow) | **444 passed** |
| **Full suite** | **970 passed, 0 failed** (934 baseline + 36 Q09) |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux. Run date: 2026-10-23.

## Q09 module breakdown

| Module | Tests | Result |
|---|---|---|
| `tests/test_dispatch.py` | 28 | 28 passed |
| `tests/test_dispatch_api.py` | 8 | 8 passed |
| **Q09 total** | **36** | **36 passed, 0 failed** |
| Baseline regression (all prior projects) | 934 | 934 passed |
| **Full suite** | **970** | **970 passed, 0 failed** |

## Measured solver performance (recorded from the run)

250 deterministic synthetic days (seed 3000–3249; 6 techs × 30 jobs),
greedy + local-improvement heuristic vs. nearest-available baseline,
identical hard constraints and pins on both sides:

```
[Q09] baseline comparison over 250 synthetic days:
        mean gap 34.58%, min -12.30%, max 81.79%
```

- Mean gap **+34.58%** (positive = heuristic beats baseline); median
  +35.94%; stdev 16.39%.
- Heuristic wins **246 / 250** days. On 4 days the baseline wins; the
  worst day is **−12.30%** — reported here, not hidden. The heuristic is
  NOT optimal, and the baseline comparison exists to say so honestly.
- The gap compares total plan cost; assigned *sets* can differ between
  the two plans (documented in ARCHITECTURE.md).

Constraint compliance (recorded from the run):

```
[Q09] verified 7500 synthetic dispatches, 0 violations
```

- 250 days × 30 jobs = **7,500 dispatches**; `verify_solution`
  (independent re-check of skill, window, shift, overlap, travel
  consistency, pin compliance) returned empty on every finished plan.
- `run_solver` runs `verify_solution` before persisting and raises
  `DispatchError` on any violation — a bad plan can never be stored.

Override audit (recorded from the run):

- 5/5 overrides (pin, pin→reassign, pin, pin→unpin) logged with reasons;
  100% audit completeness asserted in-suite.
- Empty/short reasons, unknown kinds, and unknown jobs are rejected and
  log nothing.

These numbers describe the heuristic on fabricated fixtures. They are not
a claim about real-world dispatch performance.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_dispatch.py::test_migration_012_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. All migrations applied (incl. `012_dispatch.sql`); demo techs/jobs
   seeded; solver run persisted; override recorded.
2. `rollback_migration(conn, "012_dispatch.sql")` → returned True; all
   seven `dispatch_*` tables dropped; migration record removed.
3. Verified other projects' tables still present (`leads`, `reviews`, …).
4. `run_migrations(conn)` re-applied `012_dispatch.sql` cleanly
   (returned `["012_dispatch.sql"]`).
