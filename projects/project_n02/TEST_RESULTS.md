# N02 — Test Results

**Run date:** 2026-10-23 (22:10–22:20 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/python
-m pytest tests/ -q -p no:cacheprovider`
(run in chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run; do NOT use a
disk-backed TMPDIR)

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**

## Result

**1484 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| N02 new (`tests/test_risk.py`) | 51 | 51 passed |
| N02 new (`tests/test_risk_api.py`) | 16 | 16 passed |
| P01 + P02 + Q01–Q10 + S01 + S02 + S05 + S03 + S04 + N01 prior (1417) | 1417 | 1417 passed, unchanged |

Chunk breakdown: 390 + 333 + 93 + 54 + 84 + 221 + 184 + 125 = 1484.

One mid-run anomaly, root-caused and cleared: the first attempt at the
e–n chunk hit `OSError: [Errno 28] No space left on device` (`/tmp`
tmpfs full). Splitting that chunk into four smaller runs with
`/tmp/pytest-of-root` cleared between them made all 564 tests pass. No
test failure was involved; no code changed as a result.

## Measurable criteria — verified

- **Scales documented and applied:** every register entry's rationale
  cites its likelihood/impact levels (`test_every_score_cites_scale_levels_with_rationale`).
- **Band thresholds:** parametrized boundary tests plus real fixture rows
  R-02 = 15/high vs R-01/R-08 = 16/critical (`test_band_boundaries`,
  `test_fixture_spans_boundary`).
- **Structural traceability:** every entry resolves to asset + threat
  (threat applicable to the asset type) + ≥1 validated control ref
  (`test_every_entry_traces_to_asset_threat_control`).
- **Control-mapping completeness:** `register_audit() == []` for all
  high/critical risks (`test_control_mapping_completeness_high_critical`).
- **Prioritization reproducibility:** 25 seeded shuffles → identical
  order; deterministic `rem_id` tie-break
  (`test_prioritization_reproducible_under_shuffle`,
  `test_tie_broken_deterministically_by_rem_id`).
- **Residual reconciliation:** residual ≤ inherent per risk; inherent
  177 → residual 79; Σ deltas = 98 (`test_totals_reconcile`,
  `test_residual_never_exceeds_inherent`).
- **Synthetic labeling:** every remediation cost/effort basis contains
  "synthetic" (`test_eight_remediations_with_synthetic_cost_effort`,
  `test_remediation_money_round_trips_exact`).

## Rollback — tested for real (2026-10-23, same env)

`test_migration_019_rollback_and_reapply`: migration `019_risk.sql`
applied → workbook seeded → `rollback_migration("019_risk.sql")` dropped
all six N02 tables (`risk_assets`, `risk_threats`, `risk_register`,
`risk_remediations`, `risk_remediation_effects`, `risk_snapshots`) →
re-apply via `run_migrations()` clean → re-seed works.
`test_rollback_leaves_other_tables_intact`: N01 tables untouched.

## Bug caught pre-ship

1. **Remediation reduction double-counted per effect** — RM-04 carries
   two effects on R-11; the reduction was summed per effect (18) instead
   of per affected risk (9). Fixed in `build_remediations()`; pinned by
   `test_reduction_counted_once_per_affected_risk`.
