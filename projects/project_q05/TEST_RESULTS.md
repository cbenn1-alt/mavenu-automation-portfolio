# Q05 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23

```
693 passed in 21.04s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_reconciliation.py` | 45 | 45 passed |
| `tests/test_reconciliation_api.py` | 11 | 11 passed |
| **Q05 total** | **56** | **56 passed, 0 failed** |
| Baseline regression (all prior projects) | 637 | 637 passed |
| **Full suite** | **693** | **693 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux. Run date: 2026-10-23.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_reconciliation.py::test_migration_008_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `008_reconciliation.sql` applied (in the migrations table); fixture
   ingested and matched (7 matches, 9 open exceptions).
2. `rollback_migration(conn, "008_reconciliation.sql")` → returned True;
   all six `recon_*` tables dropped; migration record removed.
3. Verified P01 (`leads`) and prior-project tables still present.
4. `run_migrations(conn)` re-applied `008_reconciliation.sql` cleanly.

## Measured performance criteria (spec §2)

| Criterion | Target | Measured | Verdict |
|---|---|---|---|
| 100% precision on exact-pass fixtures | no false exact matches | deceptive fixture (INV-01/INV-1, nonexistent ref): 2/2 correct, 0 false | PASS |
| Fuzzy pass routes 100% of below-threshold candidates to review | zero silent auto-matches | 5/5 sub-threshold candidates → review; 0 match rows created for them | PASS |
| Reports reconcile to the row | totals == independent SQL | summary matches raw-SQL recomputation exactly; identity `outstanding − overpaid == invoiced − matched-paid` holds (1800.00 == 1800.00) | PASS |
| Re-ingest produces zero duplicate matches | 0 new matches, identical queue | re-ingest + re-match: 0 new matches, match count and open-exception count unchanged | PASS |
| Threshold boundary | 0.75 auto / 0.74 review | `decide()` boundary tests pass | PASS |
| Decimal-only money | no float in amounts | `0.29`→29c (float would be 28.99…); all summary values are `Decimal` | PASS |
| CSV injection neutralized | no live formula cells | `=`,`+`,`-`,`@` cells stored with leading `'`; formula amounts rejected as row errors | PASS |
| Exception state machine | all legal moves pass, all illegal rejected | 8-case parametrized illegal-transition matrix all rejected; actor stamps + history verified | PASS |
