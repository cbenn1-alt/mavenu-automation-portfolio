# Q07 — Multi-Location KPI Rollup Pipeline

**Status: Implemented · Tested** — 42 automated tests, all passing
(full suite 869/869: 827 baseline + 42 Q07; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Per-location CSV ingest through **configured** schema maps (canonical field → source column, stored per location — never assumed); row-level validation with quarantine-everything-that-fails (each quarantined row/column carries a reason; zero silent drops); schema-drift handling (unknown columns → column-level quarantine + `schema_drift` alert while good rows still flow; missing mapped columns → all rows quarantined + alert); five KPIs (revenue, gross margin, callback rate, average ticket, bookings per tech-day) as **versioned, documented Decimal formulas** — money never float, rates quantized to 6dp after exact division; per-location + cross-location rollup with **drill-down lineage** (every consolidated number traces to its source staging rows, verified row-by-row); idempotent ingest batches (re-upload = no-op; a different CSV for the same period = new batch, no source_row collision, no double counting); location-scoped job IDs; definition versioning with a restatement log (old values superseded and kept, never edited); migration `010_kpi_rollup.sql` + real rollback test |
| What is SIMULATED | **Simulated** | The three fixture locations ("north", "south", "west") with deliberately different CSV dialects; the bad rows planted in fixtures; the schema-drift demo CSVs |
| What is SYNTHETIC | **Demo** | **All location, job, revenue, cost, and tech-day data is synthetic.** Every figure is fabricated for demonstration. The UI carries the "SYNTHETIC DEMO DATA" banner. This is explicitly **not a substitute for audited financials** |
| What is NOT claimed | — | No production deployment. No real users, no real businesses, no real financials. No platform or employer endorsement |

## Business problem

Firms with 2–5 locations track each shop in its own spreadsheet. The owner
can't answer "which location is actually profitable this month?" without a
day of manual work.

This project is a working rollup pipeline: each location's CSV is ingested
through a schema map configured for *that shop's dialect* (columns differ —
the mapping is configured, not assumed). Rows are validated one by one;
bad rows are quarantined with a reason and never silently dropped. Schema
drift is explicit: an unknown column raises an alert and is held in
quarantine while the good rows still flow; a mapped column gone missing
quarantines the whole batch loudly. Five standardized KPIs are computed
per location and rolled up company-wide — and **every consolidated number
drills down to the exact staging rows that fed it**. KPI definitions are
versioned: when a formula changes, old values are preserved (superseded,
not deleted) and the restatement log records why.

## Implemented capabilities

- **Register** (`kpi_pipeline.register_location`): location code (natural
  idempotency key) + JSON schema map; rejects maps missing canonical
  fields or containing unknown fields
- **Ingest** (`ingest_csv`): label-keyed batches (default label = SHA-256
  of the CSV text); re-upload of the same batch is a no-op; a different
  CSV for the same period is a new batch — no `source_row` collision, no
  double counting; job IDs are location-scoped
- **Validate**: `job_id` present; `completed_date` a real YYYY-MM-DD;
  `revenue`/`costs`/`tech_days` non-negative Decimals; `is_callback` parsed
  from y/yes/true/1 / n/no/false/0 (and 0/1) — anything else is quarantined
  with a reason like `invalid_revenue:abc`
- **Schema drift**: unknown CSV column → column-level quarantine entry
  (`unknown_column:<name>`, source_row NULL) + `schema_drift` alert, good
  rows still flow; mapped column missing from CSV → every row quarantined
  with `missing_mapped_column:<cols>` + alert
- **KPIs** (`kpi_defs.compute_kpi`): `revenue` = Σ revenue;
  `gross_margin` = (Σrevenue − Σcosts)/Σrevenue (NULL when revenue = 0);
  `callback_rate` = callbacks/jobs (NULL when 0 jobs);
  `average_ticket` = Σrevenue/jobs; `bookings_per_tech_day` = jobs/Σtech_days.
  Money quantized to cents, rates to 6dp, all Decimal.
- **Rollup** (`compute_location_kpis`, `compute_rollup`): per-location
  values + cross-location values (`location_id` NULL) with full
  `kpi_lineage` — 100% of rollup totals drill to source rows
- **Restatement** (`update_definition` + `restate_period`): definition
  changes insert a new version row and supersede the old (never edited);
  affected values are superseded (kept, with `restatement_id`) and
  recomputed; `kpi_restatements` logs period, old→new version, reason,
  actor. Demo: `gross_margin` v2 deducts a disclosed flat $50 callback
  rework cost per callback job.
- **Web**: `/project_q07` (dashboard, upload, compute), `/project_q07/locations`
  (schema-map config), `/project_q07/quarantine` (validation + alerts view),
  `/project_q07/kpi` (dashboard with drill-down), `/project_q07/kpi/<id>`
  (drill-down detail), `/project_q07/restatements`; and `/api/kpi/*`
  (locations, upload, compute, dashboard, lineage, quarantine, alerts,
  definitions, restate)
- **Rollback**: `010_kpi_rollup.down.sql` + `db.rollback_migration()`,
  tested for real (apply → use → roll back → re-apply)

## What is simulated (labeled, not hidden)

- **The data**: every location, job ID, dollar figure, and tech-day count
  is invented. Demo fixtures must never be presented as real business
  financials.
- **The rework cost**: `gross_margin` v2's $50-per-callback deduction is a
  disclosed placeholder assumption, not a measured cost.

## What is not claimed

- No production deployment, no real users, no real businesses.
- **Not a substitute for audited financials.** Real deployments need real
  accounting review of the KPI definitions (see each definition's
  includes/excludes, stored in `kpi_definitions` and shown on the locations
  page).
- **Never silently drops data.** Anything the pipeline cannot stage lands
  in quarantine with a reason — asserted by tests, including column-level
  drift entries.

## What each metric includes / excludes (documented assumptions)

- **revenue**: includes recorded pre-tax revenue on completed, staged jobs
  only; excludes quarantined rows and work not in the jobs CSV.
- **gross_margin**: includes job-level revenue and costs as recorded in
  the source CSV (the schema map says which columns); excludes overhead
  not in the CSV (rent, office salaries), tax, quarantined rows.
- **callback_rate**: includes staged rows whose `is_callback` flag is true
  (schema map documents the source column); excludes quarantined rows.
- **average_ticket**: revenue ÷ completed jobs; callbacks count as jobs.
- **bookings_per_tech_day**: completed jobs ÷ recorded tech-days (one
  technician-day per the schema map's source column).

## Quick start (demo)

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python -m pytest tests/test_kpi_rollup.py tests/test_kpi_rollup_api.py -q
.venv/bin/python run.py   # serves the WSGI app; visit /project_q07
```

See `DEMO.md` for the scripted walkthrough.
