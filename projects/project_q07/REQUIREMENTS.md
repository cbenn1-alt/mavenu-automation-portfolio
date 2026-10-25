# Q07 — Requirements

## Problem statement

Firms with 2–5 locations track each shop in its own spreadsheet. The owner
can't answer "which location is actually profitable this month?" without a
day of manual work.

**Target user.** Multi-location home-service owners; franchise-style
operators.

## Functional requirements

1. **Ingest per-location CSVs** (jobs, revenue, costs, callbacks) with
   **per-location schema mapping**. Columns differ between locations; the
   mapping is configured (stored JSON), never assumed.
2. **Standardized KPI set**: revenue, gross margin, callback rate, average
   ticket, bookings per tech-day. Documented formulas; what each metric
   includes and excludes is written down, not implied.
3. **Rollup with drill-down**: every consolidated number traces to the
   location rows that fed it. 100% of rollup totals must drill to source
   rows (verified row-by-row in tests).
4. **Synthetic location data**; schema drift handled explicitly.

## Non-functional requirements

- **Zero silent drops**: every input row is either staged or quarantined;
  every quarantined row/column carries a reason.
- **Exact arithmetic**: KPI values match hand computations exactly (Decimal,
  never float; money to cents, rates to 6dp).
- **No double counting**: idempotent ingest batches; location-scoped job IDs.
- **Definition changes never rewrite history**: versioned definitions;
  restatement log; old values preserved (superseded).
- **Rollback**: migration down-step tested for real.

## Failure modes and mitigations (from spec §2)

| Failure | Mitigation | Test |
|---|---|---|
| Schema drift breaks ingestion | schema-version check; unknown column → quarantine + alert, good rows still flow; missing mapped column → all rows quarantined + alert | `test_schema_drift_unknown_column_alerts_but_good_rows_flow`, `test_schema_drift_missing_mapped_column_quarantines_all_rows` |
| Double-counting across locations | location-scoped IDs; label-keyed ingest batches; UNIQUE(ingest_id, source_row) | `test_reingest_same_csv_is_idempotent`, `test_location_scoped_ids_no_cross_location_merge` |
| KPI definition changes rewriting history | versioned definitions (never edited in place); restatement log; old values superseded, not deleted | `test_definition_update_supersedes_never_edits`, `test_restatement_preserves_old_values_and_recomputes_new` |

## Out of scope

- Real accounting integration, tax handling, or payroll (the CSV is the
  source of truth for the demo).
- Multi-currency, multi-period comparisons, forecasting.
- Authentication/authorization (actor stamps are form/API fields).
- Anything that touches real business financial data — there is none.

## Measurable performance criteria (spec §2)

- Zero silent drops: every quarantined row has a reason (asserted).
- KPI values match hand computations exactly (asserted, Decimal equality).
- 100% of rollup totals drill to source rows (verified row-by-row).
