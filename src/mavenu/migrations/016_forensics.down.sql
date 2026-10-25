-- 016_forensics.down.sql — roll back migration 016_forensics.sql.
--
-- Drops all S03 tables. All rows are synthetic demonstration data
-- (fixture cases, acquisition manifests, artifacts, timeline events,
-- hypotheses, reports, hash-chain entries), so no production data is at
-- risk. The schema_migrations record is removed by
-- db.rollback_migration() after this script runs, so run_migrations()
-- can re-apply the up-step later.
--
-- NOTE: this intentionally also removes any demo cases and reports for
-- S03. Do not run against a database whose S03 records you need to keep.

DROP INDEX IF EXISTS idx_for_chain_case;
DROP INDEX IF EXISTS idx_for_reports_case;
DROP INDEX IF EXISTS idx_for_hypotheses_case;
DROP INDEX IF EXISTS idx_for_timeline_case;
DROP INDEX IF EXISTS idx_for_artifacts_acq;
DROP INDEX IF EXISTS idx_for_acquisitions_case;

DROP TABLE IF EXISTS forensics_hashchain;
DROP TABLE IF EXISTS forensics_reports;
DROP TABLE IF EXISTS forensics_hypotheses;
DROP TABLE IF EXISTS forensics_timeline_events;
DROP TABLE IF EXISTS forensics_artifacts;
DROP TABLE IF EXISTS forensics_acquisitions;
DROP TABLE IF EXISTS forensics_cases;
