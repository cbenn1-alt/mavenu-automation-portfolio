-- 011_reviews.sql — Project Q08 (Review & Reputation Monitor) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every review body, author name,
-- business identity, rating, and timestamp below and in fixtures is invented
-- for demonstration. No real business identities, no real platform data, no
-- scraping of real review platforms anywhere in this project. Reviews are
-- fabricated by design (the demo feed), and response drafts are never
-- posted automatically — there is no send path in v1 by architecture.
--
-- Design notes:
--   * review_lexicons: versioned tagger lexicons. The tagger reads lexicon
--     terms from this table (inspectable, versioned); a new lexicon version
--     is inserted, never edited in place.
--   * reviews: one row per normalized review event. UNIQUE(source,
--     external_id) is the natural idempotency key — re-ingesting the same
--     feed row is a no-op, never a duplicate.
--   * review_tags: tagger output (sentiment label + topic labels) with
--     confidence, lexicon version, and an explanation of matched terms.
--   * review_queues: triage routing output. One row per review (worst queue
--     wins): 'owner_alert' for negative/critical reviews, 'human_review'
--     for uncertain/adversarial ones (default-to-alert on uncertainty).
--     severity in {critical, high, normal}; sla_due_at is UTC.
--   * review_drafts: response drafts from templates. status is ONLY
--     'draft' | 'approved' | 'rejected' — there is no 'sent' state and no
--     send/post path anywhere in the codebase. Approval is a human gate.
--   * review_escalations: append-only log of SLA breaches.
--   * review_events: append-only, actor-stamped audit trail.

CREATE TABLE review_lexicons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    version         TEXT NOT NULL,             -- e.g. '1.0'
    category        TEXT NOT NULL,             -- 'sentiment_positive' |
                                               -- 'sentiment_negative' |
                                               -- 'topic_service' |
                                               -- 'topic_price' |
                                               -- 'topic_punctuality' |
                                               -- 'topic_workmanship'
    term            TEXT NOT NULL,             -- lowercase word/phrase
    note            TEXT,
    UNIQUE (version, category, term)
);

CREATE TABLE reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,             -- e.g. 'demo_csv', 'api'
    external_id     TEXT NOT NULL,             -- natural key within source
    stars           INTEGER CHECK (stars IS NULL OR (stars BETWEEN 1 AND 5)),
    title           TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL,
    reviewed_at     TEXT NOT NULL,             -- ISO-8601 UTC
    author_mask     TEXT NOT NULL DEFAULT '',  -- masked display name
    ingested_at     TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE TABLE review_tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER NOT NULL REFERENCES reviews(id),
    kind            TEXT NOT NULL CHECK (kind IN ('sentiment', 'topic')),
    label           TEXT NOT NULL,
    confidence      REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    lexicon_version TEXT NOT NULL,
    detail          TEXT,                      -- JSON: matched terms etc.
    created_at      TEXT NOT NULL,
    UNIQUE (review_id, kind, label)
);

CREATE TABLE review_queues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER NOT NULL REFERENCES reviews(id),
    queue           TEXT NOT NULL CHECK (queue IN ('owner_alert', 'human_review')),
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'normal')),
    sla_due_at      TEXT NOT NULL,             -- ISO-8601 UTC
    sla_hours       INTEGER NOT NULL CHECK (sla_hours > 0),
    status          TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'breached', 'resolved')),
    claimed_by      TEXT,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT,
    UNIQUE (review_id)                         -- one queue entry per review
);

CREATE TABLE review_drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER NOT NULL REFERENCES reviews(id),
    template_name   TEXT NOT NULL,
    tone            TEXT NOT NULL,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'approved', 'rejected')),
    created_by      TEXT NOT NULL DEFAULT 'system',
    approved_by     TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT
);

CREATE TABLE review_escalations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER NOT NULL REFERENCES review_queues(id),
    triggered_at    TEXT NOT NULL,
    reason          TEXT NOT NULL
);

CREATE TABLE review_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER REFERENCES reviews(id),
    event_type      TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT,                      -- JSON detail
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_review_queues_status ON review_queues(status);
CREATE INDEX idx_review_queues_queue_status ON review_queues(queue, status);
CREATE INDEX idx_review_tags_review ON review_tags(review_id);
CREATE INDEX idx_review_drafts_status ON review_drafts(status);
CREATE INDEX idx_review_events_review ON review_events(review_id);
CREATE INDEX idx_review_lexicons_version ON review_lexicons(version, category);
