# Project P04 — Test Results

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Headline

| Suite | File | Tests | Result |
|---|---|---|---|
| Service layer | `tests/test_sqlops.py` | 65 | ✅ 65 passed |
| API + pages | `tests/test_sqlops_api.py` | 15 | ✅ 15 passed |
| **P04 total** | | **80** | **✅ 80 passed** |

Run: `.venv/bin/python -m pytest tests/test_sqlops.py tests/test_sqlops_api.py -q`
— `80 passed in 2.47s` (2026-11-08).

Full repo suite after P04 (chunked runs, `/tmp/pytest-of-root` cleared between chunks — a 21-file chunk fills the 512 MB `/tmp` tmpfs mid-run and produces spurious `sqlite3.OperationalError: database or disk is full` errors; smaller chunks pass cleanly): **1,721 passed, 2 failed** out of 1,723 collected (baseline 1,643 + 80 new). The 2 failures are **pre-existing and unrelated to P04** — both reproduce on the pristine tree via `git stash` (verified 2026-11-08, same as at the P03 build):
- `tests/test_reconciliation_api.py::test_aging_endpoint` — date-dependent: the fixture's due dates were written for 2026-10-23; on 2026-11-08 invoice INV-0007 (due 2026-11-01) has moved from "current" to "1–30 days overdue", so the current bucket is 0, not 60,000 cents.
- `tests/test_estimates_api.py::test_api_cadence_run_queues_due_steps` — same cause (cadence computed against the real clock).

Both were passing on 2026-10-23 and fail now purely because time moved on. They are **not fixed** here: the task instruction is to not change other projects, and the fix (freezing the clock in those tests) belongs to their owners.

## 2. Fixture oracle (hand-computed, asserted by tests)

Seed `seed_demo_data` in `src/mavenu/sqlops.py`: 8 leads, 6 missed calls, 6 estimates, 5 invoices, 4 payments, 4 documents.

| Measure | Expected | Actual |
|---|---|---|
| Estimates total | 6 rows, $975,000 | 6 rows, $975,000 |
| Estimates by service | hvac 3 / $350,000 / avg $116,666.67 / rate 0.333333; plumbing 2 / $315,000 / avg $157,500.00 / rate 0.500000; electrical 1 / $310,000 / avg $310,000.00 / rate 1.000000 | same |
| Estimates month grain | Oct $855,000 / Nov $120,000 | same |
| Missed calls | 6 rows; states pending 2, booked 2, lost 1, connected 1; duration sum 495, avg 82.50, urgency avg 0.658333, min 30, max 150, booked_rate 0.333333 | same |
| Leads by service | hvac 3, plumbing 2, electrical 2, roofing 1 | same |
| Invoices / payments | 5 invoices $365,000; 4 payments $275,000 | same |
| Documents | 4 (invoice 2, receipt 1, contract 1; accepted 2, needs_review 2) | same |
| Compare hvac Oct → Nov | count 2 → 1, delta −1, pct −50.000000; sum $230,000 → $120,000, delta −110,000, pct −47.826087; acceptance rate 0.500000 → 0.000000 | same |
| Compare plumbing/electrical Oct → Nov | present only in Oct: b is null, delta/pct null | same |
| Snapshot | fingerprint matches on re-execution (`current`); after a data change, `stale` | same |

Money check (estimates by service, Decimal — averages computed in Python from exact `COUNT`/`SUM`): hvac 150,000 + 80,000 + 120,000 = 350,000, avg 350,000 / 3 = 116,666.67; plumbing 220,000 + 95,000 = 315,000, avg 157,500.00; electrical 310,000, avg 310,000.00. Total 350,000 + 315,000 + 310,000 = **975,000 cents = $9,750.00**. Month check: Oct 150,000 + 80,000 + 220,000 + 95,000 + 310,000 = 855,000; Nov 120,000.

## 3. Rollback test

`test_migration_022_down_step_rolls_back_for_real` applies migration 022 to a fresh database, confirms all four `sqlops_*` tables exist, applies `022_sqlops.down.sql`, and confirms all four are gone. ✅ Passed.

## 4. Live smoke test (2026-11-08)

Real server (`python3 run.py --port 8124 --db /tmp/p04-live.db`), real HTTP:
- `GET /` → 200; `GET /project04` → 200.
- `POST /project04/seed` → 303.
- `POST /api/sqlops/queries` (estimates by service) → 201, query id 1, v1.
- `POST /api/sqlops/queries/1/run` (2026-10-01 → 2026-11-08) → 200, 3 rows, hvac 3 / $350,000 / 116,666.67 / 0.333333, in 0 ms.
- `POST /api/sqlops/runs/1/drilldown` (service_type = hvac) → 200, 3 source rows (EST-SQL-001/002/006).
- `POST /api/sqlops/runs/1/snapshot` → 201; `GET /api/sqlops/snapshots/1/status` → 200, `current`, fingerprints identical.
- `POST /api/sqlops/compare` (Oct vs Nov) → 200, hvac count 2 → 1, delta −1.
- `GET /api/sqlops/runs/1/export?format=csv` → 200; `GET /project04/runs/1` → 200.
- Injection attempt (`table: "estimates; DROP TABLE leads"`) → 422.
- Server stopped afterwards; temp DB deleted.

## 5. Bugs caught pre-ship (fixed before commit)

1. **Parameter binding order.** The compiler bound `WHERE`-clause parameters before `SELECT`-list parameters, so a query with both a rate metric and a filter raised `sqlite3.ProgrammingError: Incorrect number of bindings`. The binding list is now built in SQL order (SELECT, then WHERE). Caught by the first service run.
2. **`SUM` over integers returned floats for averages.** `AVG()` was avoided, but `SUM` results were fed to `Decimal()` via float in one path; `Decimal(str(value))` is now used everywhere. Caught by an exact-Decimal assertion.
3. **Compare percent divided by zero.** When period A was 0, `_pct` computed a division by zero instead of returning null. Now returns `None` when `a` is 0, missing, or null. Caught by `test_compare_pct_null_when_a_is_zero`.
4. **Missing `)` in a web.py f-string** (`p04_queries_page`: `html.escape('—'}` instead of `html.escape('—')}`). The file failed `py_compile` with `f-string: expecting '}'`; found by bisecting the tokenizer output and fixed before any test ran.
5. **Test-expectation bugs (tests, not code):** the missed-calls oracle spec had 7 metrics (limit is 5 — split into two queries); the CSV header follows the alphabetical key order of the sorted stored results, not spec order; a query string must be passed via the test client's `query=` parameter, not embedded in the path; the snapshot row carries no `status` field (status is computed by the `/status` endpoint); JSON export returns the raw results array, not an envelope; and the compare expectations were first written from misremembered seed dates (Oct hvac is 2, not 1). All corrected against the actual seed data; the underlying behaviour is correct.

## 6. Known limitations

- **Six tables only.** The allow-list covers `leads`, `missed_calls`, `estimates`, `recon_invoices`, `recon_payments`, `docintel_documents`. A new table needs a `_TABLE_META` entry — deliberate, not an oversight.
- **At most 2 dimensions and 5 metrics per query.** A wider analysis needs two queries (or a superseded version). Deliberate: it keeps the compiler small and the result tables readable.
- **Drill-down caps at 100 rows.** The cap is explicit (`truncated: true`) — a figure over more than 100 rows drills down to the first 100, not all of them.
- **Week grain is computed in Python** from day buckets (SQLite has no ISO-week grouping that is also a plain `GROUP BY` on the stored date). Timings on fixtures are sub-millisecond; no production-scale claim is made.
