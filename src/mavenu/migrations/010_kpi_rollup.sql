-- 010_kpi_rollup.sql — Project Q07 (Multi-Location KPI Rollup Pipeline)
-- schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Location names, job IDs,
-- revenue, costs, and tech-day figures are fabricated fixtures for
-- demonstration. No real business financial data exists anywhere in this
-- project, and nothing here is a substitute for audited financials.
--
-- Design notes:
--   * kpi_locations: one row per shop location. `code` is the natural
--     idempotency key (e.g. 'north', 'south', 'west').
--   * kpi_schema_maps: the configured CSV header mapping per location
--     (canonical field -> source column), stored as JSON. UNIQUE on
--     (location_id, schema_version) so drift across versions is explicit;
--     ingest always uses the LATEST version for the location.
--   * kpi_ingests: one row per uploaded CSV batch. `label` is the
--     natural idempotency key within (location, period) — re-uploading the
--     same CSV under the same label is a no-op (deduped), while a different
--     CSV for the same period is a NEW batch (no source_row collision).
--     When the caller passes no label, it defaults to the SHA-256 of the
--     CSV text, so byte-identical re-uploads dedupe automatically.
--   * kpi_staging: normalized job rows. Money is stored as TEXT holding an
--     exact Decimal (never float). UNIQUE (ingest_id, source_row) makes
--     re-ingest of the same batch idempotent — no double counting.
--     Location-scoped IDs: a job_id is only unique within its location.
--   * kpi_quarantine: every row or column that could not be staged, WITH a
--     reason. Nothing is ever silently dropped: unknown CSV columns get a
--     per-column quarantine entry (source_row NULL) plus a schema-drift
--     alert, while the good rows still flow.
--   * kpi_alerts: schema-drift and other ingest alerts (unresolved until a
--     human marks them resolved).
--   * kpi_definitions: versioned KPI formulas. `status` is 'current' or
--     'superseded'. History is never rewritten: a definition change inserts
--     a NEW row and supersedes the old one.
--   * kpi_values: one row per (period, location_or_rollup, kpi_name,
--     definition). `location_id` NULL means the cross-location rollup.
--     UNIQUE index on (period, COALESCE(location_id,-1), kpi_name,
--     definition_id). `status` 'current'/'superseded' + restatement_id
--     preserve history through restatements.
--   * kpi_lineage: which staging rows fed which value — the drill-down
--     guarantee. 100% of rollup totals must trace to source rows.
--   * kpi_restatements: append-only log of definition changes applied to a
--     period (old definition, new definition, reason, actor).
--   * kpi_events: append-only, actor-stamped audit trail.

CREATE TABLE kpi_locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL UNIQUE,       -- natural idempotency key
    name            TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

-- Configured per-location schema maps. `map_json` is canonical field name
-- -> source CSV column. Canonical fields: job_id, completed_date, revenue,
-- costs, is_callback, tech_days.
CREATE TABLE kpi_schema_maps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id     INTEGER NOT NULL REFERENCES kpi_locations(id),
    schema_version  TEXT NOT NULL,
    map_json        TEXT NOT NULL,              -- canonical -> source column
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    UNIQUE (location_id, schema_version)
);

-- One row per uploaded CSV batch. Re-uploading the same CSV under the
-- same label is a no-op; a different CSV for the same period is a new batch.
CREATE TABLE kpi_ingests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id     INTEGER NOT NULL REFERENCES kpi_locations(id),
    period          TEXT NOT NULL,              -- 'YYYY-MM'
    label           TEXT NOT NULL,              -- natural idempotency key
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    UNIQUE (location_id, period, label)
);

CREATE INDEX idx_kpi_ingests_loc_period ON kpi_ingests(location_id, period);

CREATE TABLE kpi_staging (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ingest_id       INTEGER NOT NULL REFERENCES kpi_ingests(id),
    location_id     INTEGER NOT NULL REFERENCES kpi_locations(id),
    schema_map_id   INTEGER NOT NULL REFERENCES kpi_schema_maps(id),
    period          TEXT NOT NULL,              -- 'YYYY-MM'
    source_row      INTEGER NOT NULL,           -- 1-based data row in the source CSV
    job_id          TEXT NOT NULL,              -- location-scoped: unique per location only
    completed_date  TEXT NOT NULL,              -- 'YYYY-MM-DD'
    revenue         TEXT NOT NULL,              -- exact Decimal as text
    costs           TEXT NOT NULL,              -- exact Decimal as text
    is_callback     INTEGER NOT NULL CHECK (is_callback IN (0, 1)),
    tech_days       TEXT NOT NULL,              -- exact Decimal as text
    raw_json        TEXT NOT NULL,              -- mapped raw values for audit
    staged_at       TEXT NOT NULL,              -- UTC ISO-8601
    UNIQUE (ingest_id, source_row)              -- idempotent re-ingest
);

CREATE INDEX idx_kpi_staging_loc_period ON kpi_staging(location_id, period);
CREATE INDEX idx_kpi_staging_period ON kpi_staging(period);

-- Every quarantined row/column carries a reason. source_row NULL means the
-- entry is about a CSV COLUMN (schema drift), not a data row.
CREATE TABLE kpi_quarantine (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id     INTEGER NOT NULL REFERENCES kpi_locations(id),
    period          TEXT NOT NULL,              -- 'YYYY-MM'
    source_row      INTEGER,                    -- NULL = column-level entry
    reason          TEXT NOT NULL,              -- e.g. 'invalid_revenue:abc'
    raw_json        TEXT NOT NULL,              -- the offending raw payload
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_kpi_quarantine_loc_period ON kpi_quarantine(location_id, period);

CREATE TABLE kpi_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type      TEXT NOT NULL,              -- 'schema_drift' | 'ingest_failed'
    location_id     INTEGER REFERENCES kpi_locations(id),
    period          TEXT,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    resolved_at     TEXT,
    resolved_by     TEXT,
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_kpi_alerts_open ON kpi_alerts(resolved_at);

-- Versioned KPI definitions. `name` is the KPI (revenue, gross_margin, ...);
-- `version` is an opaque label ('v1', 'v2', ...). Only one 'current' row per
-- name; changes insert a new row and supersede the old one (never UPDATE
-- the formula in place).
CREATE TABLE kpi_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,
    formula_json    TEXT NOT NULL,              -- exact formula + rounding rules
    includes_text   TEXT NOT NULL,              -- what the metric includes
    excludes_text   TEXT NOT NULL,              -- what the metric excludes
    status          TEXT NOT NULL DEFAULT 'current'
                    CHECK (status IN ('current', 'superseded')),
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    UNIQUE (name, version)
);

-- Computed KPI values. location_id NULL = cross-location rollup total.
-- `value` is an exact Decimal as text (NULL when the formula is undefined,
-- e.g. gross_margin with zero revenue). Old rows are never deleted by a
-- restatement: they are flipped to 'superseded' and keep their lineage.
CREATE TABLE kpi_values (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,              -- 'YYYY-MM'
    location_id     INTEGER REFERENCES kpi_locations(id),
    kpi_name        TEXT NOT NULL,
    definition_id   INTEGER NOT NULL REFERENCES kpi_definitions(id),
    value           TEXT,                       -- exact Decimal as text, or NULL
    inputs_json     TEXT NOT NULL,              -- hand-checkable inputs
    status          TEXT NOT NULL DEFAULT 'current'
                    CHECK (status IN ('current', 'superseded')),
    restatement_id  INTEGER,                    -- set when superseded by a restatement
    computed_at     TEXT NOT NULL                -- UTC ISO-8601
);

CREATE UNIQUE INDEX uq_kpi_values
    ON kpi_values(period, COALESCE(location_id, -1), kpi_name, definition_id);

CREATE INDEX idx_kpi_values_period ON kpi_values(period, status);

-- Drill-down lineage: every consolidated number traces to staging rows.
CREATE TABLE kpi_lineage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kpi_value_id    INTEGER NOT NULL REFERENCES kpi_values(id),
    staging_row_id  INTEGER NOT NULL REFERENCES kpi_staging(id),
    UNIQUE (kpi_value_id, staging_row_id)
);

CREATE INDEX idx_kpi_lineage_value ON kpi_lineage(kpi_value_id);

-- Append-only restatement log.
CREATE TABLE kpi_restatements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    period              TEXT NOT NULL,
    definition_id_old   INTEGER NOT NULL REFERENCES kpi_definitions(id),
    definition_id_new   INTEGER NOT NULL REFERENCES kpi_definitions(id),
    reason              TEXT NOT NULL,
    actor               TEXT NOT NULL,
    created_at          TEXT NOT NULL           -- UTC ISO-8601
);

-- Append-only audit trail for every consequential action.
CREATE TABLE kpi_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,              -- 'location' | 'schema_map' | 'ingest' | 'kpi_value' | 'restatement' | 'definition' | 'alert'
    entity_id       INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_kpi_events_entity ON kpi_events(entity_type, entity_id, id);
