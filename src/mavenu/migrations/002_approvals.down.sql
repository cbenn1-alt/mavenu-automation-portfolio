-- 002_approvals.down.sql — rollback step for migration 002_approvals.sql.
--
-- Drops every Project 02 table. Applied by db.rollback_migration().
-- It never touches schema_migrations itself (the runner deletes the
-- migration record after this script succeeds) and never touches
-- Project 01 tables.

DROP TABLE IF EXISTS request_idempotency_keys;
DROP TABLE IF EXISTS request_events;
DROP TABLE IF EXISTS requests;
