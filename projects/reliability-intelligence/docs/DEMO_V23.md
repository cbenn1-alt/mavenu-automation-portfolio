# V23 exact-commit up/down migration replay

**Source:** Mavenu AI SaaS Platform Development Architecture V4 p.43.
**Requirement:** Implement reversible schema migration path.
**Proof:** Up/down migration evidence.

From projects/reliability-intelligence on the exact V23 commit, Python 3.11+:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    PYTHONPATH=src python scripts/verify_v10.py
    PYTHONPATH=src python scripts/verify_v11.py
    PYTHONPATH=src python scripts/verify_v12.py
    PYTHONPATH=src python scripts/verify_v13.py
    PYTHONPATH=src python scripts/verify_v14.py
    PYTHONPATH=src python scripts/verify_v15.py
    PYTHONPATH=src python scripts/verify_v16.py
    PYTHONPATH=src python scripts/verify_v17.py
    PYTHONPATH=src python scripts/verify_v18.py
    PYTHONPATH=src python scripts/verify_v19.py
    PYTHONPATH=src python scripts/verify_v20.py
    PYTHONPATH=src python scripts/verify_v21.py
    PYTHONPATH=src python scripts/verify_v22.py
    PYTHONPATH=src python scripts/verify_v23.py
    PYTHONPATH=src python scripts/verify_v24.py

Check evidence/V23/up_down_migration_report.json, migration_failure_matrix.json, and unsigned_migration_review.json.

Expected technical evidence:
- 2 successful forward adjacent steps and 2 successful reverse adjacent steps.
- Version 0 has 0 tables; version 1 has 10 tables; version 2 has 13 tables and 6 triggers. The restored v1/v0 schema fingerprints equal their pre-upgrade originals.
- 120 synthetic V21 rows retain the exact canonical-row digest across 1→2→1.
- Destructive downgrade of 120-row V21 data or the 134-row committed V24 ledger is rejected.
- Four deliberately injected migration exceptions are fully rolled back, including schema version, before and after reopening.
- No source fixtures changed, V10's 18 frozen files intact; V20 formal approval blocked.
- V24 historical bootstrap is not replaced by a V23 production migration flow.

Expected suite 1,162 (1,088 earlier + 74 V23), subject to GitHub Actions; prior 84.5% coverage floor remains. File-backed SQLite only in automatically deleted test directories.

Human sign-off remains PENDING. Test success is neither a production migration, customer data authorization nor an actual rollback of customer records.
