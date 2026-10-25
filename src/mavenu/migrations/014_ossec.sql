-- 014_ossec.sql — Project S02 (OS Architecture & Vulnerabilities).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every finding and baseline run
-- stored here describes invented, simulated lab-VM states. No real system,
-- host, account, or vulnerability is represented.
--
-- Design notes:
--   * ossec_findings: one row per vulnerability-class record opened in the
--     lab. Detection evidence is recorded at creation; remediation and
--     verification evidence are attached as the finding moves through its
--     lifecycle. Status transitions are enforced in code (ossec.py); the
--     CHECK constraint is the backstop.
--   * ossec_baseline_runs / ossec_baseline_results: one run per simulated
--     state evaluated, with a per-baseline-item pass/fail result row and
--     the evidence string the verification function produced.

CREATE TABLE ossec_findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id      TEXT NOT NULL,                 -- key into the FINDINGS catalog
    name            TEXT NOT NULL,
    vuln_class      TEXT NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('open','remediated','verified','closed')),
    detection_evidence    TEXT NOT NULL,           -- why we believe it is present
    remediation_evidence  TEXT,                    -- what was changed (simulated)
    verification_evidence TEXT,                    -- proof the fix holds
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE ossec_baseline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    state_label     TEXT NOT NULL,                 -- e.g. 'lab-vm-vulnerable'
    total_items     INTEGER NOT NULL,
    passed          INTEGER NOT NULL,
    failed          INTEGER NOT NULL,
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE ossec_baseline_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES ossec_baseline_runs(id),
    item_id         TEXT NOT NULL,                 -- e.g. 'acct-02'
    category        TEXT NOT NULL,
    passed          INTEGER NOT NULL CHECK (passed IN (0,1)),
    evidence        TEXT NOT NULL,
    UNIQUE (run_id, item_id)
);

CREATE INDEX idx_ossec_findings_status ON ossec_findings(status);
CREATE INDEX idx_ossec_findings_finding_id ON ossec_findings(finding_id);
CREATE INDEX idx_ossec_baseline_results_run ON ossec_baseline_results(run_id);
