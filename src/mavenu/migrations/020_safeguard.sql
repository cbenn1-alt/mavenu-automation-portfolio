-- 020_safeguard.sql — Project N03 (Safeguard: victim-centered, lawful
-- online-abuse triage & referral framework).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every case, checklist note,
-- referral, and finding stored here is an invented fixture for the
-- preserve → report → refer method demonstration. This framework
-- REFERS; it does not pursue. It contains no messaging, email, or
-- network capability — there is no outreach mechanism to misuse.
--
-- Design notes:
--   * safeguard_cases: synthetic case intake with safety-triage fields.
--     category is CHECK-constrained to the 8 known categories.
--   * safeguard_checklist: one row per playbook step per case; action is
--     CHECK-constrained to the CLOSED action vocabulary
--     (preserve/report/refer/safety_plan/document/escalate_to_authorities).
--     No "investigate suspect" / "contact suspect" action can be stored.
--   * safeguard_referrals: referral *guidance* records (where to refer
--     and what to bring) — never real contacts, never outreach logs.
--   * safeguard_findings: attribution discipline — status is lead /
--     verified / unknown; "verified" rows must carry an evidence_ref
--     (enforced in safeguard.py); inferences carry confidence.

CREATE TABLE safeguard_cases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    case_ref         TEXT NOT NULL UNIQUE,
    category         TEXT NOT NULL CHECK (category IN (
                         'internet_trolling','swatting','cyberbullying',
                         'cyberharassment','cyberstalking','sextortion',
                         'nc_ii_abuse','child_sexual_exploitation')),
    reporter_role    TEXT NOT NULL,
    summary          TEXT NOT NULL,
    immediate_danger INTEGER NOT NULL DEFAULT 0 CHECK (immediate_danger IN (0,1)),
    involves_minor   INTEGER NOT NULL DEFAULT 0 CHECK (involves_minor IN (0,1)),
    safety_status    TEXT NOT NULL CHECK (safety_status IN (
                         'standard','minor-safeguarding','emergency')),
    guidance_json    TEXT NOT NULL,  -- JSON list of safety-triage guidance strings
    stage            TEXT NOT NULL DEFAULT 'triaged'
                     CHECK (stage IN ('intake','triaged','active','referred','closed')),
    synthetic        INTEGER NOT NULL DEFAULT 1 CHECK (synthetic IN (0,1)),
    created_at       TEXT NOT NULL
);

CREATE TABLE safeguard_checklist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    INTEGER NOT NULL REFERENCES safeguard_cases(id),
    step_id    TEXT NOT NULL,
    action     TEXT NOT NULL CHECK (action IN (
                   'preserve','report','refer','safety_plan','document',
                   'escalate_to_authorities')),
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','done','skipped')),
    note       TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (case_id, step_id)
);

CREATE TABLE safeguard_referrals (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id              INTEGER NOT NULL REFERENCES safeguard_cases(id),
    org_key              TEXT NOT NULL,
    org_name             TEXT NOT NULL,
    purpose              TEXT NOT NULL,
    what_to_provide_json TEXT NOT NULL,  -- JSON list
    guidance             TEXT NOT NULL,  -- referral guidance text (no outreach performed)
    created_at           TEXT NOT NULL
);

CREATE TABLE safeguard_findings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER NOT NULL REFERENCES safeguard_cases(id),
    statement    TEXT NOT NULL,
    claim_type   TEXT NOT NULL CHECK (claim_type IN ('fact','inference')),
    status       TEXT NOT NULL CHECK (status IN ('lead','verified','unknown')),
    confidence   TEXT CHECK (confidence IS NULL
                             OR confidence IN ('low','medium','high')),
    evidence_ref TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX idx_sg_checklist_case  ON safeguard_checklist(case_id);
CREATE INDEX idx_sg_referrals_case  ON safeguard_referrals(case_id);
CREATE INDEX idx_sg_findings_case   ON safeguard_findings(case_id);
CREATE INDEX idx_sg_cases_category  ON safeguard_cases(category);
