-- 013_netsec.down.sql — roll back migration 013_netsec.sql.
--
-- Drops all S01 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes alerts, incidents, incident
-- timelines, tuning-log entries, and ruleset version snapshots for S01.
-- Do not run against a database whose S01 records you need to keep.

DROP INDEX IF EXISTS idx_netsec_tuning_type;
DROP INDEX IF EXISTS idx_netsec_incident_events_incident;
DROP INDEX IF EXISTS idx_netsec_incidents_status;
DROP INDEX IF EXISTS idx_netsec_alerts_severity;
DROP INDEX IF EXISTS idx_netsec_alerts_type;

DROP TABLE IF EXISTS netsec_rule_versions;
DROP TABLE IF EXISTS netsec_tuning;
DROP TABLE IF EXISTS netsec_incident_events;
DROP TABLE IF EXISTS netsec_incidents;
DROP TABLE IF EXISTS netsec_alerts;
