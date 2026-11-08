# Project P05 — Automation Reliability & Governance Center

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval, no real business data, no performance claims beyond measured timings on fixtures.

## What it does

P05 is the governance layer over the portfolio's own synthetic operations. It answers four questions, all against the local demo system:

- **Is the system healthy?** Health checks run liveness/readiness probes over the database, migrations, queue depths, and storage, and turn each probe's numeric value into **pass / degraded / fail** against warn/fail thresholds. A status summary rolls the latest run of every check into one overall verdict.
- **What happens when a job fails?** Retry policies are **data** — max attempts, exponential-backoff base and cap, deterministic jitter bound, dead-letter threshold — versioned like P04's queries. A job that exhausts its policy is dead-lettered, and a dead letter can be replayed as a fresh job. **Jobs execute no real work**: an attempt records the outcome the caller reports; P05 computes the next delay.
- **Who needs to know?** Alerting rules watch a check's metric and fire when the comparison holds. **Alerts are recorded only and never sent anywhere** — there is no send path in P05 by architecture (no email, webhook, SMS, or pager call exists in the module). Repeat firings inside the rule's dedup window bump the alert's count instead of opening a new alert; a silenced rule is skipped and the suppression is audit-logged.
- **What do we do about it?** Runbooks are versioned data — steps with time boxes, keyed to an alert key — with a timed walkthrough harness. Incidents carry an actor-stamped timeline through **open → triaged → mitigating → resolved → closed** (plus reopen), and resolving requires a resolution note.

## Documents in this folder

| Doc | Purpose |
|---|---|
| `REQUIREMENTS.md` | Functional + non-functional requirements, acceptance criteria |
| `ARCHITECTURE.md` | Module map, data model, probe/policy/rule design, key decisions |
| `TEST_PLAN.md` | Test strategy, fixture design, coverage map |
| `TEST_RESULTS.md` | Exact test counts and the hand-computed fixture oracle |
| `SECURITY.md` | Threat model, allow-list safety, input validation, audit logging |
| `RUNBOOK.md` | How to run, operate, and roll back (migration down-step) |
| `DEMO.md` | Demo script against the synthetic fixture |
| `EVIDENCE_MATRIX.md` | Claim → artifact mapping |

## Quick start

```bash
python3 run.py --port 8000 --db data/app.db
```

Then open **P05** (`/project05`), click **Seed demo data**, and run a check — or use the JSON API:

```bash
curl -X POST localhost:8000/api/governance/seed -H 'Content-Type: application/json' -d '{}'

curl localhost:8000/api/governance/status

curl -X POST localhost:8000/api/governance/checks/1/run -H 'Content-Type: application/json' -d '{}'
```

## Modules

- **Service** — `src/mavenu/governance.py`: probes, checks, retry policies, jobs, dead letters, alerting rules, alerts, runbooks, incidents, demo seed.
- **State machines** — `src/mavenu/workflow.py`: `INCIDENT_WORKFLOW` (open→triaged→mitigating→resolved→closed + reopen) and `ALERT_WORKFLOW` (open→acked→resolved), alongside the sibling workflows.
- **Web + API** — `src/mavenu/web.py`: P05 pages (`/project05`, `/project05/checks`, `/project05/alerts`, `/project05/incidents`, `/project05/jobs`, `/project05/rules`, `/project05/policies`, `/project05/runbooks`) + `/api/governance/*` JSON endpoints.
- **Migration** — `src/mavenu/migrations/023_governance.sql` (11 tables; `023_governance.down.sql` drops them).
- **Tests** — `tests/test_governance.py` (23 service tests) + `tests/test_governance_api.py` (13 API + page tests). **36 total, all passing.**
