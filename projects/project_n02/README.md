# N02 — Cyber Risk Assessment & Management

**Status: Implemented · Tested** — 67 automated tests, all passing
(1484/1484 full suite: 1417 prior + 67 new; zero regressions).

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**
> "Synthetic Test Co." does not exist. Every asset, threat, likelihood /
> impact rating, remediation cost, and effort figure in this project is
> invented. The scores are illustrative worked examples of the documented
> scoring rules — **never** an audit opinion, a certification, or a claim
> about any real organization.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Risk-workbook engine (`src/mavenu/risk.py`): documented 1–5 likelihood and impact scales with per-level rationale; scoring rule `score = likelihood × max(C,I,A)`; band thresholds (low 1–4 / medium 5–9 / high 10–15 / critical 16–25); control registry built **live** from the S01/S02 modules (never duplicated) with reference validation; register builder with structural traceability checks; `register_audit()` completeness check; remediation planner with the documented risk-reduction-per-effort prioritization rule (exact `Fraction` arithmetic, deterministic tie-break); residual-risk recomputation with reconciled totals; SQLite persistence via migration `019_risk.sql` + down-step, rollback tested for real |
| What is SIMULATED | **Simulated** | The deterministic demo fixtures: the seeded workbook (14 assets, 10 threats, 17 risks, 8 remediations) is produced by `seed_demo()` from the in-code fixture — a reproducible stand-in for a facilitator-led assessment, not a real one |
| What is SYNTHETIC | **Synthetic** | The fictional company ("Synthetic Test Co."), all ratings, rationales, costs, and efforts are invented. All remediation costs/efforts are labeled **synthetic estimate** in code, DB, pages, and API |
| What is NOT claimed | — | No production deployment. No real risk assessment was performed, for anyone. No audit opinion, no certification, no penetration test. Findings do not transfer to a real organization |

## Business problem

Small businesses need a defensible way to decide *what to fix first*: an
asset inventory, a threat analysis, a scoring discipline everyone can
reproduce, a register that traces every risk to an asset, a threat, and a
control, a remediation plan ordered by risk reduction per unit of effort,
and a residual-risk statement that shows what remains after the plan.

## Implemented capabilities

- **Fictional company + synthetic asset inventory** (`ASSETS`, 14 rows):
  hardware / software / data / people / facilities schema.
- **Threat catalog** (`THREATS`, 10 threats), each mapped to an S01/S02
  vulnerability class and to the asset types it applies to.
- **Scoring engine** (`score_risk`, `band_for_score`): documented 1–5
  likelihood and impact scales with per-level rationale; impact =
  max(C,I,A); bands low 1–4, medium 5–9, high 10–15, critical 16–25.
- **Risk register** (17 entries): every entry structurally traces to an
  asset + a threat + ≥1 control; every score carries its scale levels and
  a written rationale.
- **Control mapping**: references validated live against the S01 firewall
  ruleset, S01 alert types, and S02 hardening baselines — the mapping
  breaks loudly if a referenced control is renamed or removed instead of
  silently pointing at a stale copy. `GAP` = explicit accepted gap with a
  written reason. `register_audit()` enforces: every high/critical risk
  has ≥1 real control or an accepted-gap record.
- **Remediation planner** (8 remediations): synthetic cost (Decimal-exact
  cents) and effort per remediation, each labeled synthetic; prioritized
  by the documented reproducible rule (risk-reduction-per-effort ratio
  descending, `rem_id` tie-break — input order cannot change the output).
- **Residual-risk statement**: register recomputed after applying all
  planned remediations; per-risk deltas; totals reconcile
  (inherent 177 → residual 79, reduction 98; 0 high/critical remain).
- **Web UI + JSON API** (`web.py`): `/project_n02` (workbook hub),
  `/project_n02/scales`, `/project_n02/register`,
  `/project_n02/remediation`, `/project_n02/residual`;
  `/api/risk/{assets,threats,scales,register,controls,remediations,residual}`,
  `POST /api/risk/seed`.

## Test summary

67 new tests: scales + band boundaries (incl. 15 vs 16 boundary in real
fixture rows), register structural traceability (no orphans),
control-reference validation, high/critical mapping completeness,
prioritization reproducibility (25 seeded shuffles) + tie-break,
residual ≤ inherent per risk + totals reconciliation, synthetic cost/effort
labeling, DB round-trips, migration rollback for real. The suite caught
**1 real bug pre-ship**: remediation reduction was summed per *effect*,
double-counting a remediation with two effects on one risk (RM-04:
18 → corrected 9).

## Key numbers (synthetic fixture)

- 17 risks: 2 critical, 8 high, 6 medium, 1 low.
- Priority order: RM-05 → RM-02 → RM-03 → RM-06 → RM-08 → RM-01 → RM-07 → RM-04.
- Residual after the full plan: total 177 → 79; 0 critical, 0 high remain.
