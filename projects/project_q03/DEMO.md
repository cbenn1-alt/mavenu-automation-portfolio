# Q03 — Demo Walkthrough

Everything below uses synthetic fixture data. Run the app:

```bash
cd mavenu-portfolio
MAVENU_DB_PATH=/tmp/q03-demo.db .venv/bin/python run.py --port 8125
# open http://localhost:8125/project_q03
```

## 1. Create customers and job history

```bash
B=http://localhost:8125
curl -s -X POST $B/api/reactivation/customers \
  -H 'Content-Type: application/json' \
  -d '{"customer_name": "Acme Test Co"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['public_id'])"
# -> CUS-000001

curl -s -X POST $B/api/reactivation/customers/CUS-000001/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_ref": "JOB-101", "service_type": "hvac",
       "job_date": "2025-06-01T10:00:00+00:00", "amount_cents": 45000}'

curl -s -X POST $B/api/reactivation/customers \
  -H 'Content-Type: application/json' -d '{"customer_name": "Beta Demo LLC"}'
curl -s -X POST $B/api/reactivation/customers/CUS-000002/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_ref": "JOB-201", "service_type": "plumbing",
       "job_date": "2026-10-20T10:00:00+00:00", "amount_cents": 80000}'
```

Add a suppressed customer to see the guarantee in action:

```bash
curl -s -X POST $B/api/reactivation/customers \
  -H 'Content-Type: application/json' -d '{"customer_name": "Gamma Fixture Inc"}'
curl -s -X POST $B/api/reactivation/customers/CUS-000003/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_ref": "JOB-301", "service_type": "electrical",
       "job_date": "2025-01-15T10:00:00+00:00", "amount_cents": 120000}'
curl -s -X POST $B/api/reactivation/customers/CUS-000003/suppression \
  -H 'Content-Type: application/json' -d '{"do_not_contact": true}'
```

## 2. Score and segment

```bash
curl -s -X POST $B/api/reactivation/score | python3 -m json.tool | head -20
curl -s $B/api/reactivation/segments | python3 -m json.tool
```

Expect: Acme Test Co → `churned` (score ≈ 0.925); Beta Demo LLC →
`cooling`; Gamma Fixture Inc → `churned` with a suppression flag.
Open `/project_q03` to see the segment table and the documented scoring
formula.

## 3. Run the win-back and watch the outbox

```bash
curl -s -X POST $B/api/reactivation/winback-run | python3 -m json.tool
curl -s $B/api/reactivation/outbox | python3 -m json.tool | head -30
```

Gamma Fixture Inc appears in `skipped` with
`suppressed:do_not_contact` — zero touches queued. Open
`/project_q03/outbox` to read the rendered copy (note the
"(demo touch; nothing was sent)" footer).

## 4. Mid-sequence complaint (the adversarial demo)

```bash
# Queue touches first (already done above), then record a complaint for
# Acme Test Co *before* flushing:
curl -s -X POST $B/api/reactivation/customers/CUS-000001/complaint
curl -s -X POST $B/api/reactivation/outbox/flush | python3 -m json.tool
```

Acme's queued touch is marked `suppressed`, not sent — the stub adapter
is never called. Verify on `/project_q03/suppression`: the customer, the
reason, and the `touch.suppressed_at_flush` event.

## 5. Attribution on synthetic data

```bash
curl -s -X POST $B/api/reactivation/holdout \
  -H 'Content-Type: application/json' \
  -d '{"run_name": "demo-holdout-1", "holdout_pct": 34}' | python3 -m json.tool
curl -s "$B/api/reactivation/attribution?run_name=demo-holdout-1&window_start=2026-10-01T00:00:00%2B00:00&window_end=2026-10-31T23:59:59%2B00:00" \
  | python3 -m json.tool
```

The report shows treated/control return rates, the lift, and the 95% CI —
always with the `SYNTHETIC-DATA ILLUSTRATION` label. To see a traced
booking, record a `booking_source: "reactivation"` job for a treated
customer after flushing a touch, then re-run the report.

## 6. What to point at

- **Deterministic scoring**: `GET /api/reactivation/scoring-info` shows
  the exact weights, caps, and segment boundaries — then re-run
  `POST /api/reactivation/score` and watch the numbers not move.
- **Absolute suppression**: `/project_q03/suppression` — every flagged
  customer, its reason, and the full event trail.
- **Honest outbox**: the outbox page states plainly that v1 sends
  nothing; the send log proves the pipeline shape without delivery.
