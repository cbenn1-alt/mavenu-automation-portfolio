-- 018_netforensics.down.sql — roll back migration 018_netforensics.sql.
--
-- Drops all N01 tables. All rows are synthetic demonstration data
-- (generated captures, packets, sessions, anomalies, reports), so no
-- production data is at risk. The schema_migrations record is removed by
-- db.rollback_migration() after this script runs, so run_migrations()
-- can re-apply the up-step later.
--
-- NOTE: this intentionally also removes any demo captures and reports for
-- N01. Do not run against a database whose N01 records you need to keep.

DROP INDEX IF EXISTS idx_nf_reports_capture;
DROP INDEX IF EXISTS idx_nf_anomalies_capture;
DROP INDEX IF EXISTS idx_nf_sessions_capture;
DROP INDEX IF EXISTS idx_nf_packets_capture;
DROP INDEX IF EXISTS idx_nf_captures_scenario;

DROP TABLE IF EXISTS netforensics_reports;
DROP TABLE IF EXISTS netforensics_anomalies;
DROP TABLE IF EXISTS netforensics_sessions;
DROP TABLE IF EXISTS netforensics_packets;
DROP TABLE IF EXISTS netforensics_captures;
