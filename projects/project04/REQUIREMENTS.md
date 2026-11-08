# Project P04 — Requirements

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Purpose

Give the portfolio a governed SQL analytics layer: analysts (and the other projects' data) get repeatable, versioned, auditable answers over the operational tables — without ever handing raw SQL to a caller, and without ever letting an aggregate hide its source rows. A figure you cannot drill down to is not a figure; it is a rumour.

## 2. Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-01 | A query is a structured spec stored as JSON: `table`, `dimensions` (0–2), `metrics` (1–5), `filters`, `grain` (`none`/`day`/`week`/`month`), `period` (start/end dates). No raw SQL is accepted anywhere | Done |
| FR-02 | Spec validation rejects unknown tables/columns, unknown grains, unknown filter operators, metric-only dimensions, duplicate dimensions/metric names, `sum`/`avg`/`min`/`max` on non-numeric columns, rate metrics without a valid numerator, filters on metric columns, filter values outside a column's enum, and extra spec keys | Done |
| FR-03 | Queries are versioned: create → v1 `current`; supersede → new version `current`, old version `superseded`. Old specs are never edited; old runs still resolve to the version that produced them | Done |
| FR-04 | The compiler maps every identifier through an allow-list and binds every value as a parameter. SQL text is built only from allow-listed identifiers and fixed templates — user input never reaches SQL text | Done |
| FR-05 | Metrics: `count`, `sum`, `avg`, `min`, `max`, `rate`. Sums/counts are exact integers from SQLite; averages and rates are computed in Python from exact aggregates using `Decimal` — never float division | Done |
| FR-06 | Filters: `eq`, `ne`, `in`, `not_in`, `gte`, `lte`, `like` (with `%`/`_` escaped so a filter value cannot become a wildcard), `is_null`, `is_not_null` | Done |
| FR-07 | Grain: `day` buckets by date, `week` groups adjacent days into ISO weeks starting Monday, `month` buckets by `YYYY-MM`. A run with no rows still returns one zero row (count 0, sums 0, avg/rate null) | Done |
| FR-08 | Every run is recorded in `sqlops_runs` with query id + version, spec snapshot, period, status (`ok`/`error`), rows returned, duration in ms, actor, and error text when failed. Failed runs are recorded, not swallowed | Done |
| FR-09 | Drill-down: from any run, pick a dimension + value and get the source rows (capped at 100, flagged `truncated` when capped), filtered by the run's own filters and period. Drill-down never returns caller hashes or raw caller IDs | Done |
| FR-10 | Period-over-period comparison: run one query over two periods; per-group delta and percent change for every metric. Percent change is null when the first period is 0 or missing; a group in only one period shows the other side as null | Done |
| FR-11 | Snapshots: freeze a run's result with a SHA-256 fingerprint over spec + period + result rows. A status check re-executes the query and reports `current` or `stale` | Done |
| FR-12 | Export a run's results as CSV (header = dimensions + metrics, one row per group) or JSON (the raw results array) | Done |
| FR-13 | Audit log: every create/supersede/run/drill-down/snapshot/compare writes an event to `sqlops_events` with actor and timestamp | Done |
| FR-14 | Demo seed: idempotent synthetic data across the six readable tables (leads, missed calls, estimates, invoices, payments, documents); a second seed inserts nothing | Done |
| FR-15 | Web UI + JSON API for queries (create/list/get/supersede), runs (run/list/get), drill-down, snapshots, compare, and export | Done |

## 3. Non-functional requirements

| ID | Requirement | Status |
|---|---|---|
| NFR-01 | Python 3.12 standard library only; pytest; $0 cost | Done |
| NFR-02 | SQLite via the shared `mavenu.db` helpers; parameterized SQL only — the allow-list compiler is the only SQL builder | Done |
| NFR-03 | Money/aggregate math uses `Decimal` end-to-end; averages and rates are strings with 6 decimal places (averages) or 2 (money averages); JSON carries Decimals as strings, never floats | Done |
| NFR-04 | Input validation at every boundary: spec shape, names (1–64 chars, `[A-Za-z0-9 _-]`), periods (ISO dates, start ≤ end, ≤ 366 days), actor names, export format | Done |
| NFR-05 | Every state change and every query run is audit-logged with actor + timestamp; failed runs are logged too | Done |
| NFR-06 | Migration `022_sqlops` is reversible: the down-step drops all four tables and is exercised by test | Done |
| NFR-07 | Synthetic data only — no real business data, no production database, no external service calls; no performance claims beyond measured fixture timings | Done |

## 4. Acceptance criteria (Gate D)

1. All 80 P04 tests pass (65 service + 15 API), including the migration rollback test and the injection-attempt tests.
2. The fixture oracle in `TEST_RESULTS.md` matches hand-computed values exactly (6 estimates, $975,000 total, hvac 3 / $350,000, missed-call duration sum 495).
3. No injection attempt in the test suite reaches the database as SQL text — every hostile spec is rejected at validation, and the tables survive intact.
4. Migration down-step removes all four `sqlops_*` tables and is exercised by test.
5. Live smoke test: real HTTP seed → create → run → drill-down → snapshot → compare → export, hub and P04 pages render 200.
