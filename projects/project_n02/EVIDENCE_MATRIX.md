# N02 — Evidence Matrix

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**
> Every public claim about N02 maps below to a test, an artifact, or a
> labeled estimate. "Estimate" means a documented judgment, not a
> measurement.

| Public claim | Evidence | Label |
|---|---|---|
| Risk-workbook engine implemented (scales, scoring, register, mapping, prioritization, residual) | `src/mavenu/risk.py` | Implemented |
| Likelihood scale 1–5 with per-level rationale | `LIKELIHOOD_SCALE` + `test_likelihood_scale_has_five_documented_levels` | Tested |
| Impact scale 1–5 across C/I/A with per-level rationale | `IMPACT_SCALE` + `test_impact_scale_has_five_documented_levels` | Tested |
| Scoring rule: score = likelihood × max(C,I,A) | `score_risk()` + `test_impact_is_max_of_cia` | Tested |
| Band thresholds low 1–4 / medium 5–9 / high 10–15 / critical 16–25 | `BANDS` + parametrized `test_band_boundaries` incl. 15-vs-16 | Tested |
| Fixture spans the 15/16 boundary in real rows | R-02 = 15/high, R-01/R-08 = 16/critical (`test_fixture_spans_boundary`) | Tested |
| Every register entry traces to asset + threat + control (no orphans) | `build_register()` structural checks + `test_every_entry_traces_to_asset_threat_control` | Tested |
| Every score cites its scale levels with written rationale | `test_every_score_cites_scale_levels_with_rationale` (17/17) | Tested |
| Control refs validated live against S01/S02 (never duplicated) | `_build_control_registry()` imports + `test_registry_built_live_from_s01_s02` (37 refs) | Tested |
| A renamed/removed S01/S02 control fails loudly | `validate_control_ref` raises `RiskError`; negative tests `test_unknown_ref_rejected` | Tested |
| Every high/critical risk has ≥1 control or an explicit accepted-gap record | `register_audit() == []` (`test_control_mapping_completeness_high_critical`) | Tested |
| Accepted gaps are recorded with written reasons, not hidden | R-08/R-12/R-16/R-17 GAP rows; `test_gap_entry_without_reason_rejected` | Tested |
| Remediation prioritization is reproducible from the scoring rules | `prioritize()` + 25 seeded shuffles → identical order (`test_prioritization_reproducible_under_shuffle`) | Tested |
| Priority order RM-05 → … → RM-04 | `test_prioritization_order_is_documented_ratio_desc`; tie RM-02 before RM-03 pinned | Tested |
| Remediation reduction counted once per affected risk | Pre-ship bug fix (RM-04: 18 → 9) pinned by `test_reduction_counted_once_per_affected_risk` | Tested |
| Residual ≤ inherent per risk | `test_residual_never_exceeds_inherent` (17/17) | Tested |
| Totals reconcile (177 → 79, Σ deltas = 98) | `residual_statement()` assert + `test_totals_reconcile` | Tested |
| All remediation costs/efforts labeled synthetic | `cost_basis`/`effort_basis` = "synthetic estimate" in code, DB, pages, API (`test_eight_remediations_with_synthetic_cost_effort`, `test_remediation_money_round_trips_exact`) | Tested |
| Money handled exactly (Decimal/integer cents) | `cost_usd_cents` INTEGER; RM-01 = "1200.00", RM-06 = "0.00" round-trip | Tested |
| Migration rollback works for real | `test_migration_019_rollback_and_reapply` (tables dropped, record removed, re-apply clean) | Tested |
| Web UI + API work end to end | `tests/test_risk_api.py` (16 tests: 5 pages + 8 API incl. seed idempotency) | Tested |
| 67 new tests, full suite green | `pytest tests/test_risk.py tests/test_risk_api.py` → 67 passed; full suite 1484 passed, 0 failed (see TEST_RESULTS.md) | Tested |
| "Scores are illustrative — never an audit opinion" | Banner in module docstring, README, all 5 pages, all API responses, residual memo | Implemented (documented) |
| "The prioritization is optimal" | **Estimate** — the rule is documented and reproducible; "optimal" for a real business would need real costs and risk appetite. Labeled Simulated. | Estimate |

## What is deliberately NOT claimed

- No production deployment; no real risk assessment performed for anyone.
- No audit opinion, no certification, no penetration test.
- The fixture scores do not transfer to any real organization.
- No real company, asset, person, or event is represented.
