# N02 — Test Plan

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**

67 tests across `tests/test_risk.py` (51) and `tests/test_risk_api.py`
(16). Run with the repo venv:

```
cd ~/workspace/mavenu-portfolio
.venv/bin/python -m pytest tests/test_risk.py tests/test_risk_api.py -q
```

## 1. Ethical / fictional-company hard line (3)

- Banner contains FICTIONAL / SYNTHETIC / "NEVER an audit opinion".
- `COMPANY["fictional"] is True`; name is "Synthetic Test Co.".
- All assets carry synthetic ids and a valid asset type.

## 2. Scales (5)

- Likelihood and impact scales each have 5 levels with non-empty label +
  rationale.
- `impact == max(C,I,A)` (e.g. `score_risk(3,2,5,1)` → impact 5, score 15).
- Levels outside 1–5 rejected (0, 6, −1, 2.5, "3", True).

## 3. Band thresholds (4, incl. boundary tests)

- Parametrized boundaries: 1→low, 4→low, 5→medium, 9→medium, 10→high,
  15→high, 16→critical, 25→critical.
- Explicit 15-vs-16 boundary test.
- Real fixture rows span the boundary: R-02 = 15/high, R-01/R-08 =
  16/critical.
- Scores 0/26/−3 rejected.

## 4. Control registry (4)

- Registry built live from S01/S02: 15 + 13 + 9 = 37 refs; spot-checks
  `S02:auth-01`, `S01:deny-wan-inbound`, `S01:alert:port_scan_detected`.
- Unknown refs rejected (`S01:no-such-rule`, `S03:anything`).
- `GAP` validates as the accepted-gap marker.
- Every control ref in the register fixture resolves; every `GAP` has a
  written reason.

## 5. Register structural traceability (8)

- 17 entries; band counts 2 critical / 8 high / 6 medium / 1 low.
- **Structural assertion:** every entry traces to a known asset AND a
  known threat whose `applies_to` covers the asset's type AND ≥1 control
  — no orphan entries.
- Every score cites its scale levels (`L<n>` in the likelihood rationale,
  `Impact <n>` in the impact rationale) and `score == likelihood × impact`.
- `register_audit()` returns `[]` (every high/critical risk has ≥1
  control or an explicit accepted-gap record).
- Threat catalog has ≥8 threats, each with a vulnerability class.
- Register sorted by severity (band, score, id).
- Negative tests: duplicate `risk_id` rejected; `GAP` without reason
  rejected.

## 6. Remediation prioritization (6)

- 8 remediations; every cost/effort basis contains "synthetic";
  every reduction > 0 and effort > 0.
- **Double-count regression:** RM-04's two effects on R-11 count as one
  risk delta (9, not 18).
- Priority order equals ratio-descending: RM-05 → RM-02 → RM-03 → RM-06
  → RM-08 → RM-01 → RM-07 → RM-04.
- Reproducibility: 25 seeded shuffles of the input produce the identical
  order.
- Tie-break: RM-02 (9/8) sorts before RM-03 (9/8) by `rem_id`.
- A remediation that would raise a level is rejected.

## 7. Residual risk (5)

- Residual ≤ inherent per risk (all 17).
- Totals reconcile: inherent 177 − residual 79 == Σ deltas == 98;
  band counts sum to 17.
- 0 critical and 0 high remain after the full plan.
- Unremediated risks (R-13, R-17) keep inherent scores (delta 0).
- Residual memo is bannered synthetic / not-an-audit-opinion.

## 8. DB persistence (8)

- `seed_demo()` inserts 14 assets / 10 threats / 17 risks / 8 remediations
  / 2 snapshots.
- Re-seed is idempotent (identical register).
- Stored rows recompute identically to the in-code fixture.
- Money round-trips exactly (`RM-01` = "1200.00", `RM-06` = "0.00");
  cost/effort bases labeled synthetic.
- `list_remediations()` returns the prioritized order with `ratio_exact`.
- Snapshots capture inherent (177) and residual (79, reduction 98).
- `seeded()` flag false → true.
- `get_residual_report()` reconciles from the DB.

## 9. Migration rollback (2)

- `rollback_migration("019_risk.sql")` drops all N02 tables; re-apply
  works; re-seed works.
- Rollback leaves other tables (e.g. N01's) intact.

## 10. Web/API (16)

- Pages (8): unseeded hub offers seeding; seeded hub shows counts and
  section links; scales page documents both scales, bands, and the
  prioritization rule; register page lists all 17 risks incl. GAP rows;
  remediation page shows plan order (RM-05 before RM-04) with synthetic
  labels; residual page shows memo + deltas; nav links present; every
  page carries the honest banner.
- API (8): unseeded reads 404; scales endpoint always available with
  banner; controls endpoint lists the 37-ref live registry; seed endpoint
  idempotent; register endpoint (17 rows, empty audit violations,
  R-01 = 16/critical with rationales); remediations endpoint in priority
  order with synthetic bases; residual endpoint reconciles
  (177 → 79, Σ deltas = 98, residual ≤ inherent); assets/threats
  endpoints return 14/10 rows.
