# V26 independent reviewer replay

**V26:** Document tenant boundaries and data rights.
**Proof:** Isolation design decision.

Python 3.11+; exact checked-out commit, working directory projects/reliability-intelligence:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    for version in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
      PYTHONPATH=src python "scripts/verify_v$version.py"
    done
    PYTHONPATH=src python scripts/verify_v24_1.py
    PYTHONPATH=src python scripts/verify_v25.py
    PYTHONPATH=src python scripts/verify_v26.py

Inspect docs/data/ISOLATION_DECISION_V26.json and evidence/V26/isolation_design_decision.json, synthetic_access_probe_matrix.json, unsigned_data_rights_review.json.

Required synthetic-only findings: 38 rows across four scopes; identical case ID repeated across all scopes; 48 actor/scope/operation checks (8 authorized, 40 denied); ten malformed/unsupported requests rejected with identical scope_denied response; SQLite FK intact and schema version 2; 18 frozen V10 source files unchanged. The raw database connection can still read all 12 cases; no production RLS or authentication. No signed DPA, legal customer data rights, production isolation or owner approval.

Expected full regression: 1,388 tests (1,270 inherited plus 118 V26); actual GitHub CI is authoritative. V8 combined coverage floor: 84.5%.
