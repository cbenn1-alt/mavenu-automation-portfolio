# Project P04 — Test Plan

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Strategy

- **Service tests** (`tests/test_sqlops.py`, 65 tests) exercise `sqlops.py` directly against a fresh in-memory SQLite database with migration `022_sqlops` applied, seeded with the synthetic demo fixture. No HTTP, no server.
- **API + page tests** (`tests/test_sqlops_api.py`, 15 tests) exercise the WSGI app through the shared `wsgi_call` helpers: JSON endpoints, form posts, page renders, status codes.
- **Fixture oracle**: one hand-built seed (`seed_demo_data` in `src/mavenu/sqlops.py`) with hand-computed expected aggregates. Every aggregate (counts, sums, averages, rates, month buckets, comparisons) is asserted against the oracle — the tests cannot pass by construction, only by correct behaviour.
- **Determinism check**: the same query run twice produces byte-identical results (test `test_run_is_deterministic`).

## 2. Fixture design (synthetic only)

`seed_demo_data` inserts 8 leads, 6 missed calls, 6 estimates, 5 invoices, 4 payments, 4 documents — all invented, all dated Oct–Nov 2026. Idempotent: a second seed inserts nothing (`test_seed_is_idempotent`).

| Table | Rows | Hand-computed oracle |
|---|---|---|
| leads | 8 | by service: hvac 3, plumbing 2, electrical 2, roofing 1 |
| missed_calls | 6 | states: pending 2, booked 2, lost 1, connected 1; duration sum 495, avg 82.50, urgency avg 0.658333, min 30, max 150, booked_rate 0.333333 |
| estimates | 6 | hvac 3 / $350,000 / avg $116,666.67 / rate 0.333333; plumbing 2 / $315,000 / avg $157,500.00 / rate 0.500000; electrical 1 / $310,000 / avg $310,000.00 / rate 1.000000; total $975,000; month grain Oct $855,000 / Nov $120,000 |
| recon_invoices | 5 | total $365,000 |
| recon_payments | 4 | total $275,000 |
| docintel_documents | 4 | invoice 2, receipt 1, contract 1; accepted 2, needs_review 2 |

## 3. Coverage map (real test names — verify with `pytest --collect-only -q`)

| Area | Tests |
|---|---|
| Spec validation | `test_validate_spec_happy_path`, `test_validate_spec_rejects_unknown_table`, `test_validate_spec_rejects_unknown_column`, `test_validate_spec_rejects_unknown_grain`, `test_validate_spec_rejects_unknown_spec_keys`, `test_validate_spec_rejects_bad_filter_op`, `test_validate_spec_rejects_filter_on_metric_column`, `test_validate_spec_rejects_filter_value_outside_enum`, `test_validate_spec_rejects_metric_only_dimension`, `test_validate_spec_rejects_duplicate_dimensions`, `test_validate_spec_rejects_duplicate_metric_names`, `test_validate_spec_rejects_sum_on_text_column`, `test_validate_spec_rejects_six_metrics`, `test_validate_spec_rejects_zero_metrics`, `test_validate_spec_rejects_three_dimensions`, `test_validate_spec_rejects_bad_rate_name` |
| Query lifecycle | `test_create_and_get_query`, `test_create_duplicate_name_rejected`, `test_create_bad_name_rejected`, `test_create_bad_spec_rejected`, `test_list_queries_only_current_by_default`, `test_supersede_preserves_old_version`, `test_supersede_unknown_query_rejected` |
| Compiler | `test_compile_rejects_bad_period`, `test_compiled_sql_binds_values_as_parameters` |
| Execution + oracle | `test_oracle_estimates_total`, `test_oracle_estimates_money`, `test_oracle_leads_by_service`, `test_oracle_leads_by_state`, `test_oracle_leads_october_vs_november`, `test_oracle_distinct_emails`, `test_oracle_missed_calls_aggregates`, `test_oracle_invoices_and_payments`, `test_oracle_docintel_counts`, `test_grain_day_buckets`, `test_grain_week_groups_adjacent_days`, `test_grain_month_buckets`, `test_filter_equals_and_in`, `test_empty_period_returns_one_zero_row`, `test_rate_null_when_denominator_zero`, `test_result_row_cap_is_enforced`, `test_run_is_deterministic`, `test_run_records_error_and_history` |
| Drill-down | `test_drill_down_returns_source_rows`, `test_drill_down_on_period_bucket`, `test_drill_down_respects_run_filters`, `test_drill_down_rejects_unknown_dimension`, `test_drill_down_limit_truncates`, `test_drill_down_never_returns_caller_hash` |
| Comparison | `test_compare_periods_deltas`, `test_compare_pct_null_when_a_is_zero` |
| Snapshots + export + seed + migration | `test_snapshot_current_then_stale_after_change`, `test_snapshot_of_failed_run_rejected`, `test_export_csv_and_json`, `test_seed_is_idempotent`, `test_migration_022_down_step_rolls_back_for_real` — `022` up applies 4 tables; down drops all 4 |
| Security | `test_injection_in_table_name_rejected` (4 parametrised cases), `test_injection_in_dimension_rejected` (3 cases), `test_injection_in_metric_column_rejected`, `test_injection_in_filter_value_rejected_and_tables_intact` |
| API (15 tests) | `test_pages_render_before_and_after_seed`, `test_create_query_api`, `test_injection_attempts_rejected_at_create`, `test_list_and_get_query`, `test_supersede_via_api`, `test_run_query_api`, `test_run_query_invalid_period_records_error_run`, `test_list_runs_and_get_run`, `test_drilldown_api`, `test_snapshot_api_and_status`, `test_compare_api`, `test_export_api`, `test_page_create_run_and_drilldown_flow`, `test_page_compare_flow`, `test_page_create_with_bad_spec_shows_error` |

## 4. What is NOT tested (deliberate)

- No real business data, no production database — out of scope by design.
- No performance/load testing — the SQLite demo scale (tens of rows) is the target; per-run `duration_ms` is recorded, not benchmarked.
- No multi-user concurrency — single-writer demo; SQLite WAL is the repo default.
- No query-builder UI beyond the JSON spec textarea — the spec is the interface, and the API is the primary consumer.
