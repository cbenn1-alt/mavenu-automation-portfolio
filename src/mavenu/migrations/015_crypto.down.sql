-- 015_crypto.down.sql — roll back migration 015_crypto.sql.
--
-- Drops all S05 tables. All rows are synthetic demonstration data (test-only
-- keys, demo envelopes, lifecycle events), so no production data is at risk.
-- The schema_migrations record is removed by db.rollback_migration() after
-- this script runs, so run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes the demo key registry and stored
-- demo messages for S05. Do not run against a database whose S05 records
-- you need to keep.

DROP INDEX IF EXISTS idx_crypto_messages_version;
DROP INDEX IF EXISTS idx_crypto_key_events_version;

DROP TABLE IF EXISTS crypto_messages;
DROP TABLE IF EXISTS crypto_key_events;
DROP TABLE IF EXISTS crypto_keys;
