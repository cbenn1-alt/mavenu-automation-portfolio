-- 001_core.sql — Project 01 foundation schema (synthetic demo data only).
--
-- Tables:
--   leads             business records for the revenue-operations engine
--   lead_events       append-only audit trail of everything that happens to a lead
--   idempotency_keys  duplicate-submission protection for the intake API

CREATE TABLE leads (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id             TEXT NOT NULL UNIQUE,          -- e.g. LD-000123
    name                  TEXT NOT NULL,
    phone                 TEXT,                          -- normalized digits, NULL if not given
    email                 TEXT,                          -- lowercased, NULL if not given
    service               TEXT NOT NULL,                 -- hvac|plumbing|electrical|roofing|landscaping
    zip                   TEXT NOT NULL,                 -- 5 digits, synthetic service area
    notes                 TEXT,
    urgency               TEXT NOT NULL DEFAULT 'standard',  -- standard|priority
    state                 TEXT NOT NULL DEFAULT 'received',
    classification_label  TEXT,                          -- qualified|needs_review (from classifier)
    classification_confidence REAL,
    classification_model  TEXT,                          -- which classifier produced the label
    possible_duplicate_of INTEGER REFERENCES leads(id),
    booking_ref           TEXT,                          -- external booking reference, NULL until booked
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE INDEX idx_leads_state ON leads(state);
CREATE INDEX idx_leads_created ON leads(created_at);

CREATE TABLE lead_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- e.g. lead.received, lead.state_changed
    actor       TEXT NOT NULL,          -- public-form | system | reviewer:<name>
    from_state  TEXT,
    to_state    TEXT,
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_lead_events_lead ON lead_events(lead_id);

CREATE TABLE idempotency_keys (
    key             TEXT PRIMARY KEY,   -- client-supplied Idempotency-Key
    lead_id         INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    response_status INTEGER NOT NULL,
    response_body   TEXT NOT NULL,      -- JSON: the exact response to replay
    created_at      TEXT NOT NULL
);
