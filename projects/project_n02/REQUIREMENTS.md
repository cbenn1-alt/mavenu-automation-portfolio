# N02 — Cyber Risk Assessment & Management: Requirements

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**
> Scores are illustrative worked examples of the documented rules —
> **never** an audit opinion or certification.

## 1. Purpose

Build a complete, reproducible risk-management workbook for a fictional
small business: asset inventory → threat/vulnerability analysis →
documented likelihood × impact scoring → risk register → control mapping
to the S01 (firewall/monitoring) and S02 (hardening) baselines →
remediation prioritization → residual-risk statement. The workbook must be
*mechanical*: given the same inputs, anyone (or any run of the code)
reproduces the same register order, the same prioritization, and the same
residual totals.

## 2. Scope

In scope: the workbook engine, the synthetic fixture (company, assets,
threats, ratings, remediations), scoring rules, control-reference
validation, prioritization, residual recomputation, SQLite persistence,
web pages, and JSON API. Out of scope: §9 non-goals.

## 3. The fictional company profile

**"Synthetic Test Co."** — an obviously fictional 24-person residential
plumbing/HVAC services company: one leased office suite, a small on-prem
server closet, 12 office workstations, 6 field tablets, a synthetic cloud
email tenant, and a synthetic line-of-business dispatch application. No
real business is described; every datum is invented for this workbook.
The name is chosen to be unmistakably fictional.

## 4. Asset inventory schema

| Field | Type | Notes |
|---|---|---|
| `asset_id` | TEXT PK | `A-01`… stable synthetic ids |
| `name` | TEXT | Short label |
| `asset_type` | TEXT | One of `hardware`, `software`, `data`, `people`, `facilities` |
| `description` | TEXT | Synthetic description |
| `location` | TEXT | Synthetic location |

14 assets seeded (4 hardware, 3 software, 3 data, 2 people, 2 facilities).

## 5. Threat catalog

10 threats (`T-01`…`T-10`). Each threat record carries: id, name,
description, `vuln_class` (mapped to an S01/S02 vulnerability class), and
`applies_to` (the asset types the threat can target). Threats and their
vulnerability-class mapping:

| ID | Threat | Vulnerability class |
|---|---|---|
| T-01 | Phishing → credential theft | S02 weak-credentials |
| T-02 | Ransomware via unpatched endpoint | S02 unpatched-software |
| T-03 | Insider privilege abuse | S02 excessive-privilege |
| T-04 | Remote-admin brute force | S02 ssh-misconfiguration |
| T-05 | WAN inbound probing | S01 firewall-exposure |
| T-06 | Lateral movement across segments | S01 missing-segmentation |
| T-07 | Data exfiltration over DNS | S01 monitoring-gap |
| T-08 | Lost or stolen field tablet | S02 account-policy (partial — no mobile-device baseline exists) |
| T-09 | Exposed unneeded service | S02 unnecessary-services |
| T-10 | Facility break-in | none — physical, outside S01/S02 scope |

## 6. Likelihood scale (1–5, documented rationale per level)

| Level | Label | Rationale |
|---|---|---|
| 1 | Rare | No known occurrence in comparable small businesses; would require unusual conditions or a determined, resourced actor. |
| 2 | Unlikely | Possible but not observed in the fixture environment; requires meaningful attacker effort or a rare misstep. |
| 3 | Possible | Observed in comparable organizations; plausible within the next 12 months given current controls. |
| 4 | Likely | Expected within the next 12 months: conditions are favorable and similar events are routine in the sector. |
| 5 | Almost certain | Happening now or recurring; existing controls demonstrably absent or routinely bypassed. |

## 7. Impact scale (1–5 across confidentiality / integrity / availability)

Each risk rates C, I, and A separately; **impact = max(C, I, A)**.

| Level | Label | Rationale |
|---|---|---|
| 1 | Negligible | No meaningful effect on confidentiality, integrity, or availability; no customer or regulatory consequence. |
| 2 | Minor | Limited C/I/A effect confined to non-critical records or systems; recoverable the same day with routine effort. |
| 3 | Moderate | Material C/I/A effect on some customer records or business systems; requires deliberate response but not existential. |
| 4 | Major | Severe C/I/A effect: operations disrupted, broad customer data exposed, or regulatory notification obligations triggered. |
| 5 | Catastrophic | Business-ending C/I/A effect: total loss of customer trust, extended outage, or liabilities the fictional company could not absorb. |

## 8. Scoring rule and risk bands

- `impact = max(impact_c, impact_i, impact_a)`
- `score = likelihood × impact` (range 1–25)
- Bands: **low** 1–4 · **medium** 5–9 · **high** 10–15 · **critical** 16–25.

Every register entry stores the applied likelihood/impact levels **and** a
written rationale citing them (e.g. "L4 Likely: …", "Impact 4 (max of
C4/I3/A1): …"). Levels outside 1–5 are rejected (`RiskError`).

## 9. Risk register

17 entries. Each entry traces structurally to **one asset + one threat +
≥1 control** (asserted in code and tests — no orphan entries). Each entry
carries: risk id, asset, threat, vulnerability class, likelihood +
rationale, impact C/I/A + rationale, computed score + band, control list,
treatment (`mitigate`/`accept`/`transfer`/`avoid`).

## 10. Control mapping

Each risk maps to ≥1 control reference, validated **live** against the
S01/S02 modules (never duplicated):

- `S02:<baseline_id>` — S02 hardening baselines (15 items)
- `S01:<firewall_rule_id>` — S01 firewall rules (13 rules)
- `S01:alert:<alert_type>` — S01 monitoring alert types (9 types)
- `GAP` — explicit accepted gap, requiring a written reason

Because the registry is built from the imported S01/S02 modules, a
renamed or removed control breaks loudly at build/seed time instead of
silently mapping to a stale copy.

## 11. Remediation prioritization rule (documented, reproducible)

8 remediations, each with synthetic cost (Decimal-exact integer cents,
labeled "synthetic estimate") and synthetic effort hours (labeled
"synthetic estimate").

- `risk_reduction` = Σ over **affected risks** of (inherent score −
  residual score after applying only this remediation).
- `ratio` = `risk_reduction / effort_hours` (exact `Fraction` arithmetic;
  effort guarded to ≥1).
- **Order = ratio descending, ties broken by `rem_id` ascending.**
  Identical inputs always yield identical order regardless of input order
  (tested with 25 seeded shuffles).

Resulting fixture order: RM-05 → RM-02 → RM-03 → RM-06 → RM-08 → RM-01 →
RM-07 → RM-04.

## 12. Residual-risk recomputation

Applying all planned remediations (in `rem_id` order) recomputes every
affected risk's score from its new levels; a remediation may only *lower*
a level. The residual-risk statement reports: per-risk inherent →
residual scores and bands, applied remediations, per-risk deltas, and
before/after totals that reconcile
(`inherent_total − residual_total == Σ deltas`).
Fixture result: 177 → 79 (reduction 98); 0 critical, 0 high remain;
unremediated risks (R-13, R-17) keep their inherent scores by design.

## 13. Acceptance criteria

1. Scales documented with per-level rationale and applied: every score
   cites its likelihood/impact levels in written rationale.
2. Band thresholds hold at boundaries (4/5, 9/10, 15/16), exercised by
   real fixture rows (R-02 = 15/high, R-01/R-08 = 16/critical).
3. Every register entry structurally traces to asset + threat + control;
   `register_audit()` returns zero violations (all high/critical risks
   have ≥1 control or an explicit accepted-gap record).
4. Prioritization is reproducible: same inputs → identical order;
   shuffled inputs → identical order; ties deterministic.
5. Residual ≤ inherent per risk; totals reconcile.
6. All remediation costs/efforts labeled synthetic.
7. Migration `019_risk.sql` + down-step; rollback tested for real.
8. Nine docs shipped; honest-status banner; evidence matrix complete.

## 14. Non-goals

- **Not an audit.** No audit opinion is expressed about anyone.
- **Not a certification.** Nothing here certifies any organization.
- **Not a penetration test.** No testing of any real system is performed
  or implied.
- **Not transferable.** The fixture scores do not apply to any real
  business, including any business resembling the fictional one.
- **No real assessments performed.** No assessment was conducted for any
  real party.
