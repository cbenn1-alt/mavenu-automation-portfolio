# V21 — Canonical entity schema reviewer replay

**Objective:** Design canonical entities and relationships.
**Required proof:** Reviewed entity schema.
**Architecture:** Mavenu AI SaaS Development Architecture V4, Appendix V21–V40.

Checkout the exact V21 commit; use Python 3.11+ from projects/reliability-intelligence:

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

Inspect docs/data/ENTITY_MODEL_V21.json and SCHEMA_DESIGN_V21.sql, plus evidence/V21/schema_review_validation.json, entity_relationship_catalog.json and unsigned_entity_schema_review.json.

**Acceptance check:** 10 draft entities, 9 SQLite foreign-key relationships, 10 composite/primary key definitions, 120 populated synthetic-preview rows, 34 record origins, 36 transformation steps and zero foreign-key violations. The 11 evidence identifiers are not validated real documents; four scripted review rows represent NO human action; 12 authored labels are not domain-adjudicated. Verify all customer/security/reviewer signatures null and V10/V20 promotion blocked.

**Source security boundary:** SQLite database is only :memory:, closed on exit. The DDL is a design candidate not a V23 migration, and the relational keys do not implement tenancy authentication or authorization. No real customer data and no external network access.

Expected total regression test inventory: based on 819 V20 tests plus the V21 tests (actual hosted CI count governs). Preserve the V8 84.5% combined coverage floor and V10 18-file freeze.

**Human requirement remains outstanding:** Independent architect/data steward/security review and signed entity schema decision, plus unresolved V10/V20 phase gates, are required for formal approval.
