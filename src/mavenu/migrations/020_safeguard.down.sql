-- 020_safeguard.down.sql — roll back migration 020_safeguard.sql.
--
-- Drops all N03 tables. All rows are synthetic demonstration fixtures
-- (invented case intakes, checklist states, referral guidance records,
-- findings), so no production data is at risk. The schema_migrations
-- record is removed by db.rollback_migration() after this script runs,
-- so run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes any N03 demo/synthetic case
-- rows. Do not run against a database whose N03 records you need to keep.

DROP INDEX IF EXISTS idx_sg_cases_category;
DROP INDEX IF EXISTS idx_sg_findings_case;
DROP INDEX IF EXISTS idx_sg_referrals_case;
DROP INDEX IF EXISTS idx_sg_checklist_case;
DROP TABLE IF EXISTS safeguard_findings;
DROP TABLE IF EXISTS safeguard_referrals;
DROP TABLE IF EXISTS safeguard_checklist;
DROP TABLE IF EXISTS safeguard_cases;
