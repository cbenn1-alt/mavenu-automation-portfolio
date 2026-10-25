-- 012_dispatch.sql — Project Q09 (Technician Dispatch Optimizer) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every tech name, zone, skill,
-- job, window, and commitment stored here is fabricated for the demo. The
-- zone map is a fictional 4x4 grid; travel times are a deterministic model,
-- not real routing. No real people, businesses, or service territories.
--
-- Design notes:
--   * dispatch_techs / dispatch_jobs: natural-key idempotent on
--     external_id (re-seeding the same fixture is a no-op).
--   * dispatch_runs: one row per solver execution. Stores the documented
--     objective's parameters (policy_params JSON), the solver's cost, AND
--     the baseline's cost side-by-side so the honest gap is queryable.
--     cost_gap_pct = (baseline_cost - solver_cost) / baseline_cost * 100.
--   * dispatch_assignments: one row per (run, job) placed. reason_codes is
--     a JSON array of REASON_* codes — every assignment carries >= 1.
--     A job NOT in this table for a run is either infeasible (see
--     dispatch_infeasibility) or was never part of that run's input.
--   * dispatch_infeasibility: explicit per-job violated-constraint report.
--     Jobs are never silently dropped: unassigned => a row here.
--   * dispatch_overrides: append-only dispatcher overrides. kind in
--     ('pin','reassign','unpin'); reason is mandatory (>= 8 chars) and
--     audited. Current pins = latest row per job (pin/reassign set,
--     unpin clears).
--   * dispatch_events: append-only, actor-stamped audit trail.

CREATE TABLE dispatch_techs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    skills          TEXT NOT NULL,             -- JSON array of skill strings
    home_zone       TEXT NOT NULL,             -- e.g. 'A1'..'D4'
    shift_start     INTEGER NOT NULL,          -- minutes since midnight
    shift_end       INTEGER NOT NULL,
    current_load    TEXT NOT NULL DEFAULT '[]', -- JSON: pre-existing blocks
    created_at      TEXT NOT NULL,
    CHECK (shift_start < shift_end)
);

CREATE TABLE dispatch_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT NOT NULL UNIQUE,
    zone            TEXT NOT NULL,
    skill           TEXT NOT NULL,
    duration_min    INTEGER NOT NULL CHECK (duration_min BETWEEN 15 AND 480),
    priority        INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    window_start    INTEGER NOT NULL,
    window_end      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    CHECK (window_start < window_end)
);

CREATE TABLE dispatch_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    solver          TEXT NOT NULL,             -- policy name
    policy_params   TEXT NOT NULL,             -- JSON, e.g. lateness_weight
    total_cost      REAL NOT NULL,
    total_travel    INTEGER NOT NULL,          -- minutes
    total_lateness  REAL NOT NULL,             -- priority-weighted minutes
    baseline_cost   REAL NOT NULL,             -- nearest-available baseline
    baseline_travel INTEGER NOT NULL,
    cost_gap_pct    REAL NOT NULL,             -- honest margin vs baseline
    assigned_count  INTEGER NOT NULL,
    infeasible_count INTEGER NOT NULL,
    duration_ms     INTEGER NOT NULL,
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE dispatch_assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES dispatch_runs(id),
    job_id          INTEGER NOT NULL REFERENCES dispatch_jobs(id),
    tech_id         INTEGER NOT NULL REFERENCES dispatch_techs(id),
    scheduled_start INTEGER NOT NULL,          -- minutes since midnight
    scheduled_end   INTEGER NOT NULL,
    travel_minutes  INTEGER NOT NULL,          -- from previous stop / home
    reason_codes    TEXT NOT NULL,             -- JSON array, >= 1 code
    created_at      TEXT NOT NULL,
    UNIQUE (run_id, job_id),
    CHECK (scheduled_start < scheduled_end)
);

CREATE TABLE dispatch_infeasibility (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES dispatch_runs(id),
    job_id          INTEGER NOT NULL REFERENCES dispatch_jobs(id),
    violated        TEXT NOT NULL,             -- JSON array of INF_* codes
    detail          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE dispatch_overrides (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES dispatch_jobs(id),
    tech_id         INTEGER REFERENCES dispatch_techs(id),
    kind            TEXT NOT NULL CHECK (kind IN ('pin', 'reassign', 'unpin')),
    reason          TEXT NOT NULL,             -- mandatory, audited
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE dispatch_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES dispatch_runs(id),
    event_type      TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT,                      -- JSON detail
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_dispatch_assignments_run ON dispatch_assignments(run_id);
CREATE INDEX idx_dispatch_assignments_tech ON dispatch_assignments(tech_id);
CREATE INDEX idx_dispatch_infeasibility_run ON dispatch_infeasibility(run_id);
CREATE INDEX idx_dispatch_overrides_job ON dispatch_overrides(job_id);
CREATE INDEX idx_dispatch_events_run ON dispatch_events(run_id);
CREATE INDEX idx_dispatch_events_type ON dispatch_events(event_type);
