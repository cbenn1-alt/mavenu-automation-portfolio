# Project P04 — Evidence Matrix

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

Every claim in this project's docs maps to a test, a file, or a measured run. If a claim has no evidence row, it is not a claim — it is a TODO.

## 1. Functional claims

| Claim | Evidence |
|---|---|
| Queries are structured JSON specs (table, dimensions, metrics, filters, grain, period); no raw SQL accepted | `test_validate_spec_happy_path`, `test_validate_spec_rejects_unknown_spec_keys`, `ARCHITECTURE.md` §3 |
| Spec validation rejects unknown tables/columns/grains, bad filter ops, metric-only dimensions, duplicate dimensions/metric names, sum on text columns, bad rate names, filters on metric columns, filter values outside enums, 0 or 6+ metrics, 3+ dimensions | `test_validate_spec_*` family (16 tests) |
| Queries are versioned; supersede creates a new version, old specs are never edited, old runs resolve to their version | `test_supersede_preserves_old_version`, `test_supersede_unknown_query_rejected`, `test_supersede_via_api` (API) |
| Compiler maps identifiers through an allow-list and binds all values as parameters; no user input reaches SQL text | `test_compiled_sql_binds_values_as_parameters`, `ARCHITECTURE.md` §3 |
| Metrics count/sum/avg/min/max/rate; sums/counts exact integers; averages and rates are `Decimal` divisions in Python, never float division | `test_oracle_estimates_money` (avg 116,666.67), `test_oracle_missed_calls_aggregates` (avg 82.50, urgency 0.658333) |
| Filters eq/ne/in/not_in/gte/lte/like (wildcards escaped)/is_null/is_not_null | `test_filter_equals_and_in`, `_compile_filters` in `src/mavenu/sqlops.py` |
| Grain day/week/month; empty period returns one zero row | `test_grain_day_buckets`, `test_grain_week_groups_adjacent_days`, `test_grain_month_buckets`, `test_empty_period_returns_one_zero_row` |
| Every run recorded with query id + version, spec snapshot, period, status, rows, duration, actor, error text; failed runs recorded | `test_run_records_error_and_history`, `test_run_query_invalid_period_records_error_run` (API 422 with run id) |
| Drill-down returns source rows, capped at 100 with `truncated` flag, filtered by the run's filters and period; never returns caller hashes | `test_drill_down_returns_source_rows`, `test_drill_down_on_period_bucket`, `test_drill_down_respects_run_filters`, `test_drill_down_limit_truncates`, `test_drill_down_never_returns_caller_hash` |
| Comparison: per-group delta and percent; percent null when period A is 0 or missing; single-period groups shown with the other side null | `test_compare_periods_deltas`, `test_compare_pct_null_when_a_is_zero`, `test_compare_api` |
| Snapshots: SHA-256 fingerprint over spec + period + rows; status check re-executes and reports `current`/`stale` | `test_snapshot_current_then_stale_after_change`, `test_snapshot_of_failed_run_rejected`, `test_snapshot_api_and_status` |
| Export CSV (dimensions + metrics header) and JSON (raw results array) | `test_export_csv_and_json`, `test_export_api` |
| Audit log for every create/supersede/run/drill-down/snapshot/compare | `test_run_records_error_and_history`, `sqlops_events` table (`ARCHITECTURE.md` §2) |
| Demo seed idempotent (8 leads, 6 missed calls, 6 estimates, 5 invoices, 4 payments, 4 documents) | `test_seed_is_idempotent` |
| Web UI + JSON API for the whole flow | `tests/test_sqlops_api.py` (15 tests incl. 404/422 paths, form redirects, page renders) |
| Run is deterministic (same query twice → identical results) | `test_run_is_deterministic` |

## 2. Fixture oracle arithmetic (hand-computed)

From `seed_demo_data` in `src/mavenu/sqlops.py`:

| Measure | Arithmetic |
|---|---|
| 6 estimates, $975,000 | hvac 150,000 + 80,000 + 120,000 = 350,000; plumbing 220,000 + 95,000 = 315,000; electrical 310,000. Total 350,000 + 315,000 + 310,000 = 975,000 |
| hvac avg $116,666.67, rate 0.333333 | 350,000 / 3 = 116,666.666… → 116,666.67; 1 accepted of 3 = 0.333333 |
| Month grain Oct $855,000 / Nov $120,000 | Oct: 150,000 + 80,000 + 220,000 + 95,000 + 310,000 = 855,000; Nov: 120,000 |
| 6 missed calls, duration sum 495 | states pending 2, booked 2, lost 1, connected 1; durations sum to 495, avg 82.50; urgency avg 0.658333; min 30, max 150; booked 2 of 6 = 0.333333 |
| 8 leads by service | hvac 3, plumbing 2, electrical 2, roofing 1 |
| 5 invoices $365,000; 4 payments $275,000 | invoices 50,000 + 75,000 + 120,000 + 30,000 + 90,000 = 365,000; payments 50,000 + 75,000 + 120,000 + 30,000 = 275,000 |
| Compare hvac Oct → Nov | count 2 → 1, delta −1, pct −50.000000; sum 230,000 → 120,000, delta −110,000, pct −47.826087; rate 0.500000 → 0.000000 |

## 3. Non-functional claims

| Claim | Evidence |
|---|---|
| Stdlib only, pytest, $0 cost | `src/mavenu/sqlops.py` imports only stdlib + repo modules; no new dependency |
| Parameterized SQL only; allow-list compiler is the only SQL builder | Code review of `src/mavenu/sqlops.py`; injection tests (7 parametrised cases + API attempts) |
| Input validation at every boundary | `test_validate_spec_*` family, `test_create_bad_name_rejected`, `test_compile_rejects_bad_period`, API 422 tests |
| Drill-down never exposes caller identifiers | `test_drill_down_never_returns_caller_hash` |
| Migration 022 reversible; down-step exercised | `test_migration_022_down_step_rolls_back_for_real` |
| Live smoke test (real HTTP) | `TEST_RESULTS.md` §4 — hub 200, P04 200, seed 303, create 201, run 200, drill-down 200, snapshot 201 + status `current`, compare 200, export 200, injection 422 (2026-11-08) |
| Full suite: 1,721 passed / 2 pre-existing date-dependent failures (1,723 collected) | `TEST_RESULTS.md` §1 — both failures reproduced on the pristine tree via `git stash` |

## 4. Honest-status banner (in every doc)

Implemented + tested (Gate D ✓) · synthetic/demo data only · no production deployment · no real clients · no bank approval · no real business data · no performance claims beyond measured fixture timings.
