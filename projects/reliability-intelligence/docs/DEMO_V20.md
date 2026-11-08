# V20 — Exact-commit data-quality proof replay

**Objective:** Approve data correctness test baseline.
**Required proof:** Data quality sign-off (Architecture V4, p.42).

From the exact V20 GitHub commit, using Python 3.11+ and projects/reliability-intelligence as working directory:

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

Check evidence/V20/verification.json, evidence_manifest.json and data_quality_signoff_packet.json. Confirm 11 verified reports (V8/V10 and V11–V19), V8 coverage >=84.5%, all V10 frozen 18 paths intact, minimum 754 tests, 8 blockers, owner/reviewer names/signatures null, technical evidence PASS, and human sign-off BLOCKED_PENDING_HUMAN_SIGNOFF. Expected full suite is 819 tests (754 previous + 65 V20); actual CI controls the verified count.

Never treat this automated packet or its SHA-256 hashes as independent human approval, actual customer data provenance, live plant measurements or data rights. V10 phase-promotion and V11/V12 owner approvals remain outstanding. The CI isolated checkout archives V8–V20 evidence for 30 days.
