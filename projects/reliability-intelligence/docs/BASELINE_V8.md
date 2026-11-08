# V8 initial regression and measured coverage baseline

**Standard:** Create initial unit and smoke regression. Proof: CI result and baseline coverage (Mavenu Development Architecture V4, p.42).

The product is standard-library Python. GitHub Actions installs pinned test-only coverage.py on Python 3.11. The verification runner checks unique discovered test IDs, all seven test modules, at least 140 tests, and coverage for at least seven production source modules. It runs the complete suite and collects branch-aware coverage from the package only; tests are excluded from the source denominator.

Initial GitHub CI (run 42486809082, commit c75254e) measured **140 passing tests**, **84.951% combined coverage** over 9 source modules, from 521 statements (457 covered) and 190 branches (147 covered). docs/releases/V8_BASELINE.json now records this observed measurement and a **84.5% combined floor**, plus a 140-test minimum, per-test-module minimum counts and all nine required source files. The observed baseline is recorded as **measured, pending human sign-off**; it is not a signed release decision. Later CI runs enforce all of these floors. The policy uses a 0.451 percentage-point margin to allow minor measurement variability without silently accepting a material regression.

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

## Baseline source and identified coverage gaps

First-run source coverage: __init__.py 100%; __main__.py 74%; api_v1.py 88%; charter.py 76%; diagnostics.py 100%; fixtures.py 79%; services.py 100%; web.py 98%; workflow.py 90%. These are rounded per-file percentages from the GitHub Actions coverage report; the combined total is 84.951%.

The most significant initial omissions are CLI control paths in __main__.py, charter failure cases in charter.py, and invalid-input branches in fixtures.py. These should be priority targets in later regression increments; the measured baseline is not proof that these hazards are comprehensively tested. The source inventory SHA-256 and per-module count are recorded for audit, but the runner allows new test identifiers as long as historical module count floors remain satisfied.

Source: [initial GitHub Actions run](https://github.com/cbenn1-alt/mavenu-automation-portfolio/actions/runs/42486809082). The coverage evidence artifact is retained under GitHub Actions according to the workflow's 30-day setting.
