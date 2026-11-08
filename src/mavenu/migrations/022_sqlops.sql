-- 022_sqlops.sql — Project P04 (SQL Operations Intelligence) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. The operational rows this
-- layer analyses (leads, missed calls, estimates, invoices, payments,
-- documents) are invented fixtures from the other portfolio projects.
-- This is a SQL analytics layer over that synthetic data — not a
-- production database, not a BI tool for real business records, and not
-- a substitute for real reporting controls.
--
-- Security thesis (enforced in sqlops.py, never in SQL text):
--   * No user input ever reaches SQL text. A query is a structured
--     spec (table, dimensions, metrics, filters, grain, period) stored
--     as JSON; the compiler maps every identifier through an
--     allow-listed registry and binds every value as a `?` parameter.
--     Anything outside the registry is rejected before any SQL runs.
--   * Money is INTEGER cents in the source tables and Decimal at the
--     service layer (never float). Averages and rates are computed in
--     Python from exact COUNT/SUM aggregates — SQLite AVG is never used
--     for money.
--
-- Design notes:
--   * sqlops_queries: saved queries, versioned. A definition is NEVER
--     edited in place — a change supersedes the current version and
--     inserts a new one, so old runs stay reproducible against the
--     exact spec they executed. `spec_json` is the frozen query spec.
--   * sqlops_runs: one row per execution, with the frozen spec, the
--     period, the result rows (JSON, capped), row count, duration in
--     milliseconds, status, and actor. Every execution is audited —
--     including failed ones (status 'error' with the error text).
--   * sqlops_snapshots: a materialised result of a run. The
--     fingerprint is SHA-256 over the canonical spec + period + result
--     rows, so staleness means "the answer changed", checked by
--     re-executing and comparing fingerprints.
--   * sqlops_events: append-only audit trail for query lifecycle
--     actions (create / supersede) and snapshots, actor-stamped.

CREATE TABLE sqlops_queries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    spec_json       TEXT NOT NULL,              -- frozen query spec (JSON)
    version         INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    status          TEXT NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'superseded')),
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    superseded_by   INTEGER,                    -- id of the version that replaced this one
    UNIQUE (name, version)
);

CREATE INDEX idx_sqlops_queries_name ON sqlops_queries(name, status);

CREATE TABLE sqlops_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id        INTEGER NOT NULL REFERENCES sqlops_queries(id),
    query_version   INTEGER NOT NULL,
    spec_json       TEXT NOT NULL,              -- frozen spec as executed (JSON)
    period_start    TEXT NOT NULL,              -- ISO date YYYY-MM-DD
    period_end      TEXT NOT NULL,              -- ISO date YYYY-MM-DD
    status          TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error')),
    rows_returned   INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    result_json     TEXT NOT NULL DEFAULT '[]', -- result rows (JSON, capped)
    error_text      TEXT,                       -- set when status = 'error'
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_sqlops_runs_query ON sqlops_runs(query_id, id);

CREATE TABLE sqlops_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES sqlops_runs(id),
    query_id        INTEGER NOT NULL REFERENCES sqlops_queries(id),
    query_version   INTEGER NOT NULL,
    fingerprint     TEXT NOT NULL,              -- SHA-256 hex (spec + period + results)
    result_json     TEXT NOT NULL,              -- materialised result rows (JSON)
    row_count       INTEGER NOT NULL DEFAULT 0,
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_sqlops_snapshots_run ON sqlops_snapshots(run_id);

-- Append-only audit trail: application code never UPDATEs or DELETEs
-- this table.
CREATE TABLE sqlops_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,              -- 'query' | 'run' | 'snapshot'
    entity_id       INTEGER NOT NULL,
    event_type      TEXT NOT NULL,              -- e.g. query.created
    actor           TEXT NOT NULL,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_sqlops_events_entity ON sqlops_events(entity_type, entity_id, id);
