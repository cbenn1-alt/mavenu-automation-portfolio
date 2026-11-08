# Career-Evidence Matrix

Honesty-graded capability map for the portfolio, per the execution spec
(Section 18). Three classifications:

- **Verified** — implemented and tested in the actual target technology.
- **Transferable** — demonstrated with an alternative technology; the
  engineering principles carry over, but it is not hands-on platform proof.
- **Not yet demonstrated** — planned, blocked, or unverified.

> This matrix does not claim the portfolio substitutes for employment
> experience, and transferable evidence does not prove hands-on proficiency
> with a specific commercial platform.

**Portfolio scope as of 2026-11-08:** 23 projects live on GitHub
(`cbenn1-alt/mavenu-automation-portfolio`, main) — baseline P01–P05
(Gates A–E), Q01–Q10, S01–S05, N01–N03. Full suite **1,757 passed /
1,759 collected**; the 2 failures are pre-existing and unrelated
(Q05 aging + estimates cadence — date-dependent fixtures written for
2026-10-23, reproducing on the pristine tree). Migrations 001–023.
All data synthetic; no production deployment, no real clients, no bank
approval.

| Capability | Grade | Evidence (as of 2026-11-08) |
|---|---|---|
| SQL | **Verified** | Schema design with PKs/FKs and indexes (`migrations/001_core.sql` through `023_governance.sql`); versioned migrations with tested down-steps; parameterized queries throughout; `GROUP BY` analytics and reconciliation queries (`stats()`); duplicate/orphan-style detection (`possible_duplicate_of`); dashboard reconciled to source rows by test. Deepened by P04 SQL Operations Intelligence: versioned saved queries as structured specs (never raw SQL), allow-list compiler with bound parameters, Decimal-exact math (never float division), drill-down lineage from any figure to source rows, period-over-period comparison, SHA-256 snapshots, and a full audit log of query runs (80 tests). Q07 adds 5 versioned Decimal KPI formulas with per-location and cross-location rollup and restatement log |
| Power Automate | **Not yet demonstrated** | No platform access. Project 02 implements the workflow on the custom stack (transferable concepts: triggers, multi-step approvals, delegation, SLA escalation, state machine, audit trail — 101 tests), but that is not hands-on Power Automate proof and is never claimed as such |
| Power Apps | **Not yet demonstrated** | No platform access |
| SharePoint Online | **Not yet demonstrated** | No platform access |
| UiPath | **Not yet demonstrated** | No access |
| AI-enabled automation | **Transferable** | `LeadClassifier` protocol with confidence-threshold routing; uncertain outputs go to human review (tested). Deepened by P03 AI Document Intelligence: deterministic rule-based field extraction for invoices/receipts/contracts with per-field confidence + provenance and a 0.80 human-gated threshold, plus an exception queue (73 tests); by Q04 conversational booking agent (8-state dialogue manager, injection denylist, handoff on low confidence); and by Q01 urgency scoring. The bundled classifiers/extractors are deterministic rules, **not** trained models — the automation pattern is verified, model proficiency is not |
| Testing and UAT | **Verified** | 1,757 automated tests passing (unit + service + HTTP) across 23 projects; acceptance criteria mapped 1:1 to tests in each project's `TEST_PLAN.md`; real results in each `TEST_RESULTS.md`; live smoke tests on a real server per project; rollback down-steps exercised by test. The 2 known failures are pre-existing date-dependent fixtures (Q05 aging, estimates cadence), documented in `TEST_RESULTS.md`, not hidden |
| Documentation & change control | **Verified** | 23 projects × 9 docs each (README/ARCHITECTURE/REQUIREMENTS/TEST_PLAN/TEST_RESULTS/SECURITY/RUNBOOK/DEMO/EVIDENCE_MATRIX); DB migrations 001–023 versioned with down-steps; append-only audit trail of every state change; per-project evidence matrices mapping claims to artifacts; build log recording every project, test count, and commit |
| Monitoring & troubleshooting | **Verified** | Project 05 Reliability & Governance Center (36 tests): 5 health-check probes (DB, migrations, queue depth, storage, app smoke) with pass/degraded/fail states and a status summary; retry policies as versioned data with exact assertable backoff math, dead-letter + replay; alerting rules with thresholds, dedup windows, and silence rules — **alerts are recorded only and never sent** (no send path exists by architecture); versioned runbooks with a timed walkthrough harness; incident lifecycle (open→triaged→mitigating→resolved→closed + reopen) with actor-stamped timelines. Caveat: probes run against the local synthetic system; there is no production telemetry and no live alert delivery |
| Access controls & auditability | **Partial** | Auditability **Verified** (every transition records actor + timestamp, tested; P04 audits every query run including failures; P05 keeps actor-stamped incident timelines). Access controls **Not yet demonstrated** (reviewer actions are actor-labeled, not authenticated — demo scope) |

## How the grades move

- Project 02 (request/approval automation) → **done 2026-10-23**: workflow-automation evidence is **Verified** on the custom stack; Power Automate stays **Not yet demonstrated** without access, and will never be claimed otherwise.
- Project 04 (SQL Operations Intelligence) → **done 2026-11-08**: SQL **Verified** grade deepened (versioned saved queries, allow-list compiler, drill-down lineage, Decimal math, run audit).
- Project 05 (Reliability & Governance) → **done 2026-11-08**: monitoring moved from **Transferable** to **Verified** on the custom stack, with the recorded-only alerting caveat above.
- Project 03 (AI Document Intelligence) → **done 2026-11-08**: AI-enabled automation deepened within **Transferable** (deterministic extraction, confidence + provenance, human-gated exceptions); it does not move to **Verified** for model proficiency, because no trained model is involved.
- What would move the remaining rows: hands-on access to Power Automate / Power Apps / SharePoint Online / UiPath (a trial, a lab tenant, or an employer environment) for the platform rows; authenticated roles for the access-controls half of the last row. Nothing in this matrix is a substitute for that access.
