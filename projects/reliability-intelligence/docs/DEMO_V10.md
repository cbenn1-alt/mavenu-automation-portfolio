# V10 evidence reproduction and prototype decision review

**Exact standard:** V10 Freeze prototype baseline and open risk list. Proof: Prototype decision record (Mavenu Architecture V4, page 42).

1. Fresh checkout of feature/reliability-intelligence-v10 at its exact reviewed commit; use Python 3.11.
2. From projects/reliability-intelligence run:

~~~~bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
PYTHONPATH=src python scripts/replay_v9.py
PYTHONPATH=src python scripts/verify_v10.py
~~~~

3. Review generated evidence/V8/verification.json, evidence/V9/replay.json and evidence/V10/verification.json.
4. Confirm V8 coverage floor >=84.5%, all regression tests pass, V9 synthetic loopback replay completes 12 checks, and V10 pins 18 files.
5. Inspect docs/releases/V10_BASELINE.json, docs/RISK_REGISTER_V10.json, docs/releases/V10_DECISION.json and docs/DECISION_V10.md. Expect 11 OPEN risks, five formal blockers, a BLOCKED promotion recommendation, formal decision pending signature.
6. Verify original V9 runtime remains 0.9.0, API schema 1.3.0, synthetic-only; no real customer access or new write endpoints.

Initial V9 baseline: 153 passing tests and 84.951% coverage. V10 adds 23 tests, so 176 is expected; actual hosted CI output controls the claim. The V10 CI artifact is machine-verification evidence only.

An independent human must still replay V9 from clean source, inspect the browser and document exclusions. A named product owner must decide risk ownership, due dates, approval conditions, and whether to advance. Absent those, formal promotion remains blocked. Synthetic-only V11 research can be conducted as non-promoted work.
