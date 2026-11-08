# V17 exact-commit golden calculation reproduction

**Requirement:** Define golden/reference calculations. **Proof:** Expected-output fixtures.

From the recorded V17 GitHub commit, Python 3.11+, working in projects/reliability-intelligence:

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

Inspect fixtures/expected_outputs_v17.json, evidence/V17/golden_reference_report.json and evidence/V17/expected_output_comparison.json.

Expected **synthetic** comparison: 7 summary metrics, 6 asset outputs, 12 case history rows, total downtime 45.5, total example repair cost USD 12735.00, case-duration median 3, one case lacking an example evidence reference and six later synthetic asset occurrences. The verifier must report exact authored-value matches and unchanged source bytes, without claiming independent domain ground truth.

Expected complete regression count **603** tests, pending actual CI. The historical V8 combined source/branch coverage requirement remains 84.5%; V9 socket replay, V10 source freeze and all V11–V16 verifiers run before V17.

Human review gates: inspect fabricated calculations, repeatability and exclusion of reference_labels.json as a source of true labels. Do not claim measured customer downtime, work-order ROI, predictive performance, actual plant source ingestion, or accepted Phase 02 advancement. The technical report is not a business or customer release sign-off.
