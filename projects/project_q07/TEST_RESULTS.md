# Q07 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23

```
869 passed in 15.78s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_kpi_rollup.py` | 27 | 27 passed |
| `tests/test_kpi_rollup_api.py` | 15 | 15 passed |
| **Q07 total** | **42** | **42 passed, 0 failed** |
| Baseline regression (all prior projects) | 827 | 827 passed |
| **Full suite** | **869** | **869 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux 7.0.0-39-generic. Run date: 2026-10-23.

Note: one intermediate full-suite run on 2026-10-23 errored with
`sqlite3.OperationalError: database or disk is full` — `/tmp` (512 MB
tmpfs) had filled with stale pytest debris, unrelated to the code. After
clearing `/tmp/pytest-of-root`, the suite re-ran clean: **869 passed**.
(The same recurring /tmp issue is recorded in `AGENTS.md`.)

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_kpi_rollup.py::test_migration_010_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `010_kpi_rollup.sql` applied (in the migrations table); location
   registered, definitions seeded, north CSV ingested (3 staged, 1
   quarantined), location KPIs computed.
2. `rollback_migration(conn, "010_kpi_rollup.sql")` → returned True;
   all eleven `kpi_*` tables dropped; migration record removed.
3. Verified other projects' tables still present (`leads`,
   `er_contacts`, …).
4. `run_migrations(conn)` re-applied `010_kpi_rollup.sql` cleanly, and a
   fresh location registration worked.

## Measured performance criteria (spec §2)

| Criterion | Target | Measured | Verdict |
|---|---|---|---|
| Zero silent drops | every quarantined row has a reason | all 9 input rows across 3 fixtures either staged (7) or quarantined with a non-empty reason (2); column-drift entries carry `unknown_column:<name>` | PASS |
| KPI values match hand computations exactly | Decimal equality | all 5 KPIs × 3 locations + rollup equal `_hand()` literals exactly | PASS |
| 100% of rollup totals drill to source rows | verified row-by-row | each of the 5 rollup values traces to all 7 staged rows; recompute from lineage rows reproduces the stored value | PASS |
| Schema drift: unknown column | quarantine + alert, good rows flow | 1 alert, 1 column-level quarantine entry, 3/3 good rows staged | PASS |
| Schema drift: missing mapped column | quarantine + alert | 4/4 rows quarantined with `missing_mapped_column:cost_usd`, 1 alert, 0 staged | PASS |
| Double-counting prevention | location-scoped IDs, dedup keys | same-CSV re-upload is a no-op (`deduped`, 0 new rows, 0 duplicate quarantine rows); different CSV same period = new batch; same job ID in 2 locations kept and counted in both | PASS |
| Definition versioning | versioned definitions, restatement log | old formula row superseded (text intact), never edited; restatement → 4 log entries (north/south/west/rollup), old values preserved with `restatement_id`, v2 margin hand-checked: north `(795.50/1345.50)` quantized 6dp | PASS |
| Migration rollback | real down-step | apply → use → roll back → re-apply (see above) | PASS |
| Weighted rollup correctness | rollup ≠ mean of location averages | average_ticket 452.96 ≠ mean-of-averages (verified different) — rollup aggregates rows, not averages | PASS |
| Undefined KPIs | NULL, not crash | zero-job shop → revenue `0.00`, all rates `None` | PASS |

## Fixture ledger (measured, 2026-10-23 — verified against live output)

- north (3 staged / 1 quarantined): revenue 1345.50, costs 500.00,
  margin v1 0.628391, callback rate 0.333333, avg ticket 448.50,
  bookings/tech-day 1.200000
- south (2 staged / 1 quarantined): revenue 825.25, costs 300.00,
  margin v1 0.636474, callback rate 0.500000, avg ticket 412.62,
  bookings/tech-day 1.333333
- west (2 staged / 0 quarantined): revenue 999.99, costs 395.00,
  margin v1 0.604996, callback rate 0.500000, avg ticket 500.00,
  bookings/tech-day 0.800000
- rollup (7 staged): revenue 3170.74, costs 1195.00, margin v1 0.623116,
  callback rate 0.428571, avg ticket 452.96, bookings/tech-day 1.076923
- restatement demo: gross_margin v2 (flat $50/callback deduction) —
  north 0.591230, south 0.575886, west 0.554996; v1 values superseded,
  preserved, and logged
