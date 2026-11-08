-- 021_docintel.down.sql — roll back migration 021_docintel.sql.
--
-- Drops all seven docintel_* tables and is safe to re-apply afterwards:
-- run_migrations() will re-run the up-step cleanly. Destructive to P03
-- data by design — export what you need first (see RUNBOOK.md).
-- Other projects' tables are untouched (verified in
-- test_docintel.py::test_migration_021_down_step_rolls_back_for_real).

DROP TABLE IF EXISTS docintel_runs;
DROP TABLE IF EXISTS docintel_doc_events;
DROP TABLE IF EXISTS docintel_field_events;
DROP TABLE IF EXISTS docintel_exception_events;
DROP TABLE IF EXISTS docintel_exceptions;
DROP TABLE IF EXISTS docintel_fields;
DROP TABLE IF EXISTS docintel_documents;
