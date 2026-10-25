# Q07 — Architecture

```
CSV (north dialect) ─┐
                     ├─▶ ingest/ ──▶ validate/ ──▶ staging (kpi_staging)
CSV (south dialect) ─┤        │            │
                     │        │            └─▶ quarantine (kpi_quarantine, reason)
CSV (west dialect) ──┘        │
              schema maps     └─▶ alerts (kpi_alerts: schema_drift)
              (kpi_schema_maps, JSON, versioned)

staging ──▶ kpi/ ──▶ kpi_values + kpi_lineage ──▶ rollup/
            (versioned formulas)      (drill-down)

kpi_definitions ──▶ restatement ──▶ kpi_restatements (append-only)
(old versions kept)
```

## Modules

- `src/mavenu/kpi_defs.py` — versioned KPI definitions. `KpiDefinition`
  (name, version, formula, includes, excludes, status); `compute_kpi` /
  `compute_all` / `aggregate` — pure Decimal functions; `seed_default_definitions`,
  `get_current_definitions`, `update_definition` (supersedes, never edits).
- `src/mavenu/kpi_pipeline.py` — `register_location`, `get_schema_map`,
  `ingest_csv`, `resolve_alert`, `compute_location_kpis`, `compute_rollup`,
  `get_drilldown`, `restate_period`, plus read helpers for the web layer.
  Clock is injectable (`clock` param, defaults to `db.utcnow_iso`).

## Data model (migration `010_kpi_rollup.sql`)

| Table | Purpose |
|---|---|
| `kpi_locations` | one row per shop; `code` is the natural idempotency key |
| `kpi_schema_maps` | configured JSON map (canonical → CSV column), UNIQUE(location, version) |
| `kpi_ingests` | one row per uploaded CSV batch; UNIQUE(location, period, label) — the dedup key |
| `kpi_staging` | normalized job rows; money as Decimal text; UNIQUE(ingest_id, source_row) |
| `kpi_quarantine` | every rejected row/column WITH a reason; `source_row` NULL = column-level (drift) |
| `kpi_alerts` | `schema_drift` / `ingest_failed` alerts; resolved by a named actor |
| `kpi_definitions` | versioned KPI formulas + includes/excludes; UNIQUE(name, version); status current/superseded |
| `kpi_values` | computed values; `location_id` NULL = rollup; UNIQUE(period, COALESCE(location,-1), kpi, definition); status current/superseded |
| `kpi_lineage` | (kpi_value_id, staging_row_id) — the drill-down guarantee |
| `kpi_restatements` | append-only: period, old→new definition, reason, actor |
| `kpi_events` | append-only, actor-stamped audit trail |

## Design decisions (and why)

1. **Schema maps are data, not code.** Each shop's dialect is a JSON row,
   so a new location is a registration, not a deploy. The map is validated
   at registration (all six canonical fields required, no unknown fields).
2. **Ingest batches, not just rows.** The dedup key is (location, period,
   label) at batch level plus (ingest_id, source_row) at row level. This
   makes re-upload a clean no-op while letting a *different* CSV for the
   same period be a new batch — no `source_row` collision, no double count.
3. **Quarantine is never silent.** Column-level drift entries use
   `source_row` NULL so "every input row staged-or-quarantined" stays
   checkable while drift data is still held, not dropped.
4. **Lineage is written with the value, rewritten on recompute.** Deleting
   then re-inserting lineage per value keeps the drill-down exact even
   after restatements; the old (superseded) value rows keep their old
   lineage rows.
5. **Definitions are rows, formulas are text + code.** The DB stores the
   human-readable formula and includes/excludes; `kpi_defs.compute_kpi`
   implements the versioned branches (`v1` / `v2`). Adding a version means
   adding a branch + a doc tuple — the test for the new version asserts the
   doc, the formula, and the restatement path.
6. **Money is Decimal text in SQLite.** No float anywhere; rates are exact
   Decimal divisions quantized to 6dp so hand computations match byte-for-byte.

## Rationale (from spec §2)

The lineage guarantee (drill-down to source) is what makes a rollup
trustworthy; schema maps make it work in the real world where every shop
keeps its own dialect.
