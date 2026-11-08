# V18 exact-head reproduction

**Objective:** Test missing, stale and malformed inputs.
**Required proof:** Adverse-case regression suite (Architecture V4, page 42).

Run from projects/reliability-intelligence at the reviewed exact commit, using Python 3.11+:

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

Inspect evidence/V18/adverse_regression_report.json for exactly **16 missing**, **7 stale/future**, and **21 malformed** synthetic input rejections; five valid controls; 34 baseline records and 12 timestamp checks. Confirm unchanged fixture SHA-256 and the 18-file V10 frozen-source integrity. The synthetic clock is 2026-02-05T00:00:00Z with inclusive 45-day past/24-hour future windows.

Expected complete regression **677** tests (603 inherited and 74 new), subject to actual hosted CI. The previous 84.5% coverage threshold remains in force. No actual production ingestion, customer data or human approval is represented.
