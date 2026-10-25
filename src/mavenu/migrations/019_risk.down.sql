-- 019_risk.down.sql — roll back migration 019_risk.sql.
--
-- Drops all N02 tables. All rows are synthetic demonstration fixtures
-- (fictional company inventory, threats, register, remediations, snapshots),
-- so no production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so run_migrations()
-- can re-apply the up-step later.
--
-- NOTE: this intentionally also removes any seeded N02 workbook rows.
-- Do not run against a database whose N02 records you need to keep.

DROP INDEX IF EXISTS idx_risk_effects_risk;
DROP INDEX IF EXISTS idx_risk_effects_rem;
DROP INDEX IF EXISTS idx_risk_register_threat;
DROP INDEX IF EXISTS idx_risk_register_asset;
DROP TABLE IF EXISTS risk_snapshots;
DROP TABLE IF EXISTS risk_remediation_effects;
DROP TABLE IF EXISTS risk_remediations;
DROP TABLE IF EXISTS risk_register;
DROP TABLE IF EXISTS risk_threats;
DROP TABLE IF EXISTS risk_assets;
