# V22 — Exact-commit replay of identity uniqueness and links

**Objective:** Define identity and reference-data rules.
**Required proof:** Uniqueness and link tests.

From projects/reliability-intelligence in the reviewed V22 GitHub checkout, Python 3.11+:

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
    PYTHONPATH=src python scripts/verify_v21.py
    PYTHONPATH=src python scripts/verify_v22.py

Check evidence/V22/identity_reference_validation.json, uniqueness_link_matrix.json and unsigned_identity_review.json. Confirm:

- **9/9** fixed synthetic identifier patterns; **10/10** reference-data sets.
- **13/13** scoped uniqueness views, zero duplicate rows in the original fabricated dataset.
- **9/9** parent/child link checks, zero unresolved parent references or SQLite foreign-key violations.
- **25/25** deliberately invalid synthetic copies rejected with exact diagnostics and no original source changes.
- Original 3 fixture files unchanged; V10's 18 frozen paths preserved, V21's 120 in-memory example rows retained.
- V20 sign-off BLOCKED, V21 review pending, V22 identity reviewer unsigned and no approved V23 migration.

Expected full suite **1006** (904 V21 + 102 V22), subject to actual GitHub Actions. Existing V8 combined statement/branch coverage floor 84.5% remains.

Human sign-off on customer identity policy and reference-data semantics is not automatic. This is a synthetic code-verification candidate only.
