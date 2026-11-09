-- V25 candidate indexes, disposable synthetic benchmark ONLY.
-- Not a versioned production migration: PRAGMA user_version stays 2.
-- Four query-oriented indexes; benchmark database deleted after each run.
CREATE INDEX idx_v25_case_site_recent ON maintenance_case (tenant_id ASC, site_id ASC, occurred_at_utc DESC, case_id ASC);
CREATE INDEX idx_v25_case_asset_recent ON maintenance_case (tenant_id ASC, site_id ASC, asset_id ASC, occurred_at_utc DESC, case_id ASC);
CREATE INDEX idx_v25_case_failure_recent ON maintenance_case (tenant_id ASC, site_id ASC, failure_code ASC, occurred_at_utc DESC, case_id ASC);
CREATE INDEX idx_v25_evidence_reverse ON evidence_reference (tenant_id ASC, site_id ASC, evidence_ref ASC, case_id ASC);
