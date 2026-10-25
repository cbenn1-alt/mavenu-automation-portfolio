-- 010_kpi_rollup.down.sql — roll back migration 010_kpi_rollup.sql.
--
-- Drops all Q07 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes locations, schema maps, staged
-- rows, quarantine entries, alerts, KPI definitions/values/lineage, and
-- restatement/event history for Q07. Do not run against a database whose
-- Q07 records you need to keep.

DROP INDEX IF EXISTS idx_kpi_events_entity;
DROP INDEX IF EXISTS idx_kpi_alerts_open;
DROP INDEX IF EXISTS idx_kpi_quarantine_loc_period;
DROP INDEX IF EXISTS idx_kpi_staging_period;
DROP INDEX IF EXISTS idx_kpi_staging_loc_period;
DROP INDEX IF EXISTS idx_kpi_ingests_loc_period;
DROP INDEX IF EXISTS idx_kpi_values_period;
DROP INDEX IF EXISTS idx_kpi_lineage_value;
DROP INDEX IF EXISTS uq_kpi_values;

DROP TABLE IF EXISTS kpi_events;
DROP TABLE IF EXISTS kpi_restatements;
DROP TABLE IF EXISTS kpi_lineage;
DROP TABLE IF EXISTS kpi_values;
DROP TABLE IF EXISTS kpi_definitions;
DROP TABLE IF EXISTS kpi_alerts;
DROP TABLE IF EXISTS kpi_quarantine;
DROP TABLE IF EXISTS kpi_staging;
DROP TABLE IF EXISTS kpi_ingests;
DROP TABLE IF EXISTS kpi_schema_maps;
DROP TABLE IF EXISTS kpi_locations;
