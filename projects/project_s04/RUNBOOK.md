# S04 — Runbook

## Prerequisites

- Repo venv: `cd ~/workspace/mavenu-portfolio && .venv/bin/python`
- Python 3.12 stdlib only at runtime; SQLite; $0 spend; no network.

## 1. Seed the synthetic case (fastest path to a working register)

```bash
.venv/bin/python run.py &          # start the app (default :8080)
curl -s -X POST localhost:8080/api/custody/seed | python3 -m json.tool
# or click "Seed synthetic case" on /project_s04
```

Seeds CASE-2026-SYN-047: 4 items, 3 completed transfers, 1 rejected
hash-mismatch drill (resolved incident), 3 dispositions.

## 2. Walk the workflow end-to-end (API)

```bash
# Intake
curl -s -X POST localhost:8080/api/custody/items \
  -H 'Content-Type: application/json' -d '{
    "case_id": 1, "tag": "EV-047-005",
    "description": "Synthetic practice item",
    "storage_location": "Locker A-3",
    "acquisition_sha256": "'$(python3 -c "import hashlib; print(hashlib.sha256(b'synthetic practice bytes').hexdigest())")'",
    "acquired_by": "Case Officer A. Reyes",
    "acquisition_ref": "ACQ-SYN-047-005"}' | python3 -m json.tool

# Transfer (dual hash verification)
curl -s -X POST localhost:8080/api/custody/transfers \
  -H 'Content-Type: application/json' -d '{
    "item_id": 5, "sender": "Case Officer A. Reyes",
    "receiver": "Custodian J. Okafor", "purpose": "practice move",
    "destination_location": "Locker B-1"}' | python3 -m json.tool
curl -s -X POST localhost:8080/api/custody/transfers/5/hash-out \
  -H 'Content-Type: application/json' -d '{"hash_out": "<the acquisition sha256>"}'
curl -s -X POST localhost:8080/api/custody/transfers/5/hash-in \
  -H 'Content-Type: application/json' -d '{"hash_in": "<the acquisition sha256>"}'

# Verify the chain + access coverage
curl -s localhost:8080/api/custody/verify | python3 -m json.tool

# Disposition
curl -s -X POST localhost:8080/api/custody/dispositions \
  -H 'Content-Type: application/json' -d '{
    "item_id": 5, "disposition": "archived",
    "authorized_by": "Case Officer A. Reyes",
    "authorization_ref": "AUTH-SYN-047-D"}'
```

## 3. Verify integrity after any suspicion

```bash
curl -s localhost:8080/api/custody/verify
# chain_verification.ok must be true; dual_hash_verification.violations
# must be []; access_coverage.gaps must be [].
```

Or per item: `GET /api/custody/items/<id>` → `chain_verdict`.

## 4. Spot-check procedure (the paper process, run against the data)

1. Pick an item (register page or `GET /api/custody/items`).
2. Read its intake entry: tag, acquisition SHA-256, acquirer.
3. Walk its custody entries in seq order; confirm each event has an
   actor and a timestamp.
4. For every transfer: hash-out and hash-in both equal the acquisition
   hash; the location after completion matches the destination.
5. For terminal items: a disposition record exists with authorizer +
   reference.
6. Confirm the access log has an entry for every handling.
7. Run `GET /api/custody/verify` and record the verdict.

Programmatic equivalent: `custody.spot_check(conn, item_id=...)`.

## 5. Rollback procedure

The migration ships a tested down-step. To roll back the S04 schema
(destroys all custody data — use a backup first):

```python
import sys; sys.path.insert(0, "src")
from mavenu.db import get_connection, rollback_migration
conn = get_connection("path/to/app.db")
rollback_migration(conn, "017_custody.sql")   # drops all 7 custody tables,
                                              # clears the schema_migrations record
conn.close()
```

Rollback is exercised for real by
`tests/test_custody.py::TestMigrationRollback::test_rollback_for_real`
(run date 2026-10-23, Python 3.12.3 / pytest 9.1.1 / Linux): tables
dropped, record cleared, re-apply clean.

## 6. Incident response (hash mismatch)

1. The transfer is already rejected and the item quarantined — do not
   force it through.
2. Re-hash the physical/digital item independently; compare to the
   acquisition hash.
3. If the item matches the acquisition hash: the error is in the
   transfer paperwork — resolve the incident with a written explanation
   (`resolve_incident`), then start a new transfer.
4. If the item does NOT match: keep it quarantined, escalate to counsel,
   open a `suspected_tampering` incident.
