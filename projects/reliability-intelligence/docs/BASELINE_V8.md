# V8 initial regression and measured coverage baseline

**Standard:** Create initial unit and smoke regression. Proof: CI result and baseline coverage (Mavenu Development Architecture V4, p.42).

The product is standard-library Python. GitHub Actions installs pinned test-only coverage.py on Python 3.11. The verification runner checks unique discovered test IDs, all seven test modules, at least 140 tests, and coverage for at least seven production source modules. It runs the complete suite and collects branch-aware coverage from the package only; tests are excluded from the source denominator.

On first measurement with no committed baseline file, the runner writes a candidate snapshot and explicitly labels baseline_state=candidate_unfrozen. Once the observed CI percentages and test inventory have been reviewed, a V8_BASELINE.json may freeze the observed numbers and a transparent minimum floor. Subsequent runs enforce both test-count and coverage floors. The measured baseline must be attributable to the exact GitHub commit and Actions run.

Output: evidence/V8/coverage.json with per-source-line and branch measurement; evidence/V8/verification.json with test count, inventory SHA-256, per-module test counts, combined coverage percentage, covered statements/branches, Python version, baseline state and gate outcome. GitHub Actions retains evidence for 30 days.

**Interpretation:** coverage.py's total percentage combines covered statement and branch opportunities in this test suite. It does not prove high-risk behavior is correct, independent business utility, security compliance, real reliability prediction, or operational safety.

## Reviewer reproduction

~~~~bash
cd projects/reliability-intelligence
python -m pip install -r requirements-dev.txt
PYTHONPATH=src python scripts/verify_v8.py
~~~~

Compare the local report with the Actions artifact and examine missed lines/branches. Verify no source modules were silently excluded and no test categories disappeared.

Independent manual browser/clean setup replay is addressed at V9. The Python WSGI access logger is separate from V7's sanitized diagnostic module. No customer data may be used. The baseline is engineering evidence, **not signed product acceptance**.
