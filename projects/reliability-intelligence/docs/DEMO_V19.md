# V19 exact-commit independent computation replay

**Architecture requirement:** Reconcile aggregates and operational metrics.
**Proof:** Independent computation results (Mavenu Architecture V4, page 42).

From projects/reliability-intelligence at the exact reviewed V19 GitHub commit with Python 3.11+:

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

Review fixtures/reconciliation_v19.json and the V17 authored expected-output fixture separately. Review evidence/V19/independent_reconciliation_report.json and evidence/V19/independent_computation_results.json. Confirm:

- **25/25** synthetic reference units reconcile (7 summary values, 6 per-asset objects, 12 case-history objects), **zero** discrepancy in the original fictional dataset.
- **16/16** mutated scenarios reveal a discrepancy or fail closed with a fixed error.
- SQLite SQL aggregations and integral seconds/cents are independent of V17's Python Decimal/V16 transformed-row calculation code. The underlying synthetic source is shared and NOT an independently validated customer data source.
- The result is invariant under reversal of raw cases/assets; original fixture bytes are unchanged.
- V10 18-file freeze and V8 combined 84.5% coverage floor remain intact.
- No human approval, real plant operational measurement, source custodian or validated financial savings is asserted.

Expected complete regression suite: **754** (677 inherited plus 77 new). The actual GitHub Actions log controls the verified number. Full V8–V19 evidence should be archived under the CI artifact for 30 days.

**Reviewer gate:** Independently inspect synthetic assumptions and sources, then separately obtain approved operational metric definitions and authorized source evidence before claiming Data Correctness Phase approval. V20 is a **data-quality sign-off** requirement; passing V19 CI alone does not satisfy it.
