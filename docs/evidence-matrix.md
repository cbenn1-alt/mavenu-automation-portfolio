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

| Capability | Grade | Evidence (as of 2026-10-22) |
|---|---|---|
| SQL | **Verified** | Schema design with PKs/FKs and indexes (`migrations/001_core.sql`); versioned migrations; parameterized queries throughout; `GROUP BY` analytics and reconciliation queries (`stats()`); duplicate/orphan-style detection (`possible_duplicate_of`); dashboard reconciled to source rows by test |
| Power Automate | **Not yet demonstrated** | No platform access. Project 02 will implement the workflow on the custom stack (transferable concepts: triggers, approvals, state) |
| Power Apps | **Not yet demonstrated** | No platform access |
| SharePoint Online | **Not yet demonstrated** | No platform access |
| UiPath | **Not yet demonstrated** | No access |
| AI-enabled automation | **Transferable** | `LeadClassifier` protocol with confidence-threshold routing; uncertain outputs go to human review (tested). The bundled classifier is deterministic rules, **not** a trained model — the automation pattern is verified, model proficiency is not |
| Testing and UAT | **Verified** | 51 automated tests (unit + service + HTTP); acceptance criteria mapped 1:1 to tests in `TEST_PLAN.md`; real results in `TEST_RESULTS.md` |
| Documentation & change control | **Verified** | Per-project README/ARCHITECTURE/REQUIREMENTS/TEST_PLAN/TEST_RESULTS/SECURITY/RUNBOOK/DEMO; DB migrations versioned; append-only audit trail of every state change |
| Monitoring & troubleshooting | **Transferable** | Structured JSON operational logs; live dashboard; audit timeline per record; deliberate-failure drill documented. Full reliability center is Project 05 (planned) |
| Access controls & auditability | **Partial** | Auditability **Verified** (every transition records actor + timestamp, tested). Access controls **Not yet demonstrated** (reviewer actions are actor-labeled, not authenticated — demo scope) |

## How the grades move

- Project 02 (request/approval automation) → workflow-automation evidence to **Verified** on the custom stack; Power Automate stays **Not yet demonstrated** without access, and will never be claimed otherwise.
- Project 04 (SQL Operations Intelligence) → deepens the SQL **Verified** grade (data-quality checks, reconciliation).
- Project 05 (Reliability & Governance) → monitoring moves toward **Verified**.
