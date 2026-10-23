-- 007_webhook_hub.down.sql — roll back migration 007_webhook_hub.sql.
--
-- Drops all Q10 tables. Events, lineage, attempts, deliveries, dead
-- letters, routes and endpoint state are synthetic demo data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.

DROP TABLE IF EXISTS webhook_endpoint_state;
DROP TABLE IF EXISTS webhook_dead_letters;
DROP TABLE IF EXISTS webhook_attempts;
DROP TABLE IF EXISTS webhook_deliveries;
DROP TABLE IF EXISTS webhook_derived;
DROP TABLE IF EXISTS webhook_routes;
DROP TABLE IF EXISTS webhook_lineage;
DROP TABLE IF EXISTS webhook_events;
