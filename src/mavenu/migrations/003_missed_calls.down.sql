-- 003_missed_calls.down.sql — rollback step for migration 003_missed_calls.sql.
--
-- Drops every Project Q01 table. Applied by db.rollback_migration().
-- It never touches schema_migrations itself (the runner deletes the
-- migration record after this script succeeds) and never touches
-- Project 01 / Project 02 tables.

DROP TABLE IF EXISTS owner_notifications;
DROP TABLE IF EXISTS call_idempotency_keys;
DROP TABLE IF EXISTS call_events;
DROP TABLE IF EXISTS missed_calls;
