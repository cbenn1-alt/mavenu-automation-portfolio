# V16 — Record-level trace replay

**Architecture requirement:** Capture ingestion origin and transform lineage.
**Proof:** Record-level trace sample (Mavenu Development Architecture V4, page 42).

In a fresh exact-commit checkout of feature/reliability-intelligence-v16, Python 3.11+:

    cd projects/reliability-intelligence
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

Expected total suite: 544 tests (429 existing plus 115 new), subject to GitHub Actions verification; previous V8 source-coverage floor remains 84.5%.

Inspect three generated outputs in evidence/V16: lineage_verification.json, record_level_trace_sample.json, synthetic_record_lineage.json. Expect 3 allowlisted synthetic files, 34 traced records, 36 V15 field steps, 22 pass-through records and 5 sample traces (6 sample steps). Compare raw file SHA-256, JSON row pointers, canonical row hashes, original/new value hashes, normalizer rules and complete trace checksum. All 18 V10 frozen files must remain unchanged.

Technical demonstration does not establish a real ingestion event or customer data provenance. Source origin is reconstructed from authored fixtures. No customer, OT, production system or human reviewer authority is inferred. An independent reviewer must separately inspect evidence, resolve exceptions and approve release scope; V10 phase decision and V11 dictionary sign-off remain pending.
