# V23 — Reversible schema migration path

**Controlling requirement:** Mavenu AI SaaS Platform Development Architecture V4, p.43.
**Exact objective:** Implement reversible schema migration path.
**Required proof:** Up/down migration evidence.

**Scope:** A technical, synthetic-only backfill. V24 had already been merged into the V22 branch before V23 was implemented, so this version adds a migration runner and verifies it can reproduce both earlier schema designs. It does **not** rewrite earlier commits or change V24's historical temporary-database bootstrap to invoke V23. Formal V10/V20 approval remains blocked and V21/V22/V23/V24 human reviews remain pending.

## Explicit versions and controlled transitions

| Version | Schema content | Tables | Triggers | Downgrade rules |
|---|---|---:|---:|---|
| 0 | New empty disposable database | 0 | 0 | None |
| 1 | V21 canonical synthetic entities | 10 | 0 | Down 1→0 only if all ten tables empty |
| 2 | V21 entities + V24 experimental transaction/event ledger | 13 | 6 | Down 2→1 only if all three ledger tables empty |

Migrations follow 0→1→2 forward, and 2→1→0 backward. Their identities use SQLite PRAGMA user_version 0/1/2. Each adjacent transition is one BEGIN IMMEDIATE / transactionally executed DDL statement sequence / PRAGMA user_version / COMMIT. On any failure the entire **adjacent step** rolls back, including its schema version marker. A request that crosses two versions commits each adjacent step independently; **the whole 0→2 or 2→0 request is not atomic**.

This is a versioned schema evolution implementation, not just dropping and recreating tables in test code. SQL statements are executed individually so SQLite's executescript implicit pre-commit behavior is avoided inside the migration transaction. Unrecognized versions, extra physical tables or triggers, mismatched primary/foreign keys, disabled FK checking, nested migrations and unsupported data paths fail closed.

## Preservation and rollback

- Empty 0→1→2→1→0 returns exactly to the original zero-table schema; 1→2→1 preserves the V21 schema fingerprint. A repeat of 0→2 produces the same design fingerprint.
- A **populated V21 snapshot of 120 fabricated rows** survives 1→2→1 bit-for-bit at the canonical V21 row digest. Downgrading that populated V21 snapshot to version 0 is refused.
- An existing **populated V24 batch of 134 synthetic rows** (120 V21 rows, 12 events, one batch, one receipt) refuses 2→1 because that would delete the ledger. Its commit receipt and schema remain unchanged after the attempted downgrade.
- Four injected exceptions during upgrade and downgrade (after three V21 tables created, after first ledger table created, after first V24 ledger table dropped, after fourth V21 table dropped) result in no schema changes after rollback and **after reopening the temporary database**. Retrying the same adjacent migration succeeds.
- All physical database files are placed under automatically deleted mavenu-v23-* temporary directories, with a specifically fixed file name. Nothing is migrated in a customer account.

## Files and evidence

- docs/data/MIGRATION_CONTRACT_V23.json: allowlisted version edges, source DDL, record-preservation rules, fixed fault cases, exact expected inventory and unsigned governance.
- scripts/migrate_v23.py: controlled SQLite temporary-file connections, version validation, SQL statement partitioning, transactionally executed adjacent up/down steps and fail-closed data-bearing downgrade checks.
- scripts/verify_v23.py: exact-head synthetic verification, including compatibility with already existing V24 ledger, V10 source freeze, V20 blocked gate and V22 draft.
- tests/test_migration_v23.py: **74 new tests** covering the complete version graph, physical table/trigger inventory, metadata and FK rules, nonempty data safeguards, four fault injections, version drift and forged approval.
- evidence/V23/up_down_migration_report.json, migration_failure_matrix.json and unsigned_migration_review.json: technical result, detailed replay and blank human sign-off request.

Expected full suite: **1,162 tests** (1,088 historical + 74 V23). Exact hosted CI logs determine observed success. The existing V8 84.5% application-source coverage minimum and V10 18-file frozen baseline are unchanged.

## Review and limitations

The term **up/down migration evidence** here means tested, reversible schema transitions **for fabricated SQLite databases**, not power-failure recovery, production upgrade/rollback certification, audit trails, customer source correctness or approval by a qualified DBA. The downgrade deliberately refuses destruction of real-like data. It does not implement archival of a populated ledger to permit data-bearing downs, online rolling upgrades, backups, distributed writes or migration compatibility across application versions.

V24's original temporary bootstrap remains separate. Converting it to V23 migration execution requires a distinct integration change, full V24 regression, a reviewer-tested rollback and a durable data preservation plan before release.

**Human gates:** Customer data rights, named data/OT owner approvals, signed V21/V22 schema and identity definitions, V10/V20 formal phase sign-off, and an independent V23 migration review are all outstanding. No production database access, live tenant authorization, CMMS/SCADA/OT writes, actual plant data or proven savings are supplied.
