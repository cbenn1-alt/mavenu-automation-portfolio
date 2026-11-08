# V8 CI and baseline coverage reviewer replay

1. Check out exact V8 branch commit and enter projects/reliability-intelligence. Use Python 3.11.
2. Install test-only dependency and run complete verification:

~~~~bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
~~~~

3. Inspect generated evidence/V8/verification.json and coverage.json. Confirm 140 or more distinct tests, seven historical/current test modules, combined coverage at least 84.5%, nine required source modules and the reported frozen_measured_pending_human_signoff state. The initial measured baseline (84.951%, 140 tests) originated in GitHub Actions run 42486809082; independent acceptance and owner sign-off remain pending.
4. Confirm the smoke matrix: all five UI and API routes, read-only HTTP controls, 12 fictional cases, V6 deterministic replay, explicitly simulated reviewer dispositions, V7 sanitized failure paths, no seeded-label leakage, and absence of real data and OT writes.
5. Confirm GitHub Actions for the exact commit completed successfully, download its V8 evidence artifact, compare coverage, record reviewer identity, date, untested paths, exceptions and owner release decision.

Expected test count: 125 historical + 15 V8 = 140. This is an expectation, not a substitute for hosted execution.

No actual browser engine, customer integration, production reliability analysis, or operator approval is tested. Independent browser replay belongs to V9.
