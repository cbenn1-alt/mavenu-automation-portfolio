-- 023_governance.down.sql — roll back migration 023 (Project P05).
DROP TABLE IF EXISTS gov_events;
DROP TABLE IF EXISTS gov_incident_events;
DROP TABLE IF EXISTS gov_incidents;
DROP TABLE IF EXISTS gov_runbooks;
DROP TABLE IF EXISTS gov_alerts;
DROP TABLE IF EXISTS gov_rules;
DROP TABLE IF EXISTS gov_dead_letters;
DROP TABLE IF EXISTS gov_jobs;
DROP TABLE IF EXISTS gov_policies;
DROP TABLE IF EXISTS gov_check_runs;
DROP TABLE IF EXISTS gov_checks;
