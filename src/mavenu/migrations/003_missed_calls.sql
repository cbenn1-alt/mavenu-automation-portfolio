-- 003_missed_calls.sql — Project Q01 (Missed-Call Recovery Engine) schema.
--
-- All data in this project is synthetic demonstration data. Caller IDs are
-- never stored raw: only a masked display form (last 4 digits) and a
-- SHA-256 hash (for dedup + repeat-caller detection) are persisted.
--
-- Tables:
--   missed_calls           normalized missed-call events (one row per call)
--   call_events            append-only audit trail of everything per call
--   call_idempotency_keys  duplicate-submission protection for the ingest API
--   owner_notifications    escalation notification STUBS (no real messages sent)

CREATE TABLE missed_calls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id           TEXT NOT NULL UNIQUE,          -- e.g. MC-000123
    missed_at           TEXT NOT NULL,                 -- ISO-8601 call timestamp
    caller_id_masked    TEXT NOT NULL,                 -- e.g. '••••••0142'
    caller_id_hash      TEXT NOT NULL,                 -- SHA-256 of the digits
    ring_count          INTEGER,                       -- NULL when unknown
    duration_seconds    INTEGER NOT NULL DEFAULT 0,
    transcript          TEXT NOT NULL DEFAULT '',     -- voicemail text, typed/pasted
    urgency_score       REAL NOT NULL DEFAULT 0,       -- 0.0 .. 1.0, deterministic
    urgency_reasons     TEXT NOT NULL DEFAULT '[]',   -- JSON list of rule explanations
    urgency_scorer      TEXT NOT NULL DEFAULT '',     -- scorer identifier
    flags               TEXT NOT NULL DEFAULT '[]',   -- JSON list: after-hours, repeat-id-anomaly, ...
    state               TEXT NOT NULL DEFAULT 'pending'
                            CHECK (state IN ('pending','attempted','connected','booked','lost')),
    assigned_to         TEXT,                          -- claim/assign label, NULL until claimed
    escalated           INTEGER NOT NULL DEFAULT 0,   -- 1 after an SLA sweep escalation
    source              TEXT NOT NULL DEFAULT 'csv',  -- csv | webhook | demo
    dedup_key           TEXT NOT NULL UNIQUE,          -- caller_hash + missed_at
    attempted_at        TEXT,                          -- first callback attempt
    outcome_at          TEXT,                          -- booked/lost timestamp
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX idx_missed_calls_state ON missed_calls(state);
CREATE INDEX idx_missed_calls_hash ON missed_calls(caller_id_hash);
CREATE INDEX idx_missed_calls_missed ON missed_calls(missed_at);
CREATE INDEX idx_missed_calls_urgency ON missed_calls(state, urgency_score);

CREATE TABLE call_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     INTEGER NOT NULL REFERENCES missed_calls(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- e.g. call.received, call.scored, call.attempted
    actor       TEXT NOT NULL,          -- webhook | system | agent:<name> | api
    from_state  TEXT,
    to_state    TEXT,
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_call_events_call ON call_events(call_id);

CREATE TABLE call_idempotency_keys (
    key             TEXT PRIMARY KEY,   -- client-supplied Idempotency-Key
    response_status INTEGER NOT NULL,
    response_body   TEXT NOT NULL,      -- JSON: the exact response to replay
    created_at      TEXT NOT NULL
);

CREATE TABLE owner_notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     INTEGER NOT NULL REFERENCES missed_calls(id) ON DELETE CASCADE,
    message     TEXT NOT NULL,          -- stub content; nothing is ever sent
    status      TEXT NOT NULL DEFAULT 'queued-stub',
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_owner_notifications_call ON owner_notifications(call_id);
