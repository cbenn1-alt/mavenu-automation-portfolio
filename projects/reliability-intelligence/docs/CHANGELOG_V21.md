# V21 change, security delta and rollback

**Added:** Ten-entity SQLite DDL design, machine-readable relationship model, V16 source-to-entity synthetic mapper, ephemeral :memory: integrity and tenancy-FK validation, schema review evidence, negative tests and controlled documentation.

**Unchanged:** V9 frozen runtime 0.9.0 and read-only API v1/schema 1.3.0, V10 18-file source freeze, V11–V20 legacy technical contracts, formal V10/V20 blockers and unsigned source owner decisions.

**Security limits:** Composite tenant/site foreign keys can catch cross-tenant references *inside an enabled SQLite test connection*, not enforce live authentication/row authorization. No customer PII, network connection, SQL migration, persistent database, custody log, backup, encryption, production access or OT/CMMS write was added.

**Rollback:** Revert only V21 model, SQL design, verifier, tests, docs and CI steps. Because the preview exists solely in memory there is no database migration or production state to reverse. Human-reviewed schema proof remains pending.
