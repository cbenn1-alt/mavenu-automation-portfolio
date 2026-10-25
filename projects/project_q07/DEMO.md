# Q07 — Demo Script

**All data in this demo is synthetic.** The three shops, their dialects,
and every dollar figure are invented for demonstration.

## Setup (2 minutes)

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py
# open http://localhost:8080/project_q07
```

## Act 1 — Three shops, three dialects (3 min)

1. Open `/project_q07/locations`. Register three locations, each with its
   own schema map:
   - `north` / "North Shop": `{"job_id": "ticket_id", "completed_date": "date",
     "revenue": "rev_usd", "costs": "cost_usd",
     "is_callback": "callback_flag", "tech_days": "tech_days"}`
   - `south` / "South Shop": `{"job_id": "Job #", "completed_date": "Service Date",
     "revenue": "Amount", "costs": "Expenses",
     "is_callback": "CB", "tech_days": "CrewDays"}`
   - `west` / "West Shop": `{"job_id": "id", "completed_date": "completed",
     "revenue": "total", "costs": "parts_labor",
     "is_callback": "return_visit", "tech_days": "days"}`
2. On `/project_q07`, upload one CSV per location for period `2026-09`
   (use the fixtures in `tests/test_kpi_rollup.py`: `NORTH_CSV`,
   `SOUTH_CSV`, `WEST_CSV`). Note the upload summary: north stages 3 and
   quarantines 1 (`invalid_revenue:abc`); south stages 2, quarantines 1
   (`missing_job_id`).

**Talking point:** "The mapping is configured per shop, never assumed —
a new location is a registration, not a deploy."

## Act 2 — The quarantine is loud (2 min)

1. Upload the north CSV with an extra `discount_pct` column. The upload
   reports 1 alert; the good rows still flow.
2. Open `/project_q07/quarantine`: the unknown column sits in quarantine
   with reason `unknown_column:discount_pct`; the bad rows sit there with
   their reasons.

**Talking point:** "Nothing is silently dropped. Drift raises an alert and
is held in quarantine — the good rows keep flowing."

## Act 3 — One dashboard, every number traceable (3 min)

1. Compute for `2026-09`. Open `/project_q07/kpi?period=2026-09`.
2. Read the rollup: revenue 3170.74, gross margin, callback rate,
   average ticket, bookings per tech-day.
3. Click **drill down** on rollup revenue: all 7 staged source rows, with
   location, job, date, revenue, costs, callback flag, tech-days.

**Talking point:** "Every consolidated number traces to the rows that fed
it — that traceability is what makes a rollup trustworthy."

## Act 4 — The definition changes (2 min)

1. `POST /api/kpi/definitions` — new `gross_margin` `v2` that deducts a
   disclosed flat $50 callback rework cost per callback job.
2. `POST /api/kpi/restate` with `period=2026-09` and a reason.
3. `/project_q07/restatements` shows the log; the KPI page shows v2 values;
   drill down still works. The old v1 values are superseded — kept, not
   deleted.

**Talking point:** "Definitions are versioned. A formula change never
rewrites history — the old numbers stay, the log says why."

## Cleanup

Re-uploading any CSV is a safe no-op (batch dedup). To wipe Q07 data, use
the rollback procedure in `RUNBOOK.md`.
