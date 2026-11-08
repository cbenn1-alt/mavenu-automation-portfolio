# Project P04 — Demo

> **Status: Implemented + tested (Gate D ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## Setup (2 minutes)

```bash
cd ~/workspace/mavenu-portfolio
python3 run.py --port 8000 --db /tmp/p04-demo.db
```

## Script

### 1. Seed the demo data

Open `http://localhost:8000/project04` and click **Seed demo data** (or `POST /project04/seed`). The seed inserts 8 leads, 6 missed calls, 6 estimates, 5 invoices, 4 payments, 4 documents — all invented, all dated Oct–Nov 2026. Click it again: nothing is inserted twice.

### 2. Create a query

On `/project04`, save a query named `EST-BY-SERVICE` with this spec:

```json
{"table": "estimates", "dimensions": ["service_type"],
 "metrics": [{"kind": "count"},
             {"kind": "sum", "column": "amount_cents"},
             {"kind": "avg", "column": "amount_cents"},
             {"kind": "rate", "name": "acceptance_rate",
              "numerator": {"column": "state", "value": "accepted"}}],
 "filters": [], "grain": "none"}
```

### 3. Run it

Open the query, set the period **2026-10-01 → 2026-11-08**, and click **Run**. The run page shows:

| service_type | count | sum_amount_cents | avg_amount_cents | acceptance_rate |
|---|---|---|---|---|
| electrical | 1 | 310,000 | 310,000.00 | 1.000000 |
| hvac | 3 | 350,000 | 116,666.67 | 0.333333 |
| plumbing | 2 | 315,000 | 157,500.00 | 0.500000 |

Total: 6 estimates, $975,000. The averages are exact `Decimal` divisions of the integer sums — no floats.

### 4. Drill down (the interesting part)

On the run page, drill down `service_type = hvac`. You get the 3 source rows — EST-SQL-001 ($150,000, accepted, Oct 8), EST-SQL-002 ($80,000, sent, Oct 9), EST-SQL-006 ($120,000, sent, Nov 4). The figure 3 / $350,000 is exactly these three rows; nothing is hidden behind the aggregate. Try drilling down `caller_id` on a missed-calls run — it is rejected: caller identifiers are not readable columns.

### 5. Compare October vs November

Open `/project04/compare`, pick `EST-BY-SERVICE`, period A **2026-10-01 → 2026-10-31**, period B **2026-11-01 → 2026-11-08**. hvac goes 2 → 1 (delta −1, −50%); plumbing and electrical appear only in October, so their B side is blank — no percent is invented for a missing baseline.

### 6. Snapshot it

Back on the run page, click **Snapshot this result**, then check its status: `current`, with matching fingerprints. Now change the data — create a new estimate, or re-seed after editing a row — and check again: the snapshot reports `stale`. That is the feature working.

### 7. Try to break the SQL layer

Create a query with table `"estimates; DROP TABLE leads"`, or a dimension `"state; DROP TABLE estimates; --"`. Both are rejected with `422` at validation, before any SQL is built — and `leads` is still there afterwards. The allow-list is the whole defence, and it is small enough to read in one sitting (`_TABLE_META` in `src/mavenu/sqlops.py`).

## Talking points

- A query is a structured spec, never raw SQL — that is what makes the allow-list enforceable.
- Every figure drills down to its source rows; a number you cannot trace is not a number.
- Failed runs are recorded, not swallowed — the run history shows what was attempted, not just what succeeded.
- Averages and rates are `Decimal` divisions of exact integer aggregates; SQLite's float `AVG()` is never called.
