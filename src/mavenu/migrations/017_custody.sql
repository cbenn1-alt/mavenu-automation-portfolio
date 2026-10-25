-- 017_custody.sql — Project S04 (Forensic Evidence Management: Chain of Custody).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every case, evidence tag,
-- hash, storage location, actor name, transfer, access record,
-- disposition, and incident stored here is generated fixture material
-- for the S04 method demonstration. No real case, person, device, or
-- evidence is represented. "Evidence" in this project means synthetic
-- placeholder records (invented bytes hashed with SHA-256); nothing here
-- examines a real device or touches a real chain of custody.
--
-- Design notes:
--   * custody_cases: the synthetic case file (case_ref, title,
--     description). One seeded synthetic case exercises everything.
--   * custody_items: the evidence register. ``tag`` is the unique
--     evidence number (e.g. "EV-047-001"). ``acquisition_sha256`` is the
--     SHA-256 captured at intake and is the anchor of every later hash
--     comparison. ``status``: in_custody -> returned | destroyed | archived
--     (terminal; enforced in code by custody.py — a terminal status
--     rejects any further transfer or disposition).
--   * custody_log: the append-only, hash-chained custody journal. Each
--     row commits to the previous row: entry_hash =
--     SHA-256(prev_hash : seq : item_id : created_at : event_type :
--     payload_json : actor).
--     ``seq`` is a strict +1 sequence. verify_custody_chain() recomputes
--     every hash, checks prev_hash linkage, seq monotonicity (+1), and
--     created_at non-decreasing order. Editing ANY field of ANY row breaks
--     verification; inserting a backdated row breaks the timestamp-order
--     check (and the seq check). Rows are never updated or deleted by the
--     module (append-only; only test fixtures may write directly to prove
--     tamper detection).
--   * custody_transfers: two-phase custody handoff. A transfer completes
--     ONLY when BOTH the sender's hash-out AND the receiver's hash-in are
--     recorded AND both equal the item's acquisition_sha256 ("dual hash
--     verification"). A mismatch on either side rejects the transfer and
--     opens a quarantine incident. The item's storage_location changes
--     only on completion.
--   * custody_access: every handling/view is actor-stamped with a purpose.
--     Transfers and dispositions auto-log access rows, so the
--     access-completeness audit (custody.audit_access_coverage) can prove
--     no handling went unrecorded.
--   * custody_dispositions: terminal record — returned | destroyed |
--     archived — with a named authorizer and an authorization reference
--     (synthetic record, not a legal instrument).
--   * custody_incidents: quarantine/incident records opened on hash
--     mismatch, suspected tampering, or lost-form reports. status:
--     open | resolved (resolution is recorded with actor + timestamp).

CREATE TABLE custody_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_ref        TEXT NOT NULL UNIQUE,   -- e.g. CASE-2026-SYN-047
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE custody_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES custody_cases(id),
    tag             TEXT NOT NULL UNIQUE,   -- evidence tag, e.g. EV-047-001
    description     TEXT NOT NULL,
    media_type      TEXT NOT NULL DEFAULT 'placeholder',
    acquisition_sha256 TEXT NOT NULL,      -- SHA-256 captured at intake
    acquired_by     TEXT NOT NULL,         -- actor at intake (synthetic name)
    acquisition_ref TEXT NOT NULL,         -- intake reference (synthetic)
    storage_location TEXT NOT NULL,        -- current locker/shelf
    collected_at    TEXT NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('in_custody','returned','destroyed','archived'))
                    DEFAULT 'in_custody',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_cust_items_case ON custody_items(case_id);

CREATE TABLE custody_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES custody_items(id),
    seq             INTEGER NOT NULL,      -- strict +1 sequence, per log
    event_type      TEXT NOT NULL,         -- e.g. intake, transfer.completed
    payload_json    TEXT NOT NULL DEFAULT '{}',
    actor           TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    entry_hash      TEXT NOT NULL,         -- SHA-256(prev:seq:ts:type:payload:actor)
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_cust_log_item ON custody_log(item_id);
CREATE UNIQUE INDEX uq_cust_log_seq ON custody_log(seq);

CREATE TABLE custody_transfers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES custody_items(id),
    sender          TEXT NOT NULL,
    receiver        TEXT NOT NULL,
    purpose         TEXT NOT NULL,
    destination_location TEXT NOT NULL,
    hash_out        TEXT,                  -- sender's hash-out (NULL until recorded)
    hash_in         TEXT,                  -- receiver's hash-in (NULL until recorded)
    status          TEXT NOT NULL
                    CHECK (status IN ('initiated','completed','rejected'))
                    DEFAULT 'initiated',
    incident_id     INTEGER REFERENCES custody_incidents(id),
    initiated_at    TEXT NOT NULL,
    completed_at    TEXT
);
CREATE INDEX idx_cust_transfers_item ON custody_transfers(item_id);

CREATE TABLE custody_access (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES custody_items(id),
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,         -- intake, storage_check, transfer_out,
                                          -- transfer_in, inventory, disposition, view
    purpose         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_cust_access_item ON custody_access(item_id);

CREATE TABLE custody_dispositions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES custody_items(id),
    disposition     TEXT NOT NULL
                    CHECK (disposition IN ('returned','destroyed','archived')),
    authorized_by   TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,       -- synthetic authorization record
    detail          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_cust_disp_item ON custody_dispositions(item_id);

CREATE TABLE custody_incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER REFERENCES custody_items(id),
    kind            TEXT NOT NULL
                    CHECK (kind IN ('hash_mismatch','suspected_tampering','lost_form','other')),
    detail          TEXT NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('open','resolved'))
                    DEFAULT 'open',
    opened_by       TEXT NOT NULL,
    opened_at       TEXT NOT NULL,
    resolved_at     TEXT
);
CREATE INDEX idx_cust_incidents_item ON custody_incidents(item_id);
