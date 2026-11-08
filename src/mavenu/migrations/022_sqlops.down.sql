-- 022_sqlops.down.sql — roll back migration 022 (Project P04).
DROP TABLE IF EXISTS sqlops_events;
DROP TABLE IF EXISTS sqlops_snapshots;
DROP TABLE IF EXISTS sqlops_runs;
DROP TABLE IF EXISTS sqlops_queries;
