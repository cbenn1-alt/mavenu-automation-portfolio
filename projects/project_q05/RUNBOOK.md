# Q05 — Runbook

## Start the app

```bash
cd mavenu-portfolio
python3 run.py                                   # http://localhost:8080/
python3 run.py --port 8123 --db /tmp/q05.db     # custom port / database
```

Migration 008 applies automatically on startup.

## Run the tests

```bash
.venv/bin/python -m pytest tests/test_reconciliation.py tests/test_reconciliation_api.py -q  # expect: 56 passed
.venv/bin/python -m pytest tests/ -q                                                         # expect: 693 passed
```

## Operate the demo

1. **Ingest:** open `/project_q05` — paste an invoice CSV or a payment
   CSV and submit. Example invoices:
   ```
   invoice_id,customer,amount,issued_date,due_date
   INV-0001,Acme Test Co,1200.00,2026-09-01,2026-10-01
   INV-0002,Brightfield Services,850.00,2026-09-10,2026-10-10
   ```
   Example payments:
   ```
   payment_id,invoice_ref,customer,amount,paid_date,note
   PAY-0001,INV-0001,Acme Test Co,1200.00,2026-09-28,Check 4410
   ```
   The result page reports inserted / skipped-idempotent / sanitized /
   row-error counts.
2. **Match:** press "Run match" (or `POST /api/reconciliation/run-match`).
   The exact pass runs, then the fuzzy pass; the open-exception queue is
   rebuilt idempotently.
3. **Work the queue:** `/project_q05/exceptions` — open an exception,
   read its suggested next action, then transition it:
   `open → investigating → resolved` (or `written_off` — human only).
4. **Reports:** `/project_q05/reports` — reconciliation summary
   (check the identity line: outstanding − overpaid == invoiced −
   matched-paid), aging buckets, exception aging.
5. **API:** `POST /api/reconciliation/upload`
   (`{"kind":"invoices"|"payments","csv":"...","actor":"..."}`),
   `POST /api/reconciliation/run-match`, `GET /api/reconciliation/summary`,
   `GET /api/reconciliation/aging`,
   `GET /api/reconciliation/exceptions?state=open&kind=...`,
   `GET /api/reconciliation/exceptions/<id>`,
   `POST /api/reconciliation/exceptions/<id>/transition`
   (`{"to_state":"investigating","actor":"..."}`).
6. **Logs:** structured JSON lines on stdout (`reconciliation.*` events);
   every exception transition is also a row in
   `recon_exception_events` (queryable audit trail).

## Re-running a match

Safe and idempotent: re-running `POST /api/reconciliation/run-match`
after re-ingesting the same CSVs produces **zero new matches** and an
identical open-exception queue (tested). Human-touched exceptions
(`investigating`/`resolved`/`written_off`) are never rebuilt.

## Rollback procedure (migration 008)

If the Q05 schema must be removed (bad deploy, schema rework):

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from mavenu.db import get_connection, rollback_migration
conn = get_connection("/path/to/mavenu.db")   # the affected database
print(rollback_migration(conn, "008_reconciliation.sql"))  # True when rolled back
EOF
```

This drops all six `recon_*` tables and removes the migration record, so
`run_migrations()` can re-apply the up-step later. It does **not** touch
any other project's tables (verified in
`test_migration_008_down_step_rolls_back_for_real`).

**Do not roll back a database whose Q05 exceptions/matches you still
need** — the rollback is destructive to Q05 data by design. Export what
you need first (`GET /api/reconciliation/summary`,
`GET /api/reconciliation/exceptions`).
