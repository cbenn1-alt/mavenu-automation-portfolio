# V26 change, security delta and rollback

Added provisional isolation/data-rights decision (pooled, database-per-tenant, schema-per-tenant alternatives), six fictional actor grants, 38-row overlapping-ID synthetic fixture, two bound scoped read queries, uniform denial, exhaustive 48-case matrix, ten malformed probes, 118 new tests and unsigned review evidence.

Preserved frozen V9 read-only runtime, V10 18-file source, V21/V22 model, V23/V24.1 migrations, V24 receipts, V25 index prototypes and blocked formal phase approvals.

**Security limits:** Synthetic actor IDs are not authenticated; unrestricted SQL can read across all tenants, intentionally demonstrated in tests. Composite keys and application WHERE clauses are not RLS. No real customer records, DPA, production authn/authz, backup, OT/CMMS writes or proven financial value.

Rollback removes V26-only code, docs, tests and CI additions. Disposable SQLite files are deleted automatically; no customer state exists to migrate.
