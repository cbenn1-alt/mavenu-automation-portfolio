-- 012_dispatch.down.sql — roll back migration 012_dispatch.sql.
--
-- Drops all Q09 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes techs, jobs, runs, assignments,
-- infeasibility reports, overrides, and dispatch event history for Q09.
-- Do not run against a database whose Q09 records you need to keep.

DROP INDEX IF EXISTS idx_dispatch_events_type;
DROP INDEX IF EXISTS idx_dispatch_events_run;
DROP INDEX IF EXISTS idx_dispatch_overrides_job;
DROP INDEX IF EXISTS idx_dispatch_infeasibility_run;
DROP INDEX IF EXISTS idx_dispatch_assignments_tech;
DROP INDEX IF EXISTS idx_dispatch_assignments_run;

DROP TABLE IF EXISTS dispatch_events;
DROP TABLE IF EXISTS dispatch_overrides;
DROP TABLE IF EXISTS dispatch_infeasibility;
DROP TABLE IF EXISTS dispatch_assignments;
DROP TABLE IF EXISTS dispatch_runs;
DROP TABLE IF EXISTS dispatch_jobs;
DROP TABLE IF EXISTS dispatch_techs;
