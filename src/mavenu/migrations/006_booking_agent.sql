-- 006_booking_agent.sql — Project Q04 (Conversational Booking Agent) schema.
--
-- All data in this project is synthetic demonstration data. Conversations
-- are scripted exchanges with a deterministic rule-driven dialogue policy
-- (NOT a language model — see src/mavenu/dialogue.py). No real callers,
-- no real bookings, no real scheduling-system integration: the bundled
-- DemoBookingAdapter writes booking rows to SQLite behind the same
-- adapter-interface pattern as P01's BookingAdapter.
--
-- Privacy: caller utterances are stored MASKED (phone digits and email
-- addresses redacted at write time; see src/mavenu/booking_agent.py).
-- Raw PII never reaches these tables. Retention: closed conversations are
-- purged of transcript text after 90 days by purge_old_conversations()
-- (policy documented in projects/project_q04/SECURITY.md).
--
-- Tables:
--   booking_conversations   one row per dialogue session; finite-state
--                           machine state in `state`
--   booking_turns           every agent AND caller turn, in order
--                           (transcript + per-turn decision log)
--   booking_slots           filled slots (service/location/window/contact),
--                           values stored masked
--   booking_handoffs        escalation packages to the human queue
--   booking_bookings        bookings — written ONLY after the adapter
--                           confirms (zero rows without adapter confirmation)

CREATE TABLE booking_conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id       TEXT NOT NULL UNIQUE,          -- e.g. CONV-000001
    state           TEXT NOT NULL DEFAULT 'greeting'
                        CHECK (state IN (
                            'greeting','service','location','window',
                            'contact','confirm','booked','handoff'
                        )),
    turn_count      INTEGER NOT NULL DEFAULT 0,  -- agent + caller turns logged
    handoff_reason  TEXT,                        -- set when state = 'handoff'
    booking_ref     TEXT,                        -- set when state = 'booked'
    created_at      TEXT NOT NULL,               -- UTC ISO-8601
    updated_at      TEXT NOT NULL                -- UTC ISO-8601
);

CREATE INDEX idx_booking_conv_state ON booking_conversations(state);

CREATE TABLE booking_turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES booking_conversations(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,            -- 0-based, gapless per conversation
    role            TEXT NOT NULL CHECK (role IN ('agent','caller')),
    text            TEXT NOT NULL,               -- caller text is stored MASKED
    confidence      REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    -- Per-turn decision log: state_before/state_after, action, extracted
    -- slots (masked), reason. Every FSM transition is recorded here.
    decision_json   TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,               -- UTC ISO-8601
    UNIQUE (conversation_id, turn_index)
);

CREATE INDEX idx_booking_turns_conv ON booking_turns(conversation_id, turn_index);

CREATE TABLE booking_slots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES booking_conversations(id) ON DELETE CASCADE,
    slot_name       TEXT NOT NULL CHECK (slot_name IN (
                        'service','location','window',
                        'contact_name','contact_phone'
                    )),
    value_masked    TEXT NOT NULL,               -- masked at write time
    confidence      REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at      TEXT NOT NULL,               -- UTC ISO-8601
    updated_at      TEXT NOT NULL,               -- UTC ISO-8601
    UNIQUE (conversation_id, slot_name)
);

CREATE TABLE booking_handoffs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES booking_conversations(id) ON DELETE CASCADE,
    reason          TEXT NOT NULL CHECK (reason IN (
                        'low_confidence','max_turns','suspicious_input',
                        'contradictory_input','slot_declined','booking_failed'
                    )),
    reason_detail   TEXT NOT NULL DEFAULT '',
    transcript_json TEXT NOT NULL,               -- masked transcript snapshot
    slots_json      TEXT NOT NULL DEFAULT '{}',  -- masked slots snapshot
    status          TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','claimed','resolved')),
    created_at      TEXT NOT NULL                -- UTC ISO-8601
);

CREATE INDEX idx_booking_handoffs_status ON booking_handoffs(status);

-- Bookings exist ONLY as a consequence of an adapter confirmation.
-- The application writes this row only after
-- BookingAdapter.create_booking() returns a reference; there is no other
-- code path that inserts here.
CREATE TABLE booking_bookings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL UNIQUE REFERENCES booking_conversations(id) ON DELETE CASCADE,
    booking_ref     TEXT NOT NULL UNIQUE,        -- returned by the adapter
    adapter_name    TEXT NOT NULL,
    slot_when       TEXT NOT NULL,               -- adapter-provided slot text
    slots_json      TEXT NOT NULL DEFAULT '{}',  -- masked slots snapshot
    created_at      TEXT NOT NULL                -- UTC ISO-8601
);
