# V27 change record, security delta and rollback

**Added:** Daily 02:15 UTC cron design and time-state evaluator, SQLite online copy from V24 committed synthetic temporary DB to an isolated temporary target, independent source/copy checks (integrity, FKs, record/event/receipt hashes), reopen confirmation, file-length/SHA-256 telemetry, three failure injections, 81 tests, verification reports and unsigned review.

**Preserved:** Frozen V9 application 0.9.0/read-only API v1/schema 1.3.0; V10 18-file freeze; V21/V22 canonical schema and identities; V23 migrations, V24/V24.1 transactions, V25 index trial and V26 unratified isolation/data-rights decision. All prior human signoffs remain outstanding.

**No production enablement:** No actual scheduled job, retained copy, cloud/offsite export, customer data, credential, backup encryption, RPO/RTO benchmark, actual disaster restore, tenant authorization, industrial-control or CMMS write, or legally approved retention. Temporary SQLite files are cleaned after each scenario.

**Rollback:** Revert V27-only scripts/JSON/tests/docs/workflow. There is no customer database or backup storage to migrate or delete.
