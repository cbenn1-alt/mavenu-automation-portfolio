# V28 exact-head reproduction

**Objective:** Enforce retention, deletion and archives.
**Required proof:** Retention-policy tests.

From projects/reliability-intelligence, Python 3.11+:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    for v in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
      PYTHONPATH=src python scripts/verify_v"$v".py
    done
    PYTHONPATH=src python scripts/verify_v24_1.py
    PYTHONPATH=src python scripts/verify_v25.py
    PYTHONPATH=src python scripts/verify_v26.py
    PYTHONPATH=src python scripts/verify_v27.py
    PYTHONPATH=src python scripts/verify_v28.py

Review evidence/V28/retention_policy_test_report.json, archive_delete_hold_matrix.json, unsigned_retention_review.json. Expected synthetic 24 objects, 10 active/8 archived/6 purged under two holds; 8/8/8 after fake hold release, 20 audit events. Two injected failures fully roll back and replay adds no duplicate transitions. Wrong-scope hold release must be refused. Test copies and sources must be deleted, V10 18 frozen files and original V26 source unchanged. No retention of production backups, real customer records, actual legal authority, or secure erasure is tested.

Expected full regression: 1,571 tests; hosted GitHub Actions controls the actual result.
