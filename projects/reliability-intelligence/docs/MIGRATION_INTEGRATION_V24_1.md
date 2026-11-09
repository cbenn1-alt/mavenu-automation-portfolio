# V24.1 — V23 schema migrations integrated with V24 persistence

**Source:** Mavenu AI SaaS Platform Development Architecture V4, page 43.
**Combined requirements:** V23 reversible up/down migrations and V24 validated transactional record/event persistence.
**Status:** Technical candidate, synthetic-only, independent human review pending.

## Change from V24
The original V24 bootstrap directly ran V21 and ledger SQL through executescript. It did not use V23, which was implemented later. Both V23 and V24 have since been merged into the V22 branch. V24.1 changes scripts/persist_v24.py bootstrap to call migrate_v23.validate_version followed by migrate_v23.migrate_to(db,2), enforcing PRAGMA user_version 2 in check_structure. This is the active integration; historical V24 contracts and release records are preserved.

| Starting database | V24.1 behavior |
|---|---|
| Empty V0 | V23 migration 0→1 then 1→2; 13 tables, 6 triggers |
| Empty V1 | Resume version 1→2 |
| Populated V1 | Refuse bootstrap, preserve all source rows |
| Empty or populated V2 | Refuse duplicate bootstrap; use verified V24 commit/replay API |
| Unknown version, unexpected tables, non-test file | Fail closed, no repair or data changes |
| Interrupted 1→2 DDL | Atomic adjacent rollback to V1, reopen and resume if empty |

**Atomicity limitation:** V23 adjacent migrations individually use BEGIN IMMEDIATE/COMMIT. A multi-step 0→2 request is not one atomic transaction; failure between steps may leave a correct empty V1 schema.

## Preserved V24 data guarantees
V24 still validates the fabricated dataset in an in-memory V21/V22 staging database, then commits **120 canonical synthetic entity rows, 12 case events, one batch and one commit receipt** (134 rows) in a single data transaction. It verifies event hashes, SHA-256 receipts, cross-table links, reopening and exact-source retry with zero duplicate rows. Failures after record copy or the fourth event roll back all data rows.

**New safety rule:** No manually built but unversioned 13-table storage can be silently treated as migrated V24 storage.

## Technical proof
- docs/data/MIGRATION_INTEGRATION_V24_1.json — amendment with exact startup/approval rules.
- scripts/verify_v24_1.py — eight integration scenarios, current V23/V24 technical evidence, V10 frozen fixture validation, V20 blocked sign-off and unmodified fixture checks.
- tests/test_v24_1_migration_integration.py — **54 new regression tests**, expected complete suite **1,216** (1,162 inherited), subject to actual exact-head CI.
- evidence/V24_1/migration_persistence_integration.json — machine-readable technical result.
- evidence/V24_1/bootstrap_and_recovery_matrix.json — eight startup and failure outcomes.
- evidence/V24_1/unsigned_v24_1_review.json — unsigned human review packet.

The eight scenarios cover empty V0 initialization, empty V1 resume, failed V1→V2 upgrade and retry, refusal of populated V1, refusal of empty V2 rebootstrap, unknown version, unexpected physical schema, and refusal of a populated V2 rebootstrap preserving its integrity receipt.

## Release exclusions and gates
The database exists only in automatically deleted temporary SQLite directories. No production deployment, live customer records, approved tenant authorization, power-loss testing, backup/restore certification, industrial-control write, real operations or savings claim is added. V10 formal phase promotion and V20 data-quality sign-off remain blocked. V21/V22 source and V23/V24/V24.1 human reviews are pending. A qualified DBA/architect/security reviewer must approve any real-world migration architecture, source rights, backup/rollback and tenant isolation.

**V24.1's verified migration status supersedes the original V24 release's historical missing-migration statement; it does not retroactively change what V24 originally delivered.**
