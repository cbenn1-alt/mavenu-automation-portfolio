-- 023_governance.sql — Project P05 (Automation Reliability & Governance Center) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Health probes run against
-- this local demo system only; alerts are recorded in the database and
-- never sent anywhere — there is no send path in P05 by architecture.
-- Retry jobs, alert rules, runbooks, and incidents are invented fixtures
-- for demonstrating governance mechanics, not records of real operations.
--
-- Security thesis (enforced in governance.py, never in SQL text):
--   * Parameterized SQL only. Probe targets (table/column/value) come
--     from an allow-listed registry in code; anything outside it is
--     rejected before any SQL runs. No caller-supplied text ever reaches
--     SQL text.
--   * No secrets in code, no credentials, no network calls. The demo
--     server binds localhost only.
--
-- Design notes:
--   * gov_checks: health-check definitions. A check names a probe from
--     the registry plus JSON params and warn/fail thresholds on the
--     probe's numeric "badness" value: value <= warn -> pass,
--     value <= fail -> degraded, otherwise fail. Boolean probes return
--     0 (good) / 1 (bad) with warn = fail = 0.
--   * gov_check_runs: one row per probe execution, with the measured
--     value, detail, duration, status, and actor. The latest run per
--     check feeds the status summary.
--   * gov_policies: retry policies as data, versioned like P04 queries
--     (create -> v1 current; supersede -> new version current, old
--     superseded, never edited). Backoff is exponential with a cap and
--     deterministic jitter (SHA-256 of policy id + attempt), so the same
--     inputs always give the same delay.
--   * gov_jobs: retryable jobs under a policy. attempt_job records the
--     outcome the caller reports; after max_attempts the job is
--     dead-lettered and a gov_dead_letters row is written. Dead letters
--     can be replayed into a fresh job.
--   * gov_rules: alerting rules as data. A rule watches one check (or
--     any check when check_name is NULL) for a metric crossing a
--     threshold. Firing is recorded only — the "channel" is always
--     "log". Dedup windows collapse repeat firings into one alert with
--     a count; silences suppress firing (and the suppression is logged).
--   * gov_alerts: one row per distinct firing (rule + check), with
--     first/last seen and a count. Lifecycle open -> acked -> resolved
--     (open -> resolved is also allowed). Resolution is manual.
--   * gov_runbooks: versioned runbooks keyed by alert key (a severity
--     or alert type). Steps carry time boxes; the walkthrough harness
--     executes them against an injectable clock.
--   * gov_incidents: lifecycle open -> triaged -> mitigating ->
--     resolved -> closed, with reopen from resolved or closed.
--     gov_incident_events is the actor-stamped timeline.
--   * gov_events: append-only audit trail for every mutation in P05.
--     Application code never UPDATEs or DELETEs this table.

CREATE TABLE gov_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,           -- e.g. DB-REACHABLE
    subsystem       TEXT NOT NULL,                  -- db | queue | storage | app
    kind            TEXT NOT NULL DEFAULT 'readiness'
                    CHECK (kind IN ('liveness', 'readiness')),
    probe           TEXT NOT NULL,                  -- registry name, e.g. db_reachable
    params_json     TEXT NOT NULL DEFAULT '{}',     -- probe params (JSON)
    warn_threshold  REAL NOT NULL DEFAULT 0,       -- value <= warn -> pass
    fail_threshold  REAL NOT NULL DEFAULT 0,       -- value <= fail -> degraded, else fail
    description     TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE TABLE gov_check_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id        INTEGER NOT NULL REFERENCES gov_checks(id),
    status          TEXT NOT NULL CHECK (status IN ('pass', 'degraded', 'fail')),
    value_json      TEXT NOT NULL DEFAULT 'null',   -- measured value (JSON)
    detail_json     TEXT NOT NULL DEFAULT '{}',     -- probe detail (JSON)
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE INDEX idx_gov_check_runs_check ON gov_check_runs(check_id, id);

CREATE TABLE gov_policies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    status          TEXT NOT NULL DEFAULT 'current'
                    CHECK (status IN ('current', 'superseded')),
    max_attempts    INTEGER NOT NULL CHECK (max_attempts >= 1 AND max_attempts <= 10),
    backoff_base_s  REAL NOT NULL CHECK (backoff_base_s > 0),
    backoff_cap_s   REAL NOT NULL CHECK (backoff_cap_s >= backoff_base_s),
    jitter_max_s    REAL NOT NULL DEFAULT 0 CHECK (jitter_max_s >= 0),
    dead_letter_after INTEGER NOT NULL CHECK (dead_letter_after >= 1),
    description     TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT 'system',
    superseded_by   INTEGER,                        -- id of the version that replaced this one
    created_at      TEXT NOT NULL,                  -- UTC ISO-8601
    UNIQUE (name, version)
);

CREATE INDEX idx_gov_policies_name ON gov_policies(name, status);

CREATE TABLE gov_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    policy_id       INTEGER NOT NULL REFERENCES gov_policies(id),
    payload_json    TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'scheduled', 'retrying',
                                     'succeeded', 'dead_lettered')),
    attempts        INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_run_at     TEXT NOT NULL,                  -- UTC ISO-8601
    last_error      TEXT,
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,                  -- UTC ISO-8601
    updated_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE INDEX idx_gov_jobs_due ON gov_jobs(status, next_run_at);

CREATE TABLE gov_dead_letters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES gov_jobs(id),
    policy_id       INTEGER NOT NULL REFERENCES gov_policies(id),
    attempts        INTEGER NOT NULL,
    last_error      TEXT,
    payload_json    TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'replayed')),
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE INDEX idx_gov_dead_letters_job ON gov_dead_letters(job_id);

CREATE TABLE gov_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,           -- e.g. QUEUE-DEPTH-HIGH
    check_name      TEXT,                           -- NULL = any check
    metric          TEXT NOT NULL DEFAULT 'value',  -- detail key to compare
    operator        TEXT NOT NULL CHECK (operator IN ('gt', 'gte', 'lt', 'lte', 'eq', 'ne')),
    threshold       TEXT NOT NULL,                  -- Decimal text; compared exactly
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    owner           TEXT NOT NULL DEFAULT 'on-call',
    channel         TEXT NOT NULL DEFAULT 'log' CHECK (channel = 'log'),
    dedup_window_s  INTEGER NOT NULL DEFAULT 3600 CHECK (dedup_window_s >= 0),
    silenced_until  TEXT,                           -- UTC ISO-8601 or NULL
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE TABLE gov_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint     TEXT NOT NULL,                  -- SHA-256 of rule_id + check_id
    rule_id         INTEGER NOT NULL REFERENCES gov_rules(id),
    check_id        INTEGER REFERENCES gov_checks(id),
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'acked', 'resolved')),
    first_seen      TEXT NOT NULL,                  -- UTC ISO-8601
    last_seen       TEXT NOT NULL,                  -- UTC ISO-8601
    count           INTEGER NOT NULL DEFAULT 1 CHECK (count >= 1),
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE INDEX idx_gov_alerts_fingerprint ON gov_alerts(fingerprint, status);

CREATE TABLE gov_runbooks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    status          TEXT NOT NULL DEFAULT 'current'
                    CHECK (status IN ('current', 'superseded')),
    alert_key       TEXT NOT NULL,                  -- severity or alert type this runbook covers
    steps_json      TEXT NOT NULL,                  -- [{step, action, timebox_s}]
    created_by      TEXT NOT NULL DEFAULT 'system',
    superseded_by   INTEGER,                        -- id of the version that replaced this one
    created_at      TEXT NOT NULL,                  -- UTC ISO-8601
    UNIQUE (name, version)
);

CREATE INDEX idx_gov_runbooks_key ON gov_runbooks(alert_key, status);

CREATE TABLE gov_incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'triaged', 'mitigating', 'resolved', 'closed')),
    source_alert_id INTEGER REFERENCES gov_alerts(id),
    actor           TEXT NOT NULL DEFAULT 'system',
    resolution_note TEXT,
    created_at      TEXT NOT NULL,                  -- UTC ISO-8601
    updated_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE TABLE gov_incident_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES gov_incidents(id),
    event_type      TEXT NOT NULL,                  -- created | transition | note
    actor           TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT,
    detail_json     TEXT,
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE INDEX idx_gov_incident_events_incident ON gov_incident_events(incident_id, id);

-- Append-only audit trail: application code never UPDATEs or DELETEs
-- this table.
CREATE TABLE gov_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,                  -- check | run | policy | job | rule | alert | runbook | incident
    entity_id       INTEGER NOT NULL,
    event_type      TEXT NOT NULL,                  -- e.g. check.created, alert.fired
    actor           TEXT NOT NULL,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL                   -- UTC ISO-8601
);

CREATE INDEX idx_gov_events_entity ON gov_events(entity_type, entity_id, id);
