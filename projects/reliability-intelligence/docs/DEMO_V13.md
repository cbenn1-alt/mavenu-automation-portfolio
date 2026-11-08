# V13 exact-commit negative-case replay

**V13 requirement:** Reject impossible, null and out-of-range values.
**Acceptance evidence:** Negative-case fixtures, not an actual field-data approval.

From a fresh checkout of feature/reliability-intelligence-v13 at its reviewed head, use Python 3.11+:

    cd projects/reliability-intelligence
    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    PYTHONPATH=src python scripts/verify_v10.py
    PYTHONPATH=src python scripts/verify_v11.py
    PYTHONPATH=src python scripts/verify_v12.py
    PYTHONPATH=src python scripts/verify_v13.py

The expected full regression suite is **300 tests** (244 previous + 56 V13). The actual GitHub Actions result controls the verified count. V8's source coverage floor of 84.5% remains enforced; V9 replay requires all 12 checks and V10 pins 18 historical source/configuration files.

Review evidence/V13/negative_case_report.json to confirm:
- 34 original fabricated rows pass unchanged source and V11/V12 validation;
- exactly 29 negative fixture cases are exercised, rejected with the intended error categories, and recorded;
- exactly seven valid boundary controls pass (including leap day, zero/max numeric values and empty or three-item evidence-reference arrays);
- no copied fixture is written to disk, no customer records are used, and no formal owner signature is asserted;
- formal V10 phase-promotion decision remains BLOCKED/PENDING human sign-off and V11/V12 dictionary/schema approvals remain unverified.

Inspect fixtures/negative_cases_v13.json for target correctness and exact expected rejection codes. Check that NaN/infinite values exist only in transient Python test memory and not as invalid JSON literals or model inputs.

The CI workflow runs all V8–V13 validation commands from an isolated Git archive and uploads V8–V13 evidence to an Actions artifact retained for 30 days. No independent human reviewer is claimed by automation.
