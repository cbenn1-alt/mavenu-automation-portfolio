# V24 exact-commit transactional replay

**Requirement:** Persist validated records and events.
**Proof:** Transactional integrity tests.
**Architecture:** Mavenu AI SaaS Platform Development Architecture V4, p.43.

V23 reversible migration (up/down) implementation is **absent**. Do not interpret temporary bootstrap as a migration or production database readiness.

From the exact V24 GitHub head, Python 3.11+ and working directory projects/reliability-intelligence:

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
    PYTHONPATH=src python scripts/verify_v24.py

Check evidence/V24/transactional_integrity_report.json, rollback_reopen_matrix.json and unsigned_persistence_review.json. Verify:
1. **120/120** source entity rows from V21/V22, **12/12** invented events, one batch and one receipt, **134** total rows per transaction.
2. Normal commit and reopen succeed with equal SHA-256 receipt and zero SQLite foreign-key violations.
3. Identical retry returns ALREADY_COMMITTED, 0 additional rows.
4. Exceptions injected after all source rows and after four events cause rollback to **zero** committed rows even after reopening.
5. Repeated transactions produce the same fabricated receipt; source files and V10 18-file freeze unchanged.
6. No customer source access, production permission, true power-failure certification, V23 migration evidence or signed V24 acceptance appears in the reports.
7. Files are deleted as the TemporaryDirectory contexts exit.

Expected full suite **1,088** tests (1,006 inherited + 82 V24), subject to exact GitHub CI. Retain V8 combined 84.5% coverage minimum. CI artifacts retain the V8–V24 evidence files for 30 days.

The required human decision is separate: owner approval of domain data/storage, V23 migration proof, V10/V20 phase signoffs and qualified security review remain outstanding.
