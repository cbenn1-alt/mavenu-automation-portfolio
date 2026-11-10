# V27 — Exact-head backup telemetry reviewer replay

**Architecture objective:** Schedule backups and integrity checks.
**Required proof:** Backup success telemetry.

From projects/reliability-intelligence in the exact V27 GitHub commit, using Python 3.11+:

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

Open evidence/V27/backup_success_telemetry.json, failure_and_schedule_matrix.json and unsigned_backup_operations_review.json.

Check that there are two successful **SIMULATED** due-slot online SQLite copies, each containing 134 invented rows, with source and backup V24 receipts equal, foreign keys and event chain checked, and an independently reopened copy. Confirm three failed attempts produce FAILED status, a stable fixed error, zero accepted rows, and no misleading success. Check six canonical UTC schedule-state examples, no unattended scheduler, no retained copies, 18 frozen V10 source files unchanged, prior source hashes equal, V20 formal gate BLOCKED and V26 security proposal unsigned.

**Expected full suite:** 1,469 tests (1,388 inherited and 81 V27), subject to exact-head GitHub Actions. Existing V8 source coverage floor 84.5% and all prior regressions must pass.

The success file is **telemetry evidence**, not a recoverable backup. No production cron, retention policy, offsite storage, encryption proof, power-loss durability, RPO/RTO or customer-data permission is established.
