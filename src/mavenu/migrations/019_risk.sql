-- 019_risk.sql — Project N02 (Cyber Risk Assessment & Management).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. The fictional "Synthetic Test
-- Co." and every asset, threat, rating, remediation cost, and effort figure
-- stored here are invented fixtures for the risk-workbook demonstration.
-- Scores are illustrative — NEVER an audit opinion or certification.
--
-- Design notes:
--   * risk_assets: synthetic asset inventory (hardware/software/data/people/facilities)
--   * risk_threats: threat catalog; applies_to is a JSON list of asset types
--   * risk_register: one row per asset x threat pairing; scores are computed
--     by risk.py (likelihood x max(C,I,A)) — the DB stores the rated levels,
--     never a hand-typed score, so stored rows cannot drift from the rules.
--   * risk_remediations / risk_remediation_effects: planned remediations and
--     their level-reduction effects. Money is INTEGER cents (Decimal-exact);
--     cost_basis / effort_basis are labeled "synthetic estimate".
--   * risk_snapshots: inherent + residual register snapshots as JSON.

CREATE TABLE risk_assets (
    asset_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    asset_type  TEXT NOT NULL
                CHECK (asset_type IN ('hardware','software','data','people','facilities')),
    description TEXT NOT NULL,
    location    TEXT NOT NULL
);

CREATE TABLE risk_threats (
    threat_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    vuln_class  TEXT NOT NULL,
    applies_to  TEXT NOT NULL  -- JSON list of asset types
);

CREATE TABLE risk_register (
    risk_id              TEXT PRIMARY KEY,
    asset_id             TEXT NOT NULL REFERENCES risk_assets(asset_id),
    threat_id            TEXT NOT NULL REFERENCES risk_threats(threat_id),
    likelihood           INTEGER NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
    impact_c             INTEGER NOT NULL CHECK (impact_c BETWEEN 1 AND 5),
    impact_i             INTEGER NOT NULL CHECK (impact_i BETWEEN 1 AND 5),
    impact_a             INTEGER NOT NULL CHECK (impact_a BETWEEN 1 AND 5),
    likelihood_rationale TEXT NOT NULL,
    impact_rationale     TEXT NOT NULL,
    controls_json        TEXT NOT NULL,  -- JSON list of {ref, note?, reason?}
    treatment            TEXT NOT NULL DEFAULT 'mitigate'
                         CHECK (treatment IN ('mitigate','accept','transfer','avoid'))
);

CREATE TABLE risk_remediations (
    rem_id          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    cost_usd_cents  INTEGER NOT NULL CHECK (cost_usd_cents >= 0),
    cost_basis      TEXT NOT NULL,   -- labeled "synthetic estimate"
    effort_hours    INTEGER NOT NULL CHECK (effort_hours >= 0),
    effort_basis    TEXT NOT NULL    -- labeled "synthetic estimate"
);

CREATE TABLE risk_remediation_effects (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    rem_id    TEXT NOT NULL REFERENCES risk_remediations(rem_id),
    risk_id   TEXT NOT NULL REFERENCES risk_register(risk_id),
    field     TEXT NOT NULL
              CHECK (field IN ('likelihood','impact_c','impact_i','impact_a')),
    new_value INTEGER NOT NULL CHECK (new_value BETWEEN 1 AND 5)
);

CREATE TABLE risk_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    label        TEXT NOT NULL CHECK (label IN ('inherent','residual')),
    created_at   TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_risk_register_asset  ON risk_register(asset_id);
CREATE INDEX idx_risk_register_threat ON risk_register(threat_id);
CREATE INDEX idx_risk_effects_rem      ON risk_remediation_effects(rem_id);
CREATE INDEX idx_risk_effects_risk     ON risk_remediation_effects(risk_id);
