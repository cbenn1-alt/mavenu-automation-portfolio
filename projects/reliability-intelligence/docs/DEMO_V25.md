# V25 exact-head reviewer replay

**Architecture V4 p.43:** V25 Add indexes and performance profiling.
**Proof:** Query-plan and threshold report.

Python 3.11+, from projects/reliability-intelligence:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    for v in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
      PYTHONPATH=src python scripts/verify_v"$v".py
    done
    PYTHONPATH=src python scripts/verify_v24_1.py
    PYTHONPATH=src python scripts/verify_v25.py

Review evidence/V25/query_plan_threshold_report.json, indexed_vs_baseline_profile.json, unsigned_index_review.json. Verify four chosen indexes, all result fingerprints identical, no temp sorting, measured median<=80 ms and P95<=200 ms on 37 samples/5 warmups, rollback of two installed candidate indexes under injected failure, schema user_version 2, 9,301 fabricated rows, temporary DB deleted and frozen V10 source intact.

Expected suite: 1,270 (1,216 inherited + 54 V25), subject to actual CI. The historical 84.5% combined application coverage floor remains enforced. Timings describe warm-cache synthetic SQLite only, not a production SLA or a guaranteed relative speedup.

Human review, customer data authorization, production index migration, and V10/V20 phase approvals remain missing.
