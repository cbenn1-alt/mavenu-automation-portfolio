-- 009_entity_resolution.down.sql — roll back migration 009_entity_resolution.sql.
--
-- Drops all Q06 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes sources, contacts, blocks, pairs,
-- merge proposals, merge audit rows, events, and run history for Q06. Do
-- not run against a database whose Q06 records you need to keep.

DROP INDEX IF EXISTS idx_er_merge_audit_proposal;
DROP INDEX IF EXISTS idx_er_merges_state;
DROP INDEX IF EXISTS idx_er_pairs_contacts;
DROP INDEX IF EXISTS idx_er_pairs_band;
DROP INDEX IF EXISTS idx_er_blocks_key;
DROP INDEX IF EXISTS idx_er_contacts_email;
DROP INDEX IF EXISTS idx_er_contacts_phone;
DROP INDEX IF EXISTS idx_er_contacts_status;
DROP INDEX IF EXISTS idx_er_contacts_source;
DROP INDEX IF EXISTS idx_er_events_entity;

DROP TABLE IF EXISTS er_runs;
DROP TABLE IF EXISTS er_events;
DROP TABLE IF EXISTS er_merge_audit;
DROP TABLE IF EXISTS er_merge_proposals;
DROP TABLE IF EXISTS er_pairs;
DROP TABLE IF EXISTS er_blocks;
DROP TABLE IF EXISTS er_contacts;
DROP TABLE IF EXISTS er_sources;
