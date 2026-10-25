# Q07 — Test Plan

All fixtures are synthetic (invented location names, job IDs, dollar
figures). No real people, no real businesses, no real financials.

## Fixture design

Intentional schema differences per location (mapping configured, not assumed):

| Location | CSV header (its own dialect) |
|---|---|
| north | `ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days` |
| south | `Job #,Service Date,Amount,Expenses,CB,CrewDays` |
| west | `id,completed,total,parts_labor,return_visit,days` |

Period: `2026-09`.

- **north** (4 rows): 3 good + 1 bad (`rev_usd` = `abc` → `invalid_revenue:abc`).
- **south** (3 rows): 2 good + 1 missing job ID → `missing_job_id`.
- **west** (2 rows): 2 good.

Hand-computed aggregates (literal fixture arithmetic, in
`tests/test_kpi_rollup.py`):

- north: 3 jobs, revenue 1345.50, costs 500.00, callbacks 1, tech-days 2.5
- south: 2 jobs, revenue 825.25, costs 300.00, callbacks 1, tech-days 1.5
- west: 2 jobs, revenue 999.99, costs 395.00, callbacks 1, tech-days 2.5
- rollup: 7 jobs, revenue 3170.74, costs 1195.00, callbacks 3, tech-days 6.5

## Coverage

| Area | Tests |
|---|---|
| Schema-map config | registration requires all canonical fields; rejects unknown fields; re-register idempotent |
| Ingest/validation | good rows staged, bad rows quarantined with reasons (`invalid_revenue:abc`, `missing_job_id`); bad period rejected; unknown location rejected |
| Zero silent drops | staged + row-quarantined == input rows for every location; every quarantine entry has a non-empty reason |
| Schema drift | unknown column → alert + column-level quarantine entry, good rows still flow; missing mapped column → all rows quarantined + alert |
| KPI hand computation | all five KPIs per location + rollup, exact Decimal equality vs `_hand()`; rollup == sum of location inputs; average_ticket is weighted (not the mean of averages) |
| Undefined KPIs | zero-revenue/zero-job shop → revenue 0.00, rates NULL |
| Drill-down lineage | every rollup value traces to all 7 staged rows; recompute from lineage rows reproduces the stored value; location values trace to that location's rows only; unknown value id raises |
| Double counting | same-CSV re-upload is a no-op (`deduped`, no new rows, no duplicate quarantine); different CSV same period = new batch; same job ID in two locations kept (location-scoped) |
| Definition versioning | update supersedes old row (formula text intact), never edits; restatement → 4 log entries (3 locations + rollup), old values preserved with `restatement_id`, new v2 values hand-checked, unchanged KPIs identical, new lineage complete; restatement requires a reason |
| Alerts | resolve flow; double-resolve rejected |
| Migration rollback | apply → use → `rollback_migration` (all `kpi_*` tables gone, other projects' tables intact, migration record removed) → re-apply cleanly |
| API | location create/list; upload; dedupe; bad period rejected; compute roundtrip with hand-checked revenue; dashboard + lineage; quarantine + alerts; definitions + restate (hand-checked v2 value); restate requires reason |
| Web pages | `/project_q07`, `/locations`, `/quarantine`, `/kpi`, `/restatements` render 200 with the synthetic-data banner; KPI detail page shows lineage; upload form roundtrip; compute form 303-redirects |

## How to run

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python -m pytest tests/test_kpi_rollup.py tests/test_kpi_rollup_api.py -q
.venv/bin/python -m pytest tests/ -q   # full suite, no regressions
```
