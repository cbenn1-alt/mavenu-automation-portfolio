# Project 02 — Demonstration Script

**Audience:** a reviewer (e.g. a hiring manager for an AI Automation
Engineer role). **Duration:** ~10 minutes. All data is synthetic.

> Framing line: "This is a portfolio simulation of the request-to-approval
> chain on a custom Python stack — it mirrors what Power Automate approval
> flows do conceptually, but it is not a Power Platform implementation."

## Setup (1 min)

```bash
cd mavenu-portfolio
MAVENU_DB_PATH=/tmp/p02-demo.db .venv/bin/python run.py --port 8137 &
# open http://localhost:8137/project02
```

Point out the **SYNTHETIC DEMO DATA** banner: every name, email, and amount
is invented.

## Act 1 — Intake and validation (2 min)

1. Open `/project02`. Submit the form with a **short justification**
   (under 20 characters) → the form re-renders with a field-level error.
   *Point: validation is server-side; the client is never trusted.*
2. Submit correctly: type `purchase`, title
   `Replacement HVAC blower motor`, amount `2450`, cost center `OPS410`,
   a full justification, requester `Dana Rivera` /
   `dana.rivera@example.com`.
3. Land on the detail page: state `draft`, audit timeline shows
   `request.created` with your actor stamp.

## Act 2 — Approval routing (3 min)

1. Click **Submit for approval** → `submitted` → `in_review`. The approval
   chain shows **manager → finance** — because $2,450 exceeds the $1,000
   finance threshold.
2. Try approving as `finance` first → the action fails with a clear error.
   *Point: the wrong role cannot decide; the step owner is enforced in code.*
3. Approve as `manager` → stays `in_review`, step advances to `finance`,
   SLA deadline re-armed. Approve as `finance` → `approved`, with
   `decided_by` stamped.
4. Click **Mark fulfilled** → `fulfilled` (terminal).

*Contrast:* submit a second request as type `access` with amount blank →
chain is **manager only** — one approval finishes it.

## Act 3 — SLA escalation (2 min)

1. In a second terminal:
   ```bash
   MAVENU_APPROVAL_SLA_HOURS=0 MAVENU_DB_PATH=/tmp/p02-sla.db \
     .venv/bin/python run.py --port 8138 &
   ```
2. Submit a request there, submit it for approval, then:
   ```bash
   curl -X POST http://localhost:8138/api/requests/sla-sweep
   ```
3. Refresh the detail page: state `escalated`, chain rewritten to
   **director**, fresh deadline, and the audit timeline shows
   `request.escalated` by `system` with the previous chain preserved in the
   event detail.
4. Approve as `director` → `approved`.
   *Point: the sweep is deterministic — the same behavior is covered by
   clock-injected tests (`test_sla_breach_escalates_to_director`).*

## Act 4 — Dashboard and audit (2 min)

1. Open `/project02/dashboard`: counts by state and type, SLA-breach and
   escalation counters, and the SLA watch list ordered by deadline.
   *Point: every number is computed from the database — a test
   re-computes them with independent SQL and asserts equality.*
2. Open any request's timeline: created → submitted → routed → approvals →
   fulfilled, each with actor, timestamp, and from/to states.

## Close

- 101 automated tests; full suite 152/152 with Project 01, zero regressions.
- Rollback is a tested procedure: `002_approvals.down.sql` via
  `db.rollback_migration()` (apply → use → roll back → re-apply).
- Honest boundaries: no authentication on approver actions (documented),
  no real scheduler yet (the sweep endpoint is the hook), and this is a
  custom-stack simulation — not Power Platform, SharePoint, or UiPath.

## Cleanup

```bash
kill %1 %2 2>/dev/null; rm -f /tmp/p02-demo.db* /tmp/p02-sla.db*
```
