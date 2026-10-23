-- 006_booking_agent.down.sql — roll back migration 006_booking_agent.sql.
--
-- Drops all Q04 tables. Conversations, transcripts, handoffs and bookings
-- are synthetic demo data, so no production data is at risk. The
-- schema_migrations record is removed by db.rollback_migration() after
-- this script runs, so run_migrations() can re-apply the up-step later.

DROP TABLE IF EXISTS booking_bookings;
DROP TABLE IF EXISTS booking_handoffs;
DROP TABLE IF EXISTS booking_slots;
DROP TABLE IF EXISTS booking_turns;
DROP TABLE IF EXISTS booking_conversations;
