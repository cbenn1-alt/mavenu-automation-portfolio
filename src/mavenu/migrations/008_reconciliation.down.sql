-- 008_reconciliation.down.sql — roll back migration 008_reconciliation.sql.
--
-- Drops all Q05 tables. All rows are synthetic demonstration data, so no
-- production data is at risk. The schema_migrations record is removed
-- by db.rollback_migration() after this script runs, so
-- run_migrations() can re-apply the up-step later.
--
-- NOTE: this intentionally also removes the exceptions queue, match
-- explanations, and run history for Q05. Do not run against a database
-- whose Q05 records you need to keep.

DROP INDEX IF EXISTS uq_recon_exceptions_open;
DROP INDEX IF EXISTS idx_recon_exceptions_state;
DROP INDEX IF EXISTS idx_recon_exceptions_kind;
DROP INDEX IF EXISTS idx_recon_exception_events_exc;
DROP INDEX IF EXISTS idx_recon_matches_invoice;
DROP INDEX IF EXISTS idx_recon_matches_payment;
DROP INDEX IF EXISTS idx_recon_invoices_due;
DROP INDEX IF EXISTS idx_recon_payments_ref;
DROP INDEX IF EXISTS idx_recon_payments_date;

DROP TABLE IF EXISTS recon_runs;
DROP TABLE IF EXISTS recon_exception_events;
DROP TABLE IF EXISTS recon_exceptions;
DROP TABLE IF EXISTS recon_matches;
DROP TABLE IF EXISTS recon_payments;
DROP TABLE IF EXISTS recon_invoices;
