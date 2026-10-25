-- 011_reviews.down.sql — roll back migration 011_reviews.sql.
--
-- Drops all Q08 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes lexicons, reviews, tags, queue
-- entries, drafts, escalations, and review event history for Q08. Do not
-- run against a database whose Q08 records you need to keep.

DROP INDEX IF EXISTS idx_review_lexicons_version;
DROP INDEX IF EXISTS idx_review_events_review;
DROP INDEX IF EXISTS idx_review_drafts_status;
DROP INDEX IF EXISTS idx_review_tags_review;
DROP INDEX IF EXISTS idx_review_queues_queue_status;
DROP INDEX IF EXISTS idx_review_queues_status;

DROP TABLE IF EXISTS review_events;
DROP TABLE IF EXISTS review_escalations;
DROP TABLE IF EXISTS review_drafts;
DROP TABLE IF EXISTS review_queues;
DROP TABLE IF EXISTS review_tags;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS review_lexicons;
