-- 014_ossec.down.sql — roll back migration 014_ossec.sql.
--
-- Drops all S02 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes finding records and baseline-run
-- history for S02. Do not run against a database whose S02 records you
-- need to keep.

DROP INDEX IF EXISTS idx_ossec_baseline_results_run;
DROP INDEX IF EXISTS idx_ossec_findings_finding_id;
DROP INDEX IF EXISTS idx_ossec_findings_status;

DROP TABLE IF EXISTS ossec_baseline_results;
DROP TABLE IF EXISTS ossec_baseline_runs;
DROP TABLE IF EXISTS ossec_findings;
