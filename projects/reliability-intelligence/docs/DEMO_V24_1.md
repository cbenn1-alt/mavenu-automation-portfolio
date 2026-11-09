# V24.1 — Independent technical replay

Python 3.11+, working directory projects/reliability-intelligence, exact V24.1 commit:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    for v in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
      PYTHONPATH=src python scripts/verify_v"$v".py
    done
    PYTHONPATH=src python scripts/verify_v24_1.py

Inspect evidence/V24_1/migration_persistence_integration.json, bootstrap_and_recovery_matrix.json and unsigned_v24_1_review.json. Confirm all eight scenarios PASS, version marker 2 and 13 tables/six triggers. At least four committed example scenarios reopen with identical receipts and idempotent replay. Populated/unknown-schema startup attempts are rejected without data changes; the injected V1→V2 DDL failure rolls back and reopens at V1. The original V24 data-transaction failures, receipt checks and 1,162 inherited tests remain green. Expected new tests: 54; total 1,216 subject to GitHub CI. V8 application coverage minimum 84.5% and V10 18-file freeze remain required.

The V24 historical contract retains original missing-V23 statements; the new V24.1 contract is authoritative for current bootstrap behavior. Technical PASS is not human approval or production authorization.
