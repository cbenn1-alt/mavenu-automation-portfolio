# V3 — reviewer smoke script (local only)

**Purpose:** prove that a reviewer can start the V3 interface and navigate its four static, evidence-labeled pages without customer data. This is the V3 acceptance proof ("usable shell smoke test"), not a business acceptance signature.

## Prerequisites

- Python 3.11+ installed.
- Repository at branch feature/reliability-intelligence-v3 or the V3 commit.
- No secrets, external service, customer data, SDK or installed third-party Python packages.

## 1. Automated checks

From projects/reliability-intelligence:

~~~sh
PYTHONPATH=src python -m unittest discover -s tests -v
~~~

Expected: original 12 V2 contract tests plus 19 V3 tests pass. Verify actual output and CI results rather than relying on this expectation. Failures block advancement.

## 2. Browser smoke

~~~sh
PYTHONPATH=src python -m reliability_intelligence serve
~~~

Open http://127.0.0.1:8765/ on the same device.

| Step | Action | Expected proof |
| --- | --- | --- |
| 1 | Open Overview | V3 candidate prototype, proposed user and ≥20% unmeasured target |
| 2 | Select Case workspace | "No cases loaded"; no fake active work orders |
| 3 | Select Evaluation | Proposed manual vs assisted metric; "Not measured" |
| 4 | Select Boundaries | Customer/OT and production prohibitions plainly listed |
| 5 | Use browser back / keyboard Tab and skip link | Navigable with focus indication and main-content landmark |
| 6 | Attempt nonexistent route | HTTP 404; no sensitive diagnostics |
| 7 | Attempt POST | HTTP 405, Allow: GET, HEAD |
| 8 | Stop local server | No persistent customer records or control actions |

## 3. Security smoke (developer)

~~~sh
curl -i http://127.0.0.1:8765/
curl -i http://127.0.0.1:8765/assets/style.css
curl -i -X POST http://127.0.0.1:8765/workbench
~~~

Verify Content-Security-Policy, no-store, nosniff and DENY headers. The UI's fixed, first-party navigation contains no outbound data request or form.

## Exclusions and nonclaims

No case fixture, ranking computation, model, industrial integration, real telemetry, savings, completed customer review or Minn-Dak authorization is provided by this V3 interface. Formal owner sign-off is outstanding.
