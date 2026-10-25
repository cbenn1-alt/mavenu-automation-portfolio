# N02 — Architecture

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**

## 1. Module layout

```
src/mavenu/risk.py                  # workbook engine (single module)
src/mavenu/migrations/019_risk.sql  # schema (assets, threats, register,
                                    # remediations, effects, snapshots)
src/mavenu/migrations/019_risk.down.sql
src/mavenu/web.py                   # /project_n02* pages + /api/risk* endpoints
tests/test_risk.py                  # engine + DB tests (51)
tests/test_risk_api.py              # web/API tests (16)
```

One module was chosen deliberately: the workbook is a single pipeline
(fixture → validate → score → map → prioritize → residual) with no
natural service boundary. `web.py` only renders; it contains no scoring
logic.

## 2. Data flow

```
REGISTER_FIXTURE (17 raw rows)
  → build_register(): structural validation + score_risk() → scored register
  → register_audit(): high/critical control completeness
  → build_remediations(): solo-apply each remediation → reduction + ratio
  → prioritize(): ratio desc, rem_id asc
  → residual_statement(): apply_remediations() all → deltas + reconciled totals
  → seed_demo(): persist fixtures + inherent/residual snapshots
```

## 3. Scoring engine

- `score_risk(likelihood, c, i, a)`: validates 1–5 ints, `impact = max`,
  `score = L×I`, `band_for_score()` over the documented thresholds.
- `band_for_score()`: raises `RiskError` outside 1–25 (no silent clamp).

## 4. Control registry (live references, never duplicated)

`_build_control_registry()` indexes the S01/S02 modules at import time:

- `S02:<id>` from `ossec.BASELINES` (15)
- `S01:<rule_id>` from `firewall.RULESET` (13)
- `S01:alert:<id>` from `netsec.ALERT_TYPES` (9)

`validate_control_ref()` accepts those refs plus the `GAP` marker
(explicit accepted gap — the register entry must carry a written reason).
Importing the modules (not copying their content) means a renamed or
removed S01/S02 control fails fast at build/seed time.

## 5. Register validation (structural, in `build_register`)

- Unique `risk_id`s; known `asset_id` and `threat_id`.
- Threat `applies_to` must cover the asset's type.
- ≥1 control ref per entry; every ref validates; `GAP` requires a reason.
- Written likelihood and impact rationale required.
- Output sorted by severity (band, score, id) — deterministic display order.

## 6. Remediation model

`REMEDIATION_FIXTURE`: id, title, description, `cost_usd_cents` (int),
`cost_basis`, `effort_hours` (int), `effort_basis`, `effects` (list of
`{risk_id, field, new_value}` where field ∈ likelihood/impact_c/impact_i/
impact_a). Effects only lower levels (`apply_remediations` rejects any
raise). Reduction is computed per **affected risk** (one score delta per
risk — the suite caught a per-effect double-count pre-ship).

`prioritize()` sorts by exact `Fraction(reduction, effort)` descending,
`rem_id` ascending. The web/API layer converts the ratio to float +
exact string for JSON.

## 7. Residual risk

`apply_remediations()` deep-copies the register, applies effects in
`rem_id` order, recomputes scores. `residual_statement()` returns the
residual register, per-risk deltas (sorted by delta desc), before/after
`register_totals()` (counts + band histogram + total score), and the
bannered memo. An internal `assert` pins the reconciliation identity
`inherent − residual == Σ deltas`.

## 8. Persistence

Tables: `risk_assets`, `risk_threats` (`applies_to` as JSON),
`risk_register` (rated levels + rationale + `controls_json`; scores are
**recomputed**, never stored as hand-typed values, so rows cannot drift
from the rules), `risk_remediations` (money as INTEGER cents —
Decimal-exact; `cost_basis`/`effort_basis` labeled "synthetic estimate"),
`risk_remediation_effects`, `risk_snapshots` (inherent + residual JSON).
`seed_demo()` is idempotent (clears N02 rows first, then inserts).

## 9. Web/API surface

Pages: `/project_n02` (hub), `/project_n02/scales`,
`/project_n02/register`, `/project_n02/remediation`, `/project_n02/residual`,
`POST /project_n02/seed`. API: `GET /api/risk/{assets,threats,scales,
register,controls,remediations,residual}`, `POST /api/risk/seed`.
All JSON responses carry `"synthetic": true` and the ethical banner;
unseeded read endpoints return 404 with an error envelope.

## 10. Error handling

`RiskError(ValidationError)` carries a single-message `field_errors`
dict so the web layer's existing `ValidationError` handler renders it as
a 400. Money uses `Decimal` (cents in the DB).
