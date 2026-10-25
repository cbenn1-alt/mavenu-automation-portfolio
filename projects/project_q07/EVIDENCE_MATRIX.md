# Q07 — Evidence Matrix

Every public claim about this project, mapped to the test or artifact that
backs it. Anything not in this table is not claimed.

| Claim | Evidence | Label |
|---|---|---|
| Per-location CSV ingest with configured schema maps (mapping configured, not assumed) | `tests/test_kpi_rollup.py` — three fixtures with deliberately different headers ingested through three different maps; `test_register_location_requires_all_canonical_fields` | Implemented + Tested |
| Row-level validation; bad rows quarantined with reasons | `test_ingest_stages_good_rows_and_quarantines_bad` (`invalid_revenue:abc`), `test_ingest_missing_job_id_quarantined` | Implemented + Tested |
| Zero silent drops: every input row staged or quarantined; every quarantine entry has a reason | `test_zero_silent_drops_every_row_staged_or_quarantined_with_reason` | Implemented + Tested |
| Schema drift: unknown column → quarantine + alert, good rows still flow | `test_schema_drift_unknown_column_alerts_but_good_rows_flow` | Implemented + Tested |
| Schema drift: missing mapped column → all rows quarantined + alert | `test_schema_drift_missing_mapped_column_quarantines_all_rows` | Implemented + Tested |
| KPI values match hand computations exactly (Decimal) | `test_kpi_values_match_hand_computation_{north,south,west}`, `test_rollup_matches_hand_computation`; `_hand()` in the test file | Implemented + Tested |
| Rollup equals sum of location inputs; average_ticket is weighted | `test_rollup_equals_sum_of_location_inputs` | Implemented + Tested |
| 100% of rollup totals drill to source rows | `test_rollup_lineage_covers_every_source_row` (7/7 rows per value; recompute from lineage reproduces the value), `test_location_lineage_traces_to_that_location_only` | Implemented + Tested |
| Re-upload is a no-op; no double counting | `test_reingest_same_csv_is_idempotent` | Implemented + Tested |
| Job IDs are location-scoped (same ID in two shops kept) | `test_location_scoped_ids_no_cross_location_merge` | Implemented + Tested |
| KPI definitions versioned, never edited in place | `test_definition_update_supersedes_never_edits` | Implemented + Tested |
| Definition change → restatement log, old values preserved, new values recomputed | `test_restatement_preserves_old_values_and_recomputes_new` (4 log entries; v2 margin hand-checked; old value + lineage kept) | Implemented + Tested |
| Migration rollback works for real | `test_migration_010_down_step_rolls_back_for_real` (apply → use → roll back → other tables intact → re-apply) | Implemented + Tested |
| Web pages + JSON API work end to end | `tests/test_kpi_rollup_api.py` (16 tests: upload, compute, dashboard, lineage, quarantine, alerts, definitions, restate, page renders) | Implemented + Tested |
| All data is synthetic; not audited financials | banner on every page; README honest-status banner; fixture headers in test files | Synthetic / Demo (labeled) |
| Fixture locations and their dialects | `tests/test_kpi_rollup.py` fixtures | Simulated (labeled) |
| $50 callback rework cost in gross_margin v2 | `kpi_defs.V2_GROSS_MARGIN_DOC` + SECURITY.md — disclosed placeholder assumption | Simulated assumption (labeled) |

## Explicitly not claimed (no evidence exists, none is offered)

- Production deployment, real users, real businesses, real financials.
- Platform or employer endorsement.
- Authenticated actor identities (actor stamps are form/API fields).
