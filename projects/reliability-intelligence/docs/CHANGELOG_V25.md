# V25 change record, security delta and rollback

Added four candidate query-oriented indexes, deterministic 9,301-row synthetic SQLite benchmark, EXPLAIN QUERY PLAN and PRAGMA index_xinfo validation, before/after result equality and timing samples, threshold reports, index-DDL rollback injection, 54 tests, reviewer evidence and CI integration.

Preserved frozen V9 runtime/read-only API, V10 source hashes and V11–V24.1 technical contracts, V23 schema marker 2, V24/24.1 transaction and migration initialization, and all outstanding phase approvals.

Index candidates are installed **only** into disposable temporary database copies. They do not change V23 migration history, approved customer data schemas, operational authentication, production backups, OT/CMMS writes or actual customer performance.

Rollback means reverting V25-only files/CI; no production data/index state exists and the profiling database is auto-deleted.
