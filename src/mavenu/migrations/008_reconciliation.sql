-- 008_reconciliation.sql — Project Q05 (Invoice Reconciliation & Exception
-- Reporter) schema.
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Amounts are invented and are
-- NOT real financial data; customer/vendor names are fictional stand-ins
-- (e.g. "Acme Test Co"). This is not accounting software, not an audit
-- tool, and not a substitute for real accounting controls. Write-off
-- actions always require a human actor; the system only proposes.
--
-- Money is stored as INTEGER cents and computed with Python Decimal at
-- the service layer (never float) for exactness.
--
-- Design notes:
--   * recon_invoices: one row per invoice; `invoice_id` is the natural
--     idempotency key — re-ingesting the same CSV never duplicates rows.
--   * recon_payments: one row per payment; `payment_id` is the natural
--     idempotency key. Within-batch repeats raise a duplicate_payment
--     exception instead of inserting a second row.
--   * recon_matches: one row per (invoice, payment) pairing. Every match
--     carries its kind (exact | fuzzy), its score, and an explanation
--     (JSON list of {rule, detail}) — explainability is the thesis of
--     this project: reconciliation you can audit.
--   * recon_exceptions: the exception queue. Human states are
--     open -> investigating -> resolved | written_off (enforced in code;
--     see workflow.EXCEPTION_WORKFLOW). The partial unique index keeps
--     exactly one OPEN exception per (kind, ref) so match re-runs are
--     idempotent: a re-run clears auto-generated OPEN rows and rebuilds
--     them from current match state; rows a human has touched
--     (investigating/resolved/written_off) are never rebuilt.
--   * recon_exception_events: append-only state-transition audit trail,
--     actor-stamped.
--   * recon_runs: append-only record of each ingest/match run with its
--     counts, so runs are reproducible and explainable.

CREATE TABLE recon_invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      TEXT NOT NULL UNIQUE,       -- natural idempotency key
    customer        TEXT NOT NULL,              -- synthetic name, CSV-sanitized
    amount_cents    INTEGER NOT NULL CHECK (amount_cents >= 0),
    issued_date     TEXT NOT NULL,              -- ISO-8601 date (YYYY-MM-DD)
    due_date        TEXT NOT NULL,              -- ISO-8601 date (YYYY-MM-DD)
    source_row      INTEGER NOT NULL,           -- CSV line number (1-based data row)
    ingest_batch    TEXT NOT NULL,              -- batch label, e.g. 'csv:2026-10-23T...'
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_recon_invoices_due ON recon_invoices(due_date);

CREATE TABLE recon_payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id      TEXT NOT NULL UNIQUE,       -- natural idempotency key
    invoice_ref     TEXT,                       -- optional invoice reference
    customer        TEXT NOT NULL,              -- synthetic name, CSV-sanitized
    amount_cents    INTEGER NOT NULL CHECK (amount_cents >= 0),
    paid_date       TEXT NOT NULL,              -- ISO-8601 date (YYYY-MM-DD)
    note            TEXT NOT NULL DEFAULT '',  -- CSV-sanitized
    source_row      INTEGER NOT NULL,
    ingest_batch    TEXT NOT NULL,
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);

CREATE INDEX idx_recon_payments_ref ON recon_payments(invoice_ref);
CREATE INDEX idx_recon_payments_date ON recon_payments(paid_date);

CREATE TABLE recon_matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_row_id  INTEGER NOT NULL REFERENCES recon_invoices(id),
    payment_row_id  INTEGER NOT NULL REFERENCES recon_payments(id),
    match_kind      TEXT NOT NULL CHECK (match_kind IN ('exact', 'fuzzy')),
    score           TEXT NOT NULL,              -- Decimal 0.00..1.00 as text (1.00 for exact)
    explanation_json TEXT NOT NULL,            -- [{rule, detail}] — why this matched
    matched_by      TEXT NOT NULL,             -- 'exact-pass' | 'fuzzy-pass'
    matched_at      TEXT NOT NULL,             -- UTC ISO-8601
    UNIQUE (invoice_row_id, payment_row_id)
);

CREATE INDEX idx_recon_matches_invoice ON recon_matches(invoice_row_id);
CREATE INDEX idx_recon_matches_payment ON recon_matches(payment_row_id);

CREATE TABLE recon_exceptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN (
                        'unmatched_invoice', 'unmatched_payment',
                        'partial_payment', 'overpaid_invoice',
                        'duplicate_payment', 'review_candidate'
                    )),
    ref_type        TEXT NOT NULL CHECK (ref_type IN ('invoice', 'payment')),
    ref_id          INTEGER NOT NULL,           -- row id in recon_invoices/payments
    ref_public_id   TEXT NOT NULL,              -- invoice_id or payment_id
    detail_json     TEXT NOT NULL,              -- structured facts + candidates
    suggested_action TEXT NOT NULL,            -- the system's proposal (never posts)
    state           TEXT NOT NULL DEFAULT 'open' CHECK (state IN (
                        'open', 'investigating', 'resolved', 'written_off'
                    )),
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL,              -- UTC ISO-8601
    updated_at      TEXT NOT NULL               -- UTC ISO-8601
);

-- Exactly one OPEN exception per (kind, ref): match re-runs rebuild the
-- OPEN queue without duplicating it.
CREATE UNIQUE INDEX uq_recon_exceptions_open
    ON recon_exceptions (kind, ref_type, ref_public_id)
    WHERE state = 'open';

CREATE INDEX idx_recon_exceptions_state ON recon_exceptions(state);
CREATE INDEX idx_recon_exceptions_kind ON recon_exceptions(kind);

-- Append-only transition audit trail: every state change is actor-stamped.
-- ON DELETE CASCADE: the match run rebuilds auto-generated OPEN exceptions
-- (which carry exactly one history row — their creation), so their audit
-- rows are rebuilt with them. Rows a human has touched are never deleted.
CREATE TABLE recon_exception_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_id    INTEGER NOT NULL REFERENCES recon_exceptions(id) ON DELETE CASCADE,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.

CREATE INDEX idx_recon_exception_events_exc ON recon_exception_events(exception_id, id);

-- Append-only run log: every ingest and match run with its counts.
CREATE TABLE recon_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('ingest_invoices', 'ingest_payments', 'match')),
    stats_json      TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL               -- UTC ISO-8601
);
-- Append-only: application code never UPDATEs or DELETEs this table.
