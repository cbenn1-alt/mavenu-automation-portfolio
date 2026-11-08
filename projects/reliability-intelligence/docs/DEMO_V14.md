# V14 — Repeated-ingest comparison and reviewer replay

**Architecture V4, page 42:** V14 Enforce duplicates and idempotency rules. Proof: Repeated-ingest comparison.

At the exact V14 GitHub commit, with Python 3.11+:

    cd projects/reliability-intelligence
    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    PYTHONPATH=src python scripts/verify_v10.py
    PYTHONPATH=src python scripts/verify_v11.py
    PYTHONPATH=src python scripts/verify_v12.py
    PYTHONPATH=src python scripts/verify_v13.py
    PYTHONPATH=src python scripts/verify_v14.py

The expected inherited suite is 300 tests plus 48 V14 tests, for **348 total**; the actual hosted CI result controls. V8's 84.5% source coverage floor is enforced, and V9, V10, V11, V12, V13 checks remain part of the clean-snapshot workflow.

Inspect evidence/V14/repeated_ingest_comparison.json:
- all four synthetic datasets and 34 original records;
- exactly 16 scenario comparisons (six accepted, ten rejected);
- 34/34 identical records classified as duplicates on second full ingest;
- repeated, reordered, partitioned, overlapping and same-batch duplicate behavior all yield the same stable canonical SHA-256 state;
- every rejected batch records a fixed error category and no change to the previous state digest;
- 18 V10 frozen paths unchanged, no customer data and no human sign-off claimed.

The machine-readable policy is docs/data/IDEMPOTENCY_CONTRACT_V14.json; the scenario list is fixtures/repeated_ingest_v14.json. Examine scripts/ingest_v14.py and tests/test_idempotency_v14.py for exact identity, secondary uniqueness, atomic staging, defensive-copy and ordering behavior.

A human reviewer should verify the stated uniqueness semantics are **only synthetic assumptions**, and that later real-source or distributed ingestion would require separately authorized correctness tests. No benchmark, production deployment or customer authority is implied by CI.
