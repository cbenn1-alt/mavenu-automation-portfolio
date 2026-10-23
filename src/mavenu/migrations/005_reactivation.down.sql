-- 005_reactivation.down.sql — roll back the Q03 (Customer Reactivation
-- Engine) schema. Drops every Q03 table and nothing else; P01 / P02 /
-- Q01 / Q02 tables are untouched.
--
-- Drop order respects foreign keys: jobs, outbox, send_log, holdouts, and
-- events reference reactivation_customers, so they go first.

DROP TABLE IF EXISTS reactivation_events;
DROP TABLE IF EXISTS reactivation_holdouts;
DROP TABLE IF EXISTS reactivation_send_log;
DROP TABLE IF EXISTS reactivation_outbox;
DROP TABLE IF EXISTS reactivation_jobs;
DROP TABLE IF EXISTS reactivation_customers;
