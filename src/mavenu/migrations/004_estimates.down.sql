-- 004_estimates.down.sql — rollback step for migration 004_estimates.sql.
--
-- Drops every Project Q02 table. Applied by db.rollback_migration().
-- It never touches schema_migrations itself (the runner deletes the
-- migration record after this script succeeds) and never touches
-- Project 01 / Project 02 / Q01 tables.

DROP TABLE IF EXISTS estimate_idempotency_keys;
DROP TABLE IF EXISTS send_log;
DROP TABLE IF EXISTS estimate_outbox;
DROP TABLE IF EXISTS message_templates;
DROP TABLE IF EXISTS cadence_rules;
DROP TABLE IF EXISTS estimate_events;
DROP TABLE IF EXISTS estimates;
