# V12 independent reproduction instructions

From an exact V12 GitHub commit using Python 3.11+:

    cd projects/reliability-intelligence
    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    PYTHONPATH=src python scripts/verify_v10.py
    PYTHONPATH=src python scripts/verify_v11.py
    PYTHONPATH=src python scripts/verify_v12.py

Expected new V12 tests: **34** (full suite **244** including V11's 210), subject to actual GitHub CI. Coverage floor remains 84.5%.

The V12 report must show 4 datasets, 21 field definitions, 34 synthetic records, 196 required/type checks, nonzero enum and identifier checks and **16/16 deliberately invalid records rejected**. Confirm V10 frozen 18 files and blocked formal advancement; confirm V11 source dictionary and V12 contract have no signatures.

Inspect docs/data/SCHEMA_CONTRACT_V12.json against the V11 dictionary. Validate that no real customer's identifiers, data system credentials or API write routes have been introduced. Only authenticated humans can approve the dictionary or authorize real data access; CI never supplies that approval.

Output artifact: evidence/V12/schema_validation_report.json, published with V8–V11 evidence in GitHub Actions. The synthetic-only V9 runtime and API v1/schema 1.3.0 are unchanged.
