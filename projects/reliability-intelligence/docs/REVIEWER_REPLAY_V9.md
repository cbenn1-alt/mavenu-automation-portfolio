# V9 — independent human reviewer replay (unsigned instructions)

**Development requirement:** Document setup, demo steps and exclusions.
**Required proof:** Independent reviewer replay. Source: Mavenu Development Architecture V4, page 42.

A GitHub Actions job is not an independent human reviewer. Automated evidence is necessary but insufficient. This document provides a procedure another qualified person can execute, and an unsigned record template.

## Reviewer independence and scope

A reviewer should be a technically capable person other than the primary author who can use Python 3.11, terminal commands, HTTP status checks and a basic accessibility/navigation inspection. They should have no access to Minn-Dak or any other customer system as part of this review. Do not claim that a GitHub Actions robot or this assistant is a human reviewer.

## A. Establish a clean checkout

1. Create a new empty working directory; check out the exact V9 PR head SHA as described in SETUP_V9.md. Avoid using a previously installed editable package or working directory with old artifacts.
2. Record operating system, Python version and the exact Git commit.
3. Read product charter, docs/EXCLUSIONS_V9.md and the original V8 coverage baseline before executing.
4. Confirm no .env, live keys, tokens, customer records, or network connectors are necessary.

## B. Verify tests and output

From projects/reliability-intelligence:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py

Expected: all tests pass (at least 153) and V8 coverage floor 84.5% is met. V9 replay records the 12 synthetic cases, four fictional reviewer-role dispositions and twelve required automated checks. Verify the actual result, not expected figures. The script writes evidence/V9/replay.json with formal_review_accepted=false and independent_human_reviewer=false.

Compare the CLI demo trace checksum with replay.json and the /api/v1/demo response. The same checksum is evidence of deterministic replay, not an immutable log or digital signature.

## C. Independent manual local browser replay

Start:

    PYTHONPATH=src python -m reliability_intelligence serve --port 8765

Within the same host, inspect:

- Overview (/): candidate user/outcome, synthetic-only and unapproved status visible.
- Case workbench (/workbench): exactly 12 fabricated case rows, SYN identifiers and no operational work orders.
- Workflow (/workflow): four explicitly SCRIPTED fictional dispositions, eight unresolved, same trace checksum as CLI.
- Evaluation (/evaluation): proposed metric, explicitly unmeasured.
- Boundaries (/governance): no real customer records, enterprise integrations or PLC/SCADA/OT actions.

Tab through links, test skip-to-content, visible focus, responsive widths and browser back. Automated route tests do NOT substitute for a full browser/accessibility audit; record any issues.

## D. HTTP contract and negative paths

    curl -i http://127.0.0.1:8765/api/v1/status
    curl -i http://127.0.0.1:8765/api/v1/demo
    curl -I http://127.0.0.1:8765/api/v1/demo
    curl -i -X POST http://127.0.0.1:8765/api/v1/demo
    curl -i http://127.0.0.1:8765/api/v2/status

Expected GET 200 with schema 1.3.0; HEAD 200 with no body; POST 405; unknown version 404. Diagnostic failure headers are category fingerprints, not request/incident IDs. Note that the underlying simple WSGI server may produce independent access logs, unlike sanitized V7 diagnostics.

## E. Exceptions and decision

Record test count, coverage percentage, CI run link, reviewer environment, reproducible trace checksum, browser checks, defects, screenshots or ticket links where applicable, and reviewer signature/date in a privately stored copy of the template.

Decision options: ACCEPT LIMITED TECHNICAL V9, CONDITIONAL, or BLOCK. An independent human review should explicitly identify residual risks and may block a technically green candidate. No signature, no independent human proof. The upstream V2–V8 approvals and separately held V1 Git history remain unresolved.

**Exclusions:** synthetic-only local rehearsal; no industrial plant controls, real data, employee records, user authentication, deployment, production evidence, reliable savings forecasts, or validated predictive intelligence.
