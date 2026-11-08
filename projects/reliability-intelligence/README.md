# Mavenu Reliability Intelligence — V3 (GitHub development)

**State:** implemented local UI/navigation prototype; **not business-approved, not a deployed customer application and not an AI predictive-maintenance system**. The V2 requirements contract remains a candidate pending human sign-off. This branch adds an auditable V3 interface shell **on top of V2**.

## Architecture ledger

- **V2:** Define user, pain point and measurable outcome. Proof: approved narrow problem statement (**formal approval pending**).
- **V3:** Implement minimal user interface and navigation. Proof: usable shell smoke test (**automated tests in this PR**).
- **V4–V6:** Service/API boundaries, representative synthetic fixtures, and first end-to-end workflow (**not yet implemented**).
- **V30 / G1**, **V60 / G2** and later readiness gates are **not passed**.

Source: Mavenu AI SaaS Platform Development Architecture V4, page 42.

## Launch the local interface

Requires Python 3.11+; application dependencies: **Python standard library only**.

~~~bash
cd projects/reliability-intelligence
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~

Open **http://127.0.0.1:8765/** from the same computer. The server **always binds to loopback**; do not expose the prototype publicly.

Available navigation:

| Path | Page | State |
| --- | --- | --- |
| / | Overview | Proposed user, buyer and outcome |
| /workbench | Case workspace | Empty-state navigation; no records |
| /evaluation | Evaluation | Proposed matched-review metric; no measured results |
| /governance | Boundaries | Allowed / disallowed scope |

Static assets load from the repository at /assets/style.css. No external script, API key, hosting account, analytics beacon or JavaScript runtime is required. The UI is keyboard accessible, includes a skip link, visible focus styles, responsive layout, and reduced-motion CSS.

## Test and inspect

~~~bash
PYTHONPATH=src python -m reliability_intelligence status --json
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
~~~

The first PR's V2 contract tests remain active. V3 adds WSGI route, navigation, empty-state, HTML-escaping, CSP, HTTP method, HEAD, invalid-charter and loopback-binding smoke/negative-path tests. **Automated test passes do not establish customer value or industrial safety certification.**

See docs/DEMO_V3.md for reproduction, docs/releases/V3.md for release evidence, and docs/PROBLEM_STATEMENT.md for the unapproved hypothesis.

## Hard boundaries

- **SYNTHETIC_ONLY.** No Minn-Dak or third-party records and no authorization implied.
- No Dynamics 365, Levridge, Power BI, CMMS/ERP, historian, PLC/SCADA, or other OT system connections.
- No synthetic case fixtures yet (scheduled V5), no operations workflow (scheduled V6), no ML, no autonomous prioritization, no write-back.
- No savings claims, validated failure detection, or signed customer partnership.
- Browser UI is read-only and limited to GET/HEAD. Reverse proxies and internet hosting are **out of scope**.

## Repository strategy

The V3 feature branch is based on feature/reliability-intelligence-v2. Its PR targets that branch, so V2 need not be merged prematurely. **The separate local V1 source package/history is still not imported into the portfolio repository.** Before presenting a consolidated V1–V3 baseline, reconcile that history and record a reproducible setup result. Do not merge a draft increment as an approved release.

## Next V4

Define versioned **API/service boundaries** with contract smoke tests, keeping all integrations synthetic, local and read-only until later formal approval gates.
