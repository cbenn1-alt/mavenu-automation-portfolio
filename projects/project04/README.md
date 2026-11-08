# Project P04 — SQL Operations Intelligence

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval, no real business data, no performance claims beyond measured timings on fixtures.

## What it does

P04 is a SQL analytics layer over the portfolio's operational SQLite data. A query is a **structured spec** — table, dimensions, metrics, filters, grain, period — stored as JSON and versioned. It is **never raw SQL from a caller**. The compiler maps every identifier through an allow-list and binds every value as a parameter, so **no user input ever reaches SQL text**. Averages and rates are computed in Python from exact `COUNT`/`SUM` aggregates, so no figure is ever a float division. Every figure drills down to its source rows, every execution is recorded (including failed ones), and snapshots report current vs. stale by re-executing the query and comparing fingerprints.

Three capabilities sit on top of the query engine:

- **Versioned saved queries** — create a query (v1); superseding it creates a new version and marks the old one `superseded`. Old specs are never edited, and old runs still resolve to the version that produced them.
- **Period-over-period comparison** — run one query over two periods; per-group deltas and percent change, with percent change left blank (never invented) when the first period is 0 or missing.
- **Snapshots** — freeze a run's result with a SHA-256 fingerprint over spec + period + rows; a status check re-executes and reports `current` or `stale`.

## Documents in this folder

| Doc | Purpose |
|---|---|
| `REQUIREMENTS.md` | Functional + non-functional requirements, acceptance criteria |
| `ARCHITECTURE.md` | Module map, data model, compiler design, key decisions |
| `TEST_PLAN.md` | Test strategy, fixture design, coverage map |
| `TEST_RESULTS.md` | Exact test counts and the hand-computed fixture oracle |
| `SECURITY.md` | Threat model, SQL safety, input validation, audit logging |
| `RUNBOOK.md` | How to run, operate, and roll back (migration down-step) |
| `DEMO.md` | Demo script against the synthetic fixture |
| `EVIDENCE_MATRIX.md` | Claim → artifact mapping |

## Quick start

```bash
python3 run.py --port 8000 --db data/app.db
```

Then open **P04** (`/project04`), click **Seed demo data**, and create a query — or use the JSON API:

```bash
curl -X POST localhost:8000/api/sqlops/queries -H 'Content-Type: application/json' \
  -d '{"name":"EST-BY-SERVICE","spec":{"table":"estimates","dimensions":["service_type"],"metrics":[{"kind":"count"},{"kind":"sum","column":"amount_cents"}],"filters":[],"grain":"none"},"actor":"demo"}'

curl -X POST localhost:8000/api/sqlops/queries/1/run -H 'Content-Type: application/json' \
  -d '{"period_start":"2026-10-01","period_end":"2026-11-08","actor":"demo"}'
```

## Modules

- **Service** — `src/mavenu/sqlops.py`: spec validation, the allow-list compiler, execution, drill-down, comparison, snapshots, export, demo seed.
- **Web + API** — `src/mavenu/web.py`: P04 pages (`/project04`, `/project04/queries`, `/project04/runs`, `/project04/compare`) + `/api/sqlops/*` JSON endpoints.
- **Migration** — `src/mavenu/migrations/022_sqlops.sql` (4 tables; `022_sqlops.down.sql` drops them).
- **Tests** — `tests/test_sqlops.py` (65 service tests) + `tests/test_sqlops_api.py` (15 API + page tests). **80 total, all passing.**
