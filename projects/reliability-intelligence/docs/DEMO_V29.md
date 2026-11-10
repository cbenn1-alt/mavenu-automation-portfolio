# V29 independent reviewer reproduction

**Objective:** Execute restore and corruption response drill.
**Required proof:** Timed restore evidence.

On the exact V29 commit, Python 3.11+, working directory projects/reliability-intelligence:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    for v in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
      PYTHONPATH=src python "scripts/verify_v${v}.py"
    done
    PYTHONPATH=src python scripts/verify_v24_1.py
    PYTHONPATH=src python scripts/verify_v25.py
    PYTHONPATH=src python scripts/verify_v26.py
    PYTHONPATH=src python scripts/verify_v27.py
    PYTHONPATH=src python scripts/verify_v28.py
    PYTHONPATH=src python scripts/verify_v29.py

Review evidence/V29/timed_restore_evidence.json, corruption_response_matrix.json and unsigned_recovery_review.json.

Validate three timed, fully reopened restores with 134 rows/12 events each, valid manifest and receipt, zero synthetic post-backup writes and separate active/backup/target directories. Verify damaged active database is detected but valid backup remains restorable. Verify four rejected attempts (missing, digest-tampered, header-corrupt, injected post-copy exception) leave no accepted target. All three temp files deleted after each case. V10 18-file frozen records remain unmodified; V27 does not have retained customer backups; V28 legal-hold sidecar is not restored.

Expected cumulative suite **1,643** tests (1,571 existing + 72 new); authoritative count comes from GitHub Actions. Do not treat milliseconds on 134 fictional SQLite records as an operational RTO or production RPO.
