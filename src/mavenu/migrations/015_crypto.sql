-- 015_crypto.sql — Project S05 (Applied Cryptography).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every key, message, and event
-- stored here is generated test material for the S05 teaching demos. No
-- real system, user, or secret is represented. Keys are labeled test-only.
--
-- Design notes:
--   * crypto_keys: versioned key registry. One 'active' version at a time
--     (enforced in code by crypto_demo.create_key; the UNIQUE on key_version
--     is the backstop). 'retired' keys stay decryptable (old data readable);
--     'destroyed' keys are wiped (zeros) + tombstoned and refuse use.
--   * crypto_key_events: append-only lifecycle log (created/rotated/
--     destroyed/compromised/reencrypted), actor-stamped.
--   * crypto_messages: demo envelopes encrypted under the active key at
--     write time; key_version records which version to decrypt with.
--     The nonce/tag/ciphertext are hex; plaintext is never stored.

CREATE TABLE crypto_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_version     INTEGER NOT NULL UNIQUE,
    key_hex         TEXT NOT NULL,                 -- synthetic demo key (test-only)
    status          TEXT NOT NULL
                    CHECK (status IN ('active','retired','compromised','destroyed')),
    created_at      TEXT NOT NULL,
    rotated_at      TEXT,
    note            TEXT NOT NULL DEFAULT ''
);

CREATE TABLE crypto_key_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_version     INTEGER NOT NULL,
    event           TEXT NOT NULL
                    CHECK (event IN ('created','rotated','destroyed','compromised','reencrypted')),
    actor           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_crypto_key_events_version ON crypto_key_events(key_version);

CREATE TABLE crypto_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_version     INTEGER NOT NULL,              -- version used at write time
    nonce_hex       TEXT NOT NULL,
    ct_hex          TEXT NOT NULL,
    tag_hex         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_crypto_messages_version ON crypto_messages(key_version);
