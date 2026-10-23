-- 005_reactivation.sql — Project Q03 (Customer Reactivation Engine) schema.
--
-- All data in this project is synthetic demonstration data. Customers are
-- invented records for fictional businesses (e.g. "Acme Test Co"); the
-- outbox is NOT a messaging system — it is a queue of rendered win-back
-- touches behind a replaceable adapter interface. No real messages are
-- ever sent in v1. Attribution reports are computed over synthetic data
-- and are labeled as illustrations, never as measured campaign lift.
--
-- Tables:
--   reactivation_customers   customer records + suppression flags + segment/score
--   reactivation_jobs        synthetic job history (RFM source) + booking_source
--                            for attribution ('organic' | 'reactivation')
--   reactivation_outbox      due win-back touches rendered and queued
--                            (idempotency keys; suppression re-checked at flush)
--   reactivation_send_log    adapter send attempts (stub adapter in v1)
--   reactivation_holdouts    deterministic treated/control split per analysis run
--   reactivation_events      append-only audit trail of everything per customer

CREATE TABLE reactivation_customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id       TEXT NOT NULL UNIQUE,          -- e.g. CUS-000001
    customer_name   TEXT NOT NULL,               -- synthetic, e.g. 'Acme Test Co'
    -- Suppression flags. Any ONE of these excludes the customer from
    -- every win-back step, whatever the segment says. Honored absolutely:
    -- checked at queue-build time AND at flush time.
    do_not_contact  INTEGER NOT NULL DEFAULT 0,  -- 1 = do-not-contact list
    complaint_at    TEXT,                        -- UTC ISO-8601; NULL = no complaint
    active_job      INTEGER NOT NULL DEFAULT 0,  -- 1 = a job is currently open
    active_job_ref  TEXT,                        -- synthetic job reference, if any
    -- Scoring state (NULL until score_customers runs).
    segment         TEXT CHECK (segment IN ('active','cooling','dormant','churned')),
    dormancy_score  REAL CHECK (dormancy_score >= 0.0 AND dormancy_score <= 1.0),
    scored_at       TEXT,                        -- UTC ISO-8601 of the last scoring run
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX idx_rx_customers_segment ON reactivation_customers(segment);
CREATE INDEX idx_rx_customers_flags ON reactivation_customers(do_not_contact, active_job);

CREATE TABLE reactivation_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER NOT NULL REFERENCES reactivation_customers(id) ON DELETE CASCADE,
    job_ref         TEXT NOT NULL,               -- synthetic job label, e.g. 'JOB-0042'
    service_type    TEXT NOT NULL,               -- hvac | plumbing | electrical | roofing | landscaping
    job_date        TEXT NOT NULL,               -- UTC ISO-8601 of the completed job
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    -- Attribution provenance. 'reactivation' = booked after a reactivation
    -- touch; 'organic' = returned on their own. Synthetic by construction.
    booking_source  TEXT NOT NULL DEFAULT 'organic'
                        CHECK (booking_source IN ('organic','reactivation')),
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_rx_jobs_customer ON reactivation_jobs(customer_id);
CREATE INDEX idx_rx_jobs_date ON reactivation_jobs(job_date);

-- Outbox: rendered win-back touches waiting on the (stub) send adapter.
-- idempotency_key = 'rx:<customer_id>:seg:<segment>:step:<step_index>' ->
-- scheduler replays can never create a second row for the same step.
-- Suppression is re-checked at flush time: a row for a newly-suppressed
-- customer is marked 'suppressed' and never sent.
CREATE TABLE reactivation_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    customer_id     INTEGER NOT NULL REFERENCES reactivation_customers(id) ON DELETE CASCADE,
    segment         TEXT NOT NULL,               -- segment the plan was built for
    step_index      INTEGER NOT NULL,            -- 1-based within the segment plan
    channel         TEXT NOT NULL,               -- e.g. 'email' (rendered only, never sent)
    scheduled_for   TEXT NOT NULL,               -- when the step became due (UTC ISO-8601)
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','sent','suppressed','failed')),
    recipient_label TEXT NOT NULL,               -- synthetic label; never a real address
    subject         TEXT NOT NULL,               -- rendered
    body            TEXT NOT NULL,               -- rendered
    created_at      TEXT NOT NULL,
    sent_at         TEXT
);

CREATE INDEX idx_rx_outbox_status ON reactivation_outbox(status);
CREATE INDEX idx_rx_outbox_customer ON reactivation_outbox(customer_id);

CREATE TABLE reactivation_send_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id   INTEGER NOT NULL UNIQUE REFERENCES reactivation_outbox(id) ON DELETE CASCADE,
    adapter     TEXT NOT NULL,          -- e.g. 'stub' in v1
    status      TEXT NOT NULL,          -- e.g. 'stub-logged'
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

-- Holdout assignments for attribution analyses. Deterministic per
-- (run_name, public_id): the same customers always land in the same
-- group, which is what keeps the comparison honest and reproducible.
CREATE TABLE reactivation_holdouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_name    TEXT NOT NULL,          -- analysis run label, e.g. 'demo-holdout-1'
    customer_id INTEGER NOT NULL REFERENCES reactivation_customers(id) ON DELETE CASCADE,
    group_name  TEXT NOT NULL CHECK (group_name IN ('treated','control')),
    created_at  TEXT NOT NULL,
    UNIQUE (run_name, customer_id)
);

CREATE INDEX idx_rx_holdouts_run ON reactivation_holdouts(run_name, group_name);

CREATE TABLE reactivation_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES reactivation_customers(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- e.g. customer.scored, touch.queued, touch.suppressed
    actor       TEXT NOT NULL,          -- system | api | demo
    detail      TEXT,                   -- JSON object, may be NULL
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_rx_events_customer ON reactivation_events(customer_id);
