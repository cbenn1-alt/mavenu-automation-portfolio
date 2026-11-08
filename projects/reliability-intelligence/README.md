# Mavenu Reliability Intelligence — V2 (GitHub integration)

**Status:** implemented and locally tested *requirements scaffold*; business problem, buyer, baseline and thresholds **not approved or validated**. This is **not** a maintenance platform, industrial AI model, customer pilot, or production application.

## V2 requirement

Mavenu's AI SaaS Platform Development Architecture V4, page 42: **"Define user, pain point and measurable outcome."** Required proof: **"Approved narrow problem statement."** A draft charter and executable checks are present; formal sign-off is still pending. Do not promote V2 to accepted until authorized owners sign the release decision.

## Proposed narrowly bounded use case

- **User:** maintenance planner / reliability engineer. **Buyer:** maintenance or operations leader. These are hypotheses, not confirmed Minn-Dak stakeholders.
- **Question:** Does source-traceable review of repeat equipment failures improve the speed and completeness of a human review within one asset family?
- **Primary outcome:** proposed 20% reduction in *median minutes per completed review case*, compared against a pre-registered matched manual baseline, with no loss of critical-case detection. This is a **target to test, not a measured saving**.
- **Scope:** synthetic-only, no customers, no Dynamics 365, Levridge, CMMS, historian, ERP, PLC, SCADA, OT, or production system integration.
- **Alternatives:** configure existing CMMS / Power BI or incumbent tools, or stop, if existing capabilities already meet the need.

## Run from this directory

~~~sh
PYTHONPATH=src python -m reliability_intelligence status --json
PYTHONPATH=src python -m reliability_intelligence charter
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
~~~

Python 3.11+; no external runtime dependencies. The GitHub Actions workflow runs the tests on PRs. GitHub-hosted CI is **unverified until a run completes**.

## Files

- `product_charter.json`: candidate user, narrow problem, measurable outcome, explicit approval gaps and hard data/control boundaries.
- `docs/PROBLEM_STATEMENT.md`: personas, problem hypothesis, disqualifiers and no-build alternative.
- `docs/MEASUREMENT_PLAN.md`: metric, denominator, comparison protocol and economic interpretation.
- `docs/releases/V2.md`: six-part release evidence packet and approval checklist.
- `src/reliability_intelligence/`: fail-closed inert charter/status CLI.
- `tests/`: contract and safety-regression tests. **Not proof of real operational impact.**

## Prior V1 and continuity

V1 was developed as an independent local source package. This GitHub directory establishes a self-contained V2 requirements scaffold and does **not** represent that the earlier V1 git history has been imported to this repository. The original V1 package, its 12 local tests and its architecture record remain separate pending a future baseline import/reconciliation. The V2 code does not implement a data ingestion, model or UI feature prematurely.

## Next gate

V2 acceptance requires a **named accountable internal product owner** to approve the narrow problem statement, and customer-domain validation before a pilot. For Minn-Dak or any other prospective customer, secure written authorization before any live data, systems access, or deployment. Next technical increment: V3, minimal interface shell.
