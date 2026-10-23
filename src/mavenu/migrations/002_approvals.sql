-- 002_approvals.sql — Project 02 foundation schema (synthetic demo data only).
--
-- Tables:
--   requests                  business records for the request & approval engine
--   request_events            append-only audit trail of everything that happens to a request
--   request_idempotency_keys  duplicate-submission protection for the request intake API

CREATE TABLE requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id           TEXT NOT NULL UNIQUE,          -- e.g. RQ-000123
    request_type        TEXT NOT NULL,                 -- purchase|travel|access|hr_change|vendor_onboarding|budget_transfer
    title               TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL DEFAULT 0,    -- monetary size; 0 for non-monetary types
    cost_center         TEXT NOT NULL,                 -- synthetic cost-center code, e.g. OPS410
    justification       TEXT NOT NULL,
    requester_name      TEXT NOT NULL,
    requester_email     TEXT NOT NULL,                 -- lowercased, synthetic fixtures only
    state               TEXT NOT NULL DEFAULT 'draft', -- request lifecycle state (see workflow.py)
    approval_chain      TEXT NOT NULL DEFAULT '[]',    -- JSON list of approver roles, in order
    current_step        INTEGER NOT NULL DEFAULT 0,    -- index into approval_chain
    sla_due_at          TEXT,                          -- ISO deadline for the pending step, NULL when none pending
    decided_by          TEXT,                          -- actor that approved/rejected, NULL until decided
    decided_at          TEXT,                          -- ISO timestamp of the decision, NULL until decided
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX idx_requests_state ON requests(state);
CREATE INDEX idx_requests_created ON requests(created_at);
CREATE INDEX idx_requests_sla ON requests(state, sla_due_at);

CREATE TABLE request_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- e.g. request.created, approval.recorded, request.escalated
    actor       TEXT NOT NULL,          -- public-form | system | reviewer:<name> | role:<role>
    role        TEXT,                   -- approver role for approval events, NULL otherwise
    from_state  TEXT,
    to_state    TEXT,
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_request_events_request ON request_events(request_id);

CREATE TABLE request_idempotency_keys (
    key             TEXT PRIMARY KEY,   -- client-supplied Idempotency-Key
    request_id      INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    response_status INTEGER NOT NULL,
    response_body   TEXT NOT NULL,      -- JSON: the exact response to replay
    created_at      TEXT NOT NULL
);
