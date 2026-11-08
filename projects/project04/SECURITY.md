# Project P04 — Security

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Threat model

P04 is a local demo with no network exposure beyond the dev server, no real business data, and no real PII. But it is a **SQL layer**, so the realistic threats are sharper than in the sibling projects: SQL injection through a table, column, dimension, filter, or drill-down value; a hostile spec smuggling a second statement; a filter value becoming a wildcard; a caller reading columns they should not see (caller hashes, raw caller IDs); and silent or forged state changes with no audit trail. All five are addressed below.

## 2. Controls

| Threat | Control | Evidence |
|---|---|---|
| SQL injection via table / column / dimension / metric / filter / drill-down | **Allow-list compiler + parameterized SQL only.** Every identifier in a spec is looked up in `_TABLE_META` before any SQL is built; SQL text is assembled only from validated identifiers inside fixed templates. Every value (filter values, period bounds, drill-down values) is bound as a `?` parameter. There is no code path that interpolates caller-supplied text into SQL. | `test_injection_in_table_name_rejected` (4 parametrised cases incl. `; DROP TABLE`, `UNION SELECT`, NUL byte), `test_injection_in_dimension_rejected` (3 cases), `test_injection_in_metric_column_rejected`, `test_injection_attempts_rejected_at_create` (API 422), `test_compiled_sql_binds_values_as_parameters`; live smoke test: `table: "estimates; DROP TABLE leads"` → 422, tables intact |
| Second-statement smuggling | Spec validation rejects any table/column name that is not an exact allow-list match; `;` and whitespace tricks cannot survive the lookup. SQLite's `execute` also rejects multiple statements. | Same injection tests as above; `test_injection_in_filter_value_rejected_and_tables_intact` asserts the tables still exist and still hold their rows after the attempt |
| Wildcard smuggling through `LIKE` | Filter values for `like` have `%` and `_` escaped (`\%`, `\_`) before binding, with an explicit `ESCAPE '\'` clause — a filter value cannot become a pattern | `test_filter_equals_and_in` and the `like` escaping in `_compile_filters` (`src/mavenu/sqlops.py`) |
| Reading columns that must stay hidden | The allow-list excludes sensitive columns entirely: `caller_id_masked`/`caller_id_hash` are not readable columns, and drill-down returns only `public_id`, `created_at`, and the queried dimension/metric columns. There is no `SELECT *` anywhere in P04. | `test_drill_down_never_returns_caller_hash` |
| Unvalidated input at the boundary | Spec shape validated on create/supersede (unknown keys, bad types, bad enums, bad names); periods validated (ISO dates, start ≤ end, ≤ 366 days); names limited to 1–64 chars `[A-Za-z0-9 _-]`; export format restricted to `csv`/`json`; actor names trimmed and defaulted | `test_validate_spec_*` family (16 tests), `test_create_bad_name_rejected`, `test_create_bad_spec_rejected`, `test_compile_rejects_bad_period`, API 422 tests |
| Silent or forged state changes | Every create/supersede/run/drill-down/snapshot/compare writes an audit row to `sqlops_events` with actor + timestamp; failed runs are recorded with their error text, not swallowed | `test_run_records_error_and_history`, `test_run_query_invalid_period_records_error_run` (API 422 with the run id) |
| Secrets in code | None. No credentials, tokens, or keys anywhere in P04. The demo server binds localhost only. | Grep: no `password`, `token`, `secret`, `api_key` in `src/mavenu/sqlops.py` |

## 3. What P04 does NOT do (by design)

- No raw SQL input — there is no endpoint, form, or parameter that accepts SQL text.
- No writes to the operational tables — P04 reads `leads`, `missed_calls`, `estimates`, `recon_invoices`, `recon_payments`, `docintel_documents`; it writes only its own four tables.
- No authentication/authorisation — the dev server is a single-user demo; do not expose it.
- No deletion of audit rows — events are append-only; the migration down-step drops whole tables, which is a rollback, not a redaction tool.
- No `SELECT *`, no dynamic table names, no string-built `WHERE` clauses — the compiler's output is fully determined by the allow-list and the fixed templates.
