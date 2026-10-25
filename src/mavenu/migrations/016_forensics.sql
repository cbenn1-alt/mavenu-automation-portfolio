-- 016_forensics.sql — Project S03 (Digital Forensic Applications).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every case, authorization
-- record, acquisition manifest, artifact, timeline event, hypothesis,
-- and report stored here is generated fixture material for the S03
-- method demonstration. No real device, person, or system is represented.
-- The "disk image" this workflow acquires is a synthetic directory tree
-- plus a manifest; nothing here touches a real filesystem beyond the
-- fixture trees generated under synthetic_cases/ or tests' tmp dirs.
--
-- Design notes:
--   * forensics_cases: case intake + synthetic authorization record
--     (authorizer_name / authorization_ref) + handling plan. Stages:
--     intake -> acquired -> examined -> analyzed -> reported (enforced
--     in code by forensics.py).
--   * forensics_acquisitions: hashed acquisition of the synthetic tree.
--     start_hash snapshots the directory listing before content is read;
--     manifest_hash covers the canonical per-file manifest after.
--   * forensics_artifacts: examination output (file listings with MAC
--     times, parsed log events, carved "deleted" entries), keyed to the
--     acquisition so every finding traces back to hashed evidence.
--   * forensics_timeline_events: merged chronological events for a case.
--   * forensics_hypotheses: statement + BOTH supporting and contradicting
--     evidence (confirmation-bias control, enforced in code).
--   * forensics_reports: findings with facts/inference separation; an
--     inference without a confidence level is rejected by validation.
--   * forensics_hashchain: append-only SHA-256 chain across every
--     handoff (case opened, acquisition start/complete, each examination
--     step, timeline, hypothesis, report). verify_chain() recomputes it.

CREATE TABLE forensics_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_ref        TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    authorizer_name TEXT NOT NULL,      -- synthetic authorization record
    authorization_ref TEXT NOT NULL,    -- synthetic authorization record
    handling_plan_json TEXT NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('intake','acquired','examined','analyzed','reported')),
    created_at      TEXT NOT NULL
);

CREATE TABLE forensics_acquisitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES forensics_cases(id),
    method          TEXT NOT NULL,
    source_label    TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    start_hash      TEXT NOT NULL,      -- hash of the directory listing snapshot
    manifest_json   TEXT NOT NULL,      -- canonical per-file manifest
    manifest_hash   TEXT NOT NULL,      -- SHA-256 of the canonical manifest
    file_count      INTEGER NOT NULL,
    total_bytes     INTEGER NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('complete','failed'))
                    DEFAULT 'complete'
);
CREATE INDEX idx_for_acquisitions_case ON forensics_acquisitions(case_id);

CREATE TABLE forensics_artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_id  INTEGER NOT NULL REFERENCES forensics_acquisitions(id),
    kind            TEXT NOT NULL
                    CHECK (kind IN ('file','log_event','carved')),
    ref_path        TEXT NOT NULL,
    detail_json     TEXT NOT NULL DEFAULT '{}',
    sha256          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_for_artifacts_acq ON forensics_artifacts(acquisition_id);

CREATE TABLE forensics_timeline_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES forensics_cases(id),
    ts              TEXT NOT NULL,      -- ISO-8601, UTC
    source          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    summary         TEXT NOT NULL,
    ref             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_for_timeline_case ON forensics_timeline_events(case_id);

CREATE TABLE forensics_hypotheses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES forensics_cases(id),
    statement       TEXT NOT NULL,
    supporting_json TEXT NOT NULL,      -- non-empty list of evidence refs
    contradicting_json TEXT NOT NULL,   -- non-empty list of evidence refs
    status          TEXT NOT NULL
                    CHECK (status IN ('open','supported','refuted','unresolved')),
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_for_hypotheses_case ON forensics_hypotheses(case_id);

CREATE TABLE forensics_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES forensics_cases(id),
    findings_json   TEXT NOT NULL,
    audit_json      TEXT NOT NULL,      -- facts/inference audit result
    report_text     TEXT NOT NULL,      -- rendered Markdown report
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_for_reports_case ON forensics_reports(case_id);

CREATE TABLE forensics_hashchain (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES forensics_cases(id),
    step            TEXT NOT NULL,      -- e.g. acquisition.complete
    payload         TEXT NOT NULL,
    payload_hash    TEXT NOT NULL,      -- SHA-256(prev_hash:step:payload)
    prev_hash       TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_for_chain_case ON forensics_hashchain(case_id);
