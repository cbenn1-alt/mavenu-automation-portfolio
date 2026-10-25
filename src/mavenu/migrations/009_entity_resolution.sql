-- 009_entity_resolution.sql — Project Q06 (Data Quality & Entity Resolution
-- Service) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Names, phone numbers, emails,
-- and addresses are fictional fixtures for demonstration. No real personal
-- data exists anywhere in this project.
--
-- Design notes:
--   * er_sources: one row per ingested CSV source (spreadsheet, form tool,
--     phone export). `label` is the natural idempotency key — re-ingesting
--     the same CSV under the same label never duplicates rows.
--   * er_contacts: one row per ingested contact. Raw columns keep the
--     source's original text; *_norm / name_key / phone_digits columns hold
--     the deterministic normalized forms (see normalize.py). Normalized
--     columns are recomputed by the normalize stage and are always a pure
--     function of the raw columns — the service layer re-derives them, it
--     never trusts stale values.
--   * er_blocks: blocking index. One row per (block_key, contact). Blocks
--     are cheap equality keys (phone digits, lowercased email,
--     zip+surname) so candidate pairs are generated from co-occurrence
--     instead of an O(n^2) all-pairs scan. Rebuilt from active contacts on
--     every resolve run.
--   * er_pairs: candidate pairs, generated ONLY from shared blocks
--     (UNIQUE on (a, b) with a < b). `score`/`band`/`score_detail_json`
--     are filled by the scoring stage. A pair row is the durable record
--     that merge proposals reference.
--   * er_merge_proposals: the human-in-the-loop gate. A resolve run only
--     ever creates proposals in state 'proposed' — there is NO code path
--     that auto-confirms. 'confirmed' is reachable only through
--     confirm_merge(), which requires a non-blank, non-"system" actor.
--     'reversed' is reachable only through reverse_merge().
--   * er_merge_audit: one row per confirmed merge. Carries the FULL
--     pre-merge row images of winner and loser plus per-field provenance,
--     so any merge is exactly reversible. Pre-image columns are immutable
--     once written; only reversed_at/reversed_by are set later, once.
--   * er_events: append-only, actor-stamped audit trail for every
--     consequential action (ingest, resolve, propose, confirm, reject,
--     reverse).
--   * er_runs: append-only record of each ingest/resolve run with counts.

CREATE TABLE er_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL UNIQUE,       -- natural idempotency key
    source_kind     TEXT NOT NULL CHECK (source_kind IN (
                        'spreadsheet', 'form', 'phone', 'other'
                    )),
    ingested_at     TEXT NOT NULL               -- UTC ISO-8601
);

CREATE TABLE er_contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES er_sources(id),
    source_row      INTEGER NOT NULL,           -- 1-based data row in the source CSV
    -- raw (source's original text, formula-sanitized)
    raw_name        TEXT NOT NULL,
    raw_phone       TEXT NOT NULL DEFAULT '',
    raw_email       TEXT NOT NULL DEFAULT '',
    raw_address     TEXT NOT NULL DEFAULT '',
    raw_zip         TEXT NOT NULL DEFAULT '',
    raw_notes       TEXT NOT NULL DEFAULT '',
    -- normalized (deterministic; recomputed by the normalize stage)
    name_norm       TEXT NOT NULL DEFAULT '',
    name_key        TEXT NOT NULL DEFAULT '',
    phone_digits    TEXT NOT NULL DEFAULT '',
    email_norm      TEXT NOT NULL DEFAULT '',
    address_norm    TEXT NOT NULL DEFAULT '',
    zip_norm        TEXT NOT NULL DEFAULT '',
    -- merge bookkeeping
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged')),
    merged_into     INTEGER REFERENCES er_contacts(id),
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    UNIQUE (source_id, source_row)              -- idempotent re-ingest
);

CREATE INDEX idx_er_contacts_source ON er_contacts(source_id);
CREATE INDEX idx_er_contacts_status ON er_contacts(status);
CREATE INDEX idx_er_contacts_phone ON er_contacts(phone_digits);
CREATE INDEX idx_er_contacts_email ON er_contacts(email_norm);

-- Blocking index: rebuilt from active contacts on every resolve run.
CREATE TABLE er_blocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    block_key       TEXT NOT NULL,              -- e.g. 'phone:7015550142'
    contact_id      INTEGER NOT NULL REFERENCES er_contacts(id),
    UNIQUE (block_key, contact_id)
);

CREATE INDEX idx_er_blocks_key ON er_blocks(block_key);

-- Candidate pairs: generated ONLY from shared blocks (never all-pairs).
CREATE TABLE er_pairs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_a_id    INTEGER NOT NULL REFERENCES er_contacts(id),
    contact_b_id    INTEGER NOT NULL REFERENCES er_contacts(id),
    block_key       TEXT NOT NULL,              -- the block that paired them
    score           TEXT,                       -- Decimal 0.00..1.00 as text, NULL until scored
    band            TEXT CHECK (band IN ('match', 'review', 'no_match')),
    score_detail_json TEXT,                     -- component breakdown + reasons
    scored_at       TEXT,                       -- UTC ISO-8601
    CHECK (contact_a_id < contact_b_id),
    UNIQUE (contact_a_id, contact_b_id)
);

CREATE INDEX idx_er_pairs_band ON er_pairs(band);
CREATE INDEX idx_er_pairs_contacts ON er_pairs(contact_a_id, contact_b_id);

-- Merge proposals: the human gate. 'proposed' only from the service;
-- 'confirmed'/'rejected' only via explicit human action; 'reversed' only
-- via reverse_merge().
CREATE TABLE er_merge_proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id         INTEGER NOT NULL UNIQUE REFERENCES er_pairs(id),
    winner_id       INTEGER NOT NULL REFERENCES er_contacts(id),
    loser_id        INTEGER NOT NULL REFERENCES er_contacts(id),
    state           TEXT NOT NULL DEFAULT 'proposed' CHECK (state IN (
                        'proposed', 'confirmed', 'rejected', 'reversed'
                    )),
    proposed_by     TEXT NOT NULL DEFAULT 'system',
    proposed_at     TEXT NOT NULL,              -- UTC ISO-8601
    decided_by      TEXT,
    decided_at      TEXT,                       -- UTC ISO-8601
    field_plan_json TEXT NOT NULL,              -- per-field winning value + provenance
    decision_note   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_er_merges_state ON er_merge_proposals(state);

-- Merge audit: full pre-images make every merge exactly reversible.
CREATE TABLE er_merge_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     INTEGER NOT NULL REFERENCES er_merge_proposals(id),
    winner_id       INTEGER NOT NULL,
    loser_id        INTEGER NOT NULL,
    winner_pre_image_json TEXT NOT NULL,        -- winner row BEFORE the merge
    loser_pre_image_json  TEXT NOT NULL,       -- loser row BEFORE the merge
    field_provenance_json TEXT NOT NULL,       -- per-field {field, value, from_contact_id, reason}
    merged_by       TEXT NOT NULL,
    merged_at       TEXT NOT NULL,              -- UTC ISO-8601
    reversed_at     TEXT,                       -- set once by reverse_merge()
    reversed_by     TEXT
);
-- Pre-image columns are append-only: application code never UPDATEs them.

CREATE INDEX idx_er_merge_audit_proposal ON er_merge_audit(proposal_id);

-- Append-only audit trail for every consequential action.
CREATE TABLE er_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,              -- 'source' | 'contact' | 'pair' | 'proposal' | 'merge'
    entity_id       INTEGER NOT NULL,
    event_type      TEXT NOT NULL,              -- e.g. 'contact.ingested', 'merge.confirmed'
    actor           TEXT NOT NULL,
    from_state      TEXT,
    to_state        TEXT,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_er_events_entity ON er_events(entity_type, entity_id, id);

-- Append-only run log: every ingest and resolve run with its counts.
CREATE TABLE er_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('ingest', 'resolve')),
    stats_json      TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.
