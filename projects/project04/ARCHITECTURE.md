# Project P04 — Architecture

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Module map

| Module | Responsibility |
|---|---|
| `src/mavenu/sqlops.py` | Service layer: spec validation, allow-list compiler, execution, drill-down, comparison, snapshots, export, demo seed, audit events. |
| `src/mavenu/web.py` | P04 pages + `/api/sqlops/*` JSON endpoints; reuses shared page helpers and the Q05-style form-post → 303-redirect pattern. |
| `src/mavenu/migrations/022_sqlops.sql` | Four tables (see §2). `022_sqlops.down.sql` drops them all. |
| `tests/test_sqlops.py` | 65 service-layer tests incl. the hand-computed fixture oracle and injection-attempt tests. |
| `tests/test_sqlops_api.py` | 15 API + page tests over the WSGI app. |

## 2. Data model (migration 022)

| Table | Purpose |
|---|---|
| `sqlops_queries` | One row per query version: `name`, `version`, `spec_json`, `description`, `status` (`current`/`superseded`), `created_by`, `superseded_by`, timestamps. Unique per `(name, version)`; only one `current` per name. |
| `sqlops_runs` | One row per execution: `query_id`, `query_version`, `spec_json` (the spec as run — a frozen copy), `period_start`, `period_end`, `status` (`ok`/`error`), `rows_returned`, `duration_ms`, `result_json`, `error_text`, `actor`, timestamps. |
| `sqlops_snapshots` | One row per snapshot: `run_id`, `fingerprint` (SHA-256 over spec + period + result rows), `actor`, timestamps. |
| `sqlops_events` | Append-only audit log: `entity_type`, `entity_id`, `event`, `actor`, `detail_json`, `created_at`. |

Foreign keys: runs reference their query; snapshots reference their run. The readable operational tables (`leads`, `missed_calls`, `estimates`, `recon_invoices`, `recon_payments`, `docintel_documents`) are owned by other projects — P04 reads them, never writes them.

## 3. The allow-list compiler

The compiler is the security boundary, and it is deliberately small:

- **Tables** — `_TABLE_META` declares exactly six readable tables, each with its allowed columns, each column's type (`int`/`money`/`text`/`date`/`decimal`), its enum values where applicable, and its date column. A spec naming anything else is rejected before any SQL is built.
- **Identifiers** — every table, column, and dimension name in a spec is looked up in the allow-list; the compiler then emits SQL using only those validated identifiers, inside fixed templates. There is no code path that interpolates caller-supplied text into SQL.
- **Values** — every filter value, period bound, and drill-down value is bound as a `?` parameter. `LIKE` values have `%` and `_` escaped first, so a filter value cannot become a wildcard.
- **Aggregates** — the SQL does only what SQLite does exactly: `COUNT(*)`, `SUM(col)` over integers. Averages and rates are computed in Python from those exact aggregates with `Decimal`: `avg = SUM / COUNT` (6 decimal places), `rate = numerator / COUNT` (6 decimal places), money averages to 2 places. No float division anywhere in the pipeline.
- **Grain** — `day` groups by `date(col)`; `month` by `substr(date(col), 1, 7)`; `week` groups adjacent days into ISO weeks starting Monday (computed in Python from the day buckets, because SQLite has no ISO-week grouping that is also a plain `GROUP BY` on the stored date). An empty result still yields one zero row, so a dashboard never has to guess whether "no data" means "zero" or "broken".

## 4. Versioning and run history

A query is identified by `(name, version)`. Creating a query inserts v1 as `current`. Superseding inserts vN+1 as `current` and marks vN `superseded` — the old row is never updated, so the history is append-only. A run stores a frozen copy of the spec it executed plus the version number, so re-reading an old run never depends on the query's current state. A failed run (bad period, bad spec at run time) is recorded with `status = 'error'` and its error text, then the error is raised — the API returns `422` with the run id, so the failure is inspectable instead of invisible.

## 5. Comparison and snapshots

**Comparison** runs the same query twice (two recorded runs) and joins the results on the dimension key. For each metric it reports `a`, `b`, `delta` (Decimal, null when either side is missing), and `pct` (percent change, null when `a` is 0, missing, or null). A group present in only one period appears with the other side null — it is not dropped, and no percent is invented for it.

**Snapshots** fingerprint the run's spec, period, and result rows (JSON, sorted keys, SHA-256). A status check re-executes the query over the same period and compares fingerprints: `current` if they match, `stale` if the underlying data changed. The check is a read — it does not write a run row.

## 6. Key decisions

1. **Specs as data, not SQL.** The one-line spec in the architecture doc ("SQL analytics layer over operational data") is realised as structured JSON specs. This is what makes the allow-list enforceable: there is nothing to parse, only fields to validate.
2. **Grounded in Q07, Q05, and P01.** KPI definitions (what counts as "accepted", what a rate's numerator is) are documented in the spec, in the Q07 style; the audit event table follows the Q05 event shape; the dashboard-style aggregation follows P01's DB-computed dashboard. P04 adds versioning, drill-down lineage, and snapshots — the pieces the siblings do not have.
3. **Averages and rates never touch a float.** SQLite `AVG()` returns a float; P04 never calls it. `SUM` over integers is exact, and `Decimal` division in Python gives a reproducible 6-decimal string. This is the same rule P03 applies to money.
4. **Drill-down is a first-class feature, not a debug tool.** Every figure on a run page has a drill-down form next to it. The drill-down re-applies the run's filters and period, so the rows it returns are exactly the rows the figure was computed from — plus a 100-row cap with an explicit `truncated` flag.
5. **Failed runs are data.** A run that errors is recorded with its error text. A run history that only shows successes is a lie by omission; P04's shows both.
6. **No performance claims.** Timings are recorded per run (`duration_ms`) on fixtures, and the docs report only those measured fixture timings. There is no production database to benchmark against, and none is claimed.
