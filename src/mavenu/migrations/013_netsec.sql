-- 013_netsec.sql — Project S01 (Network Security: Defensive Lab & Monitoring).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every alert, incident, tuning
-- entry, and ruleset version stored here is fabricated for the lab demo.
-- No real networks, hosts, or events are represented.
--
-- Design notes:
--   * netsec_alerts: one row per synthetic alert ingested by the pipeline.
--     `suppressed` marks alerts silenced/throttled by a fatigue-tuning
--     entry — suppression stays reviewable (the tuning row is linked by
--     alert_type), never silent.
--   * netsec_incidents / netsec_incident_events: ticket lifecycle with an
--     append-only, actor-stamped timeline. Status transitions are enforced
--     in code (netsec.py); the CHECK constraint is the backstop.
--   * netsec_tuning: the alert-fatigue log — what was silenced, throttled,
--     or de-escalated and WHY. A tuning row without a reason is not valid.
--   * netsec_rule_versions: versioned snapshots of the firewall ruleset as
--     JSON — the config-rollback record (revert = restore an earlier row).

CREATE TABLE netsec_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id        TEXT NOT NULL UNIQUE,          -- e.g. 'SYN-123456'
    alert_type      TEXT NOT NULL,                 -- key into the alert catalog
    severity        TEXT NOT NULL
                    CHECK (severity IN ('info','low','medium','high','critical')),
    source_ip       TEXT NOT NULL,                 -- synthetic source address
    suppressed      INTEGER NOT NULL DEFAULT 0 CHECK (suppressed IN (0,1)),
    detail          TEXT NOT NULL,                 -- JSON: description + steps
    created_at      TEXT NOT NULL
);

CREATE TABLE netsec_incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    severity        TEXT NOT NULL
                    CHECK (severity IN ('info','low','medium','high','critical')),
    status          TEXT NOT NULL
                    CHECK (status IN ('open','triaged','contained','resolved','closed')),
    source_alert_type TEXT,
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE netsec_incident_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES netsec_incidents(id),
    event_type      TEXT NOT NULL,                 -- 'created' | 'transition'
    actor           TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT,
    detail          TEXT,                          -- JSON
    created_at      TEXT NOT NULL
);

CREATE TABLE netsec_tuning (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type      TEXT NOT NULL,
    action          TEXT NOT NULL
                    CHECK (action IN ('silence','threshold','de-escalate')),
    reason          TEXT NOT NULL,                 -- WHY (mandatory)
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE netsec_rule_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    version         TEXT NOT NULL,
    ruleset_json    TEXT NOT NULL,                 -- full ordered ruleset
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_netsec_alerts_type ON netsec_alerts(alert_type);
CREATE INDEX idx_netsec_alerts_severity ON netsec_alerts(severity);
CREATE INDEX idx_netsec_incidents_status ON netsec_incidents(status);
CREATE INDEX idx_netsec_incident_events_incident ON netsec_incident_events(incident_id);
CREATE INDEX idx_netsec_tuning_type ON netsec_tuning(alert_type);
