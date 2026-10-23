-- 004_estimates.sql — Project Q02 (Estimate Follow-Up Automation) schema.
--
-- All data in this project is synthetic demonstration data. Estimates are
-- invented records for fictional customers (e.g. "Acme Test Co"); the
-- outbox is NOT a mail server — it is a queue of rendered messages behind
-- a replaceable adapter interface. No real messages are ever sent in v1.
--
-- Tables:
--   estimates                estimate records + lifecycle state machine
--   estimate_events          append-only audit trail of everything per estimate
--   cadence_rules            configurable follow-up steps (day N after sent)
--   message_templates        versioned message templates; history preserved
--   estimate_outbox          due follow-ups rendered and queued (idempotency keys)
--   send_log                 adapter send attempts (stub adapter in v1)
--   estimate_idempotency_keys  duplicate-submission protection for the create API

CREATE TABLE estimates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id           TEXT NOT NULL UNIQUE,          -- e.g. EST-000123
    customer_name       TEXT NOT NULL,               -- synthetic, e.g. 'Acme Test Co'
    service_type        TEXT NOT NULL,               -- hvac | plumbing | electrical | roofing | landscaping
    estimator           TEXT NOT NULL,               -- estimator/agent label (synthetic)
    amount_cents        INTEGER NOT NULL CHECK (amount_cents > 0),
    state               TEXT NOT NULL DEFAULT 'draft'
                            CHECK (state IN ('draft','sent','viewed','followed_up',
                                             'accepted','declined','expired')),
    decline_reason      TEXT,                        -- required when state = 'declined'
    decline_note        TEXT,                        -- optional free text
    unsubscribed        INTEGER NOT NULL DEFAULT 0,  -- 1 = opted out; stop rule
    sent_at             TEXT,                        -- first sent timestamp (UTC ISO-8601)
    viewed_at           TEXT,                        -- last viewed timestamp
    followup_count      INTEGER NOT NULL DEFAULT 0,  -- follow-ups queued so far
    last_followup_at    TEXT,
    accepted_at         TEXT,
    declined_at         TEXT,
    expired_at          TEXT,
    notes               TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX idx_estimates_state ON estimates(state);
CREATE INDEX idx_estimates_service ON estimates(service_type);
CREATE INDEX idx_estimates_estimator ON estimates(estimator);
CREATE INDEX idx_estimates_sent ON estimates(sent_at);

CREATE TABLE estimate_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    estimate_id INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- e.g. estimate.created, estimate.sent, estimate.followup_queued
    actor       TEXT NOT NULL,          -- web-form | system | agent:<name> | api
    from_state  TEXT,
    to_state    TEXT,
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_estimate_events_estimate ON estimate_events(estimate_id);

CREATE TABLE cadence_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    step_index      INTEGER NOT NULL,               -- 1-based ordering of follow-up steps
    days_after_sent REAL NOT NULL CHECK (days_after_sent >= 0),
    template_name   TEXT NOT NULL,                  -- references message_templates.name (active version)
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_cadence_rules_active ON cadence_rules(is_active, step_index);

CREATE TABLE message_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,          -- e.g. followup_step1; history rows share the name
    version     INTEGER NOT NULL,       -- 1-based; only the latest row per name is active
    subject     TEXT NOT NULL,          -- may contain {{variables}}
    body        TEXT NOT NULL,          -- may contain {{variables}}
    variables   TEXT NOT NULL DEFAULT '[]',  -- JSON list of required variable names
    is_active   INTEGER NOT NULL DEFAULT 1,  -- 1 only on the newest version
    created_at  TEXT NOT NULL,
    UNIQUE (name, version)
);

CREATE INDEX idx_message_templates_name ON message_templates(name, is_active);

-- Outbox: rendered follow-up messages waiting on the (stub) send adapter.
-- idempotency_key = 'est:<estimate_id>:step:<step_index>' -> scheduler
-- replays can never create a second row for the same step.
CREATE TABLE estimate_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    estimate_id     INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
    template_name   TEXT NOT NULL,
    template_version INTEGER NOT NULL,
    step_index      INTEGER NOT NULL,
    scheduled_for   TEXT NOT NULL,      -- when the step became due (UTC ISO-8601)
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','sent','failed')),
    recipient_label TEXT NOT NULL,      -- synthetic label; never a real address
    subject         TEXT NOT NULL,      -- rendered
    body            TEXT NOT NULL,      -- rendered
    created_at      TEXT NOT NULL,
    sent_at         TEXT
);

CREATE INDEX idx_outbox_status ON estimate_outbox(status);
CREATE INDEX idx_outbox_estimate ON estimate_outbox(estimate_id);

CREATE TABLE send_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id   INTEGER NOT NULL UNIQUE REFERENCES estimate_outbox(id) ON DELETE CASCADE,
    adapter     TEXT NOT NULL,          -- e.g. 'stub' in v1
    status      TEXT NOT NULL,          -- e.g. 'stub-logged'
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

CREATE TABLE estimate_idempotency_keys (
    key             TEXT PRIMARY KEY,   -- client-supplied Idempotency-Key
    response_status INTEGER NOT NULL,
    response_body   TEXT NOT NULL,      -- JSON: the exact response to replay
    created_at      TEXT NOT NULL
);

-- Seed defaults: the demo cadence (day 2 / 7 / 14) and its three templates.
-- Seeded rows carry created_at from SQLite's clock; service-layer tests that
-- need exact timestamps build their own rules/templates instead.
INSERT INTO message_templates (name, version, subject, body, variables, is_active, created_at)
VALUES
('followup_step1', 1,
 'Following up on your estimate ({{estimate_id}})',
 'Hi {{customer_name}},\n\nJust checking in on the {{service_type}} estimate {{estimate_id}} ({{amount}}) we sent over.\n\nHappy to answer any questions or adjust the scope.\n\n— {{estimator}} (demo message; nothing was sent)',
 '["estimate_id","customer_name","service_type","amount","estimator"]', 1,
 datetime('now')),
('followup_step2', 1,
 'Still interested? Your estimate {{estimate_id}}',
 'Hi {{customer_name}},\n\nWanted to make sure you saw estimate {{estimate_id}} for {{service_type}} — {{amount}}.\n\nIf the timing or scope needs to change, tell us and we will rework it.\n\n— {{estimator}} (demo message; nothing was sent)',
 '["estimate_id","customer_name","service_type","amount","estimator"]', 1,
 datetime('now')),
('followup_step3', 1,
 'Last check-in on estimate {{estimate_id}}',
 'Hi {{customer_name}},\n\nThis is our last scheduled check-in on estimate {{estimate_id}} ({{service_type}}, {{amount}}).\n\nIf you would rather we stop following up, reply "stop".\n\n— {{estimator}} (demo message; nothing was sent)',
 '["estimate_id","customer_name","service_type","amount","estimator"]', 1,
 datetime('now'));

INSERT INTO cadence_rules (step_index, days_after_sent, template_name, is_active, created_at)
VALUES
(1, 2,  'followup_step1', 1, datetime('now')),
(2, 7,  'followup_step2', 1, datetime('now')),
(3, 14, 'followup_step3', 1, datetime('now'));
