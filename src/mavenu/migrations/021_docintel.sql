-- 021_docintel.sql — Project P03 (AI Document Intelligence & Exception
-- Management) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Document texts, vendor and
-- customer names, amounts, and dates are invented fixtures. This is not
-- a document-processing service for real business records, not OCR, and
-- not a substitute for real document controls. Extraction is a
-- deterministic rule-based engine (see extraction.py) — not a trained
-- model and never described as one.
--
-- Money is stored as INTEGER cents and computed with Python Decimal at
-- the service layer (never float) for exactness.
--
-- Design notes:
--   * docintel_documents: one row per ingested document; `doc_id` is the
--     natural idempotency key — re-ingesting the same document never
--     duplicates it. `state` is enforced in code (workflow.DOC_WORKFLOW):
--     ingested -> needs_review | accepted | rejected. A document reaches
--     `accepted` only when every spec field is accepted — extraction
--     proposes, a human disposes.
--   * docintel_fields: one row per spec field per document, including
--     fields the extractor could not find (status 'missing'). Each
--     extracted field carries its confidence (Decimal text), the rule
--     that extracted it, the 1-based source line, and the raw matched
--     text — field-level provenance, the thesis of this project.
--     status: proposed (extracted below the accept threshold) |
--     accepted (at/above threshold, or human-accepted/corrected) |
--     rejected (human-rejected) | missing (not extracted).
--   * docintel_exceptions: the exception queue. Human states are
--     open -> investigating -> resolved | written_off (enforced in code;
--     see workflow.EXCEPTION_WORKFLOW — shared with Q05). The partial
--     unique index keeps exactly one OPEN exception per (kind, doc,
--     field) so re-extraction is idempotent: a re-run clears
--     auto-generated OPEN rows and rebuilds them; rows a human has
--     touched (investigating/resolved/written_off) are never rebuilt.
--   * docintel_exception_events: append-only state-transition audit
--     trail, actor-stamped.
--   * docintel_field_events: append-only field-review audit trail
--     (accept / correct / reject, actor-stamped, with the corrected
--     value when one was supplied).
--   * docintel_doc_events: append-only document state-transition audit
--     trail, actor-stamped.
--   * docintel_runs: append-only record of each ingest/extract run with
--     its counts, so runs are reproducible and explainable.

CREATE TABLE docintel_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT NOT NULL UNIQUE,       -- natural idempotency key
    doc_type        TEXT NOT NULL CHECK (doc_type IN ('invoice', 'receipt', 'contract')),
    source_format   TEXT NOT NULL CHECK (source_format IN ('json', 'csv', 'text')),
    source_text     TEXT NOT NULL,              -- document text as ingested
    state           TEXT NOT NULL DEFAULT 'ingested' CHECK (state IN (
                        'ingested', 'needs_review', 'accepted', 'rejected'
                    )),
    doc_confidence  TEXT,                       -- Decimal 0.00..1.00 as text
                                                -- (min field confidence; NULL
                                                -- when nothing was extracted)
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    updated_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_docintel_documents_state ON docintel_documents(state);
CREATE INDEX idx_docintel_documents_type ON docintel_documents(doc_type);

CREATE TABLE docintel_fields (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES docintel_documents(id),
    field_name      TEXT NOT NULL,
    value_text      TEXT,                       -- canonical value (money as
                                                -- "1250.00", dates as ISO)
    value_cents     INTEGER,                    -- money fields only; NULL otherwise
    confidence      TEXT,                       -- Decimal 0.00..1.00 as text; NULL
                                                -- when the field was not extracted
    rule_id         TEXT,                       -- extraction rule that fired; NULL
                                                -- when the field was not extracted
    source_line     INTEGER,                    -- 1-based line in source_text
    raw_matched_text TEXT,                      -- exact text the rule matched
    status          TEXT NOT NULL DEFAULT 'missing' CHECK (status IN (
                        'proposed', 'accepted', 'rejected', 'missing'
                    )),
    corrected       INTEGER NOT NULL DEFAULT 0 CHECK (corrected IN (0, 1)),
    corrected_value_text TEXT,                  -- human-supplied value, if any
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    updated_at      TEXT NOT NULL,              -- UTC ISO-8601
    UNIQUE (document_id, field_name)
);

CREATE INDEX idx_docintel_fields_doc ON docintel_fields(document_id);
CREATE INDEX idx_docintel_fields_status ON docintel_fields(status);

CREATE TABLE docintel_exceptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN (
                        'low_confidence', 'missing_field', 'validation_failed',
                        'duplicate_document', 'unparseable_document'
                    )),
    ref_type        TEXT NOT NULL CHECK (ref_type IN ('document')),
    ref_id          INTEGER NOT NULL,           -- row id in docintel_documents
    ref_public_id   TEXT NOT NULL,              -- doc_id
    field_name      TEXT,                       -- field the exception is about
                                                -- (NULL for document-level kinds)
    detail_json     TEXT NOT NULL,              -- structured facts
    suggested_action TEXT NOT NULL,             -- the system's proposal (never posts)
    state           TEXT NOT NULL DEFAULT 'open' CHECK (state IN (
                        'open', 'investigating', 'resolved', 'written_off'
                    )),
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    updated_at      TEXT NOT NULL               -- UTC ISO-8601
);

-- Exactly one OPEN exception per (kind, doc, field): re-extraction
-- rebuilds the OPEN queue without duplicating it. (NULL field_name rows
-- are deduped in code, since SQLite treats NULLs as distinct.)
CREATE UNIQUE INDEX uq_docintel_exceptions_open
    ON docintel_exceptions (kind, ref_type, ref_public_id, field_name)
    WHERE state = 'open';

CREATE INDEX idx_docintel_exceptions_state ON docintel_exceptions(state);
CREATE INDEX idx_docintel_exceptions_kind ON docintel_exceptions(kind);

-- Append-only transition audit trail: every state change is actor-stamped.
-- ON DELETE CASCADE: re-extraction rebuilds auto-generated OPEN exceptions
-- (which carry exactly one history row — their creation), so their audit
-- rows are rebuilt with them. Rows a human has touched are never deleted.
CREATE TABLE docintel_exception_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_id    INTEGER NOT NULL REFERENCES docintel_exceptions(id) ON DELETE CASCADE,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_docintel_exception_events_exc ON docintel_exception_events(exception_id, id);

-- Append-only field-review audit trail: every accept / correct / reject.
CREATE TABLE docintel_field_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id        INTEGER NOT NULL REFERENCES docintel_fields(id),
    document_id     INTEGER NOT NULL REFERENCES docintel_documents(id),
    field_name      TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('accept', 'correct', 'reject')),
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_docintel_field_events_field ON docintel_field_events(field_id, id);

-- Append-only document state-transition audit trail.
CREATE TABLE docintel_doc_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES docintel_documents(id),
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_docintel_doc_events_doc ON docintel_doc_events(document_id, id);

-- Append-only run log: every ingest and extract run with its counts.
CREATE TABLE docintel_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('ingest_json', 'ingest_csv', 'ingest_text', 'extract')),
    stats_json      TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.
