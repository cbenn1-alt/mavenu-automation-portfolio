# V11 — data source dictionary reproduction and review procedure

**Exact architecture increment:** V11 Declare data types, meaning, and ownership.
**Acceptance proof:** Approved source/field dictionary.
**Actual status:** Technically validated synthetic dictionary; **approval not obtained**.

From a clean checkout of feature/reliability-intelligence-v11, with Python 3.11+:

~~~~bash
cd projects/reliability-intelligence
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
PYTHONPATH=src python scripts/replay_v9.py
PYTHONPATH=src python scripts/verify_v10.py
PYTHONPATH=src python scripts/verify_v11.py
~~~~

The full regression count is expected to be **210** (176 V10 + 34 V11 tests); use GitHub Actions actual output. Existing V8 84.5% coverage floor is still enforced; the V9 12-check socket replay and V10 18-file frozen baseline are verified independently.

Expected V11 dictionary scope: four datasets, 21 declared field occurrences, six fabricated asset rows, twelve fabricated case rows, four fictional reviewer-script rows and twelve unblinded reference-label rows. Expect unassigned stewards, no real customer system source, blocked Phase 02 promotion, and technical_evidence status rather than an approval. The verifier outputs ignored evidence/V11/verification.json.

Negative-path tests intentionally mutate copies only (not repo files) to reject mismatched types/units, invented steward authorization, missing/extra fields, inconsistent identifiers, noncanonical timestamps, nonfinite costs, duplicate keys, and cross-dataset foreign-key failures. No customer systems, secrets, accounts or industrial controls are touched.

The evidence demonstrates fixture/dictionary consistency, not the correctness or fitness of a real industrial data model. A qualified customer data steward and domain reviewer must separately approve the field dictionary and record the source of authority, units, taxonomy, retention and owner assignments. This approval cannot be inferred from CI.
