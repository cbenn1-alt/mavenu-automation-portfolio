-- 017_custody.down.sql — rollback for 017_custody.sql (Project S04).
-- Drops all S04 tables. Order: children first to respect FK references.

DROP TABLE IF EXISTS custody_transfers;
DROP TABLE IF EXISTS custody_incidents;
DROP TABLE IF EXISTS custody_dispositions;
DROP TABLE IF EXISTS custody_access;
DROP TABLE IF EXISTS custody_transfers;
DROP TABLE IF EXISTS custody_log;
DROP TABLE IF EXISTS custody_items;
DROP TABLE IF EXISTS custody_cases;
DROP TABLE IF EXISTS custody_access;
