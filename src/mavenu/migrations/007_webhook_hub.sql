-- 007_webhook_hub.sql — Project Q10 (Webhook Integration Hub) schema.
--
-- All data in this project is synthetic demonstration data. Webhook
-- payloads are invented events; stub endpoints are in-process callables
-- (never real HTTP, never real SaaS). HMAC verification uses documented
-- TEST-ONLY secrets (see src/mavenu/webhooks.py); a real deployment must
-- supply per-source secrets via the environment or a secret manager.
--
-- Privacy: full payloads are NEVER written to stdout logs or API
-- responses. Logs and API responses carry redacted summaries (key names
-- and value types only). The append-only event store holds the envelope
-- as received (synthetic in v1); SECURITY.md documents the field
-- allowlist required before any real deployment.
--
-- Design notes:
--   * webhook_events is APPEND-ONLY: rows are inserted, never updated.
--     Current per-event status is DERIVED from webhook_lineage (latest
--     to_state per event_id). That is the whole point of the lineage log:
--     "received → routed → queued → delivered | dead_lettered | rejected".
--   * webhook_lineage is append-only: one row per state transition,
--     actor-stamped. No transition is ever deleted or rewritten.
--   * webhook_attempts is append-only: every delivery attempt is logged,
--     success or failure, with a per-attempt row.
--   * webhook_deliveries is the mutable retry queue (queued → delivered |
--     dead_lettered); attempts/next_attempt_at drive exponential backoff.
--   * webhook_endpoint_state holds per-endpoint circuit-breaker state
--     (closed → open → half_open → closed).

CREATE TABLE webhook_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id       TEXT NOT NULL UNIQUE,          -- e.g. EVT-000001
    event_id        TEXT NOT NULL UNIQUE,         -- sender idempotency key
    source          TEXT NOT NULL,                -- e.g. 'demo-form'
    event_type      TEXT NOT NULL,                -- e.g. 'lead.created'
    envelope_json   TEXT NOT NULL,                -- canonical envelope (synthetic)
    signature_ok    INTEGER NOT NULL DEFAULT 0 CHECK (signature_ok IN (0,1)),
    created_at      TEXT NOT NULL                 -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_webhook_events_type   ON webhook_events(event_type);
CREATE INDEX idx_webhook_events_source ON webhook_events(source);

CREATE TABLE webhook_lineage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,                -- logical ref to webhook_events.event_id
    from_state      TEXT,                         -- NULL for the first transition
    to_state        TEXT NOT NULL,                -- received|rejected|routed|queued|
                                                  -- delivered|dead_lettered|replayed
    actor           TEXT NOT NULL DEFAULT 'hub',
    detail_json     TEXT,                         -- small, redacted context only
    created_at      TEXT NOT NULL                 -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_webhook_lineage_event ON webhook_lineage(event_id, id);

-- Versioned routing rules: event type (+ conditions) → action list.
-- Updating a rule bumps `version`; deliveries record the rule version
-- that created them so history stays explainable.
CREATE TABLE webhook_routes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    version         INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    event_type      TEXT NOT NULL DEFAULT '*',   -- '*' matches every type
    conditions_json TEXT NOT NULL DEFAULT '[]',  -- [{field, op, value}]
    actions_json    TEXT NOT NULL DEFAULT '[]',  -- [{type, ...params}]
    priority        INTEGER NOT NULL DEFAULT 100,-- lower runs first
    enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at      TEXT NOT NULL,               -- UTC ISO-8601
    updated_at      TEXT NOT NULL                -- UTC ISO-8601
);

-- Terminal projections of transform actions. A transform never re-enters
-- routing (documented loop guard); the derived envelope is stored here
-- with the rule + version that produced it.
CREATE TABLE webhook_derived (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,
    rule_id         INTEGER NOT NULL REFERENCES webhook_routes(id),
    rule_version    INTEGER NOT NULL,
    derived_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL                -- UTC ISO-8601
);

CREATE INDEX idx_webhook_derived_event ON webhook_derived(event_id);

-- Mutable retry queue. One row per (event, endpoint); INSERT OR IGNORE
-- makes forwarding idempotent on the event idempotency key.
CREATE TABLE webhook_deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,                -- logical ref to webhook_events.event_id
    endpoint        TEXT NOT NULL,                -- stub endpoint name, e.g. 'stub:crm-sink'
    rule_id         INTEGER,                     -- rule that created this delivery
    rule_version    INTEGER,
    state           TEXT NOT NULL DEFAULT 'queued'
                        CHECK (state IN ('queued','delivered','dead_lettered')),
    attempts        INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts    INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
    next_attempt_at TEXT NOT NULL,               -- UTC ISO-8601; due when <= now
    last_error      TEXT,                        -- last failure summary (no secrets)
    created_at      TEXT NOT NULL,               -- UTC ISO-8601
    updated_at      TEXT NOT NULL,               -- UTC ISO-8601
    UNIQUE (event_id, endpoint)
);

CREATE INDEX idx_webhook_deliveries_due ON webhook_deliveries(state, next_attempt_at);
CREATE INDEX idx_webhook_deliveries_event ON webhook_deliveries(event_id);

-- Append-only attempt log: every delivery attempt, success or failure.
CREATE TABLE webhook_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id     INTEGER NOT NULL REFERENCES webhook_deliveries(id) ON DELETE CASCADE,
    attempt_no      INTEGER NOT NULL CHECK (attempt_no >= 1),
    endpoint        TEXT NOT NULL,
    ok              INTEGER NOT NULL CHECK (ok IN (0,1)),
    detail          TEXT NOT NULL DEFAULT '',    -- short summary, never secrets
    created_at      TEXT NOT NULL                 -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_webhook_attempts_delivery ON webhook_attempts(delivery_id);

-- Dead-letter store: poison events, routing failures, exhausted retries.
-- `delivery_id` is set for exhausted-retry dead letters, NULL for
-- ingest/routing-level ones. `replayed` marks a dead letter that was
-- re-queued for another attempt.
CREATE TABLE webhook_dead_letters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,
    delivery_id     INTEGER REFERENCES webhook_deliveries(id),
    source          TEXT NOT NULL DEFAULT '',
    event_type      TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL
                        CHECK (reason IN (
                            'malformed_envelope','routing_error',
                            'max_attempts_exceeded','unknown_endpoint'
                        )),
    detail_json     TEXT,                        -- redacted summary, never full payload
    replayed        INTEGER NOT NULL DEFAULT 0 CHECK (replayed IN (0,1)),
    created_at      TEXT NOT NULL                -- UTC ISO-8601
);

CREATE INDEX idx_webhook_dead_letters_event ON webhook_dead_letters(event_id);

-- Circuit-breaker state, one row per endpoint.
CREATE TABLE webhook_endpoint_state (
    endpoint              TEXT PRIMARY KEY,
    state                 TEXT NOT NULL DEFAULT 'closed'
                              CHECK (state IN ('closed','open','half_open')),
    consecutive_failures  INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    opened_at             TEXT,                   -- UTC ISO-8601
    half_open_after       TEXT,                   -- UTC ISO-8601; probe allowed when <= now
    last_failure_at       TEXT,                   -- UTC ISO-8601
    updated_at            TEXT NOT NULL           -- UTC ISO-8601
);
