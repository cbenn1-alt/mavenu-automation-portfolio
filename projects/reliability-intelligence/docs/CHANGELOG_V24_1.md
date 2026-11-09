# V24.1 change, security delta and rollback

**Modified:** scripts/persist_v24.py imports migrate_v23, replaces raw executescript bootstrap with V23 migration-to-version-2, supports recovery from an empty version-1 schema, rejects nonempty V1 and any V2 rebootstrap, and demands user_version=2 during integrity validation.

**Added:** migration integration contract, verify_v24_1.py, 54 integration regression tests, eight-scenario report, reviewer packet and clean-archive CI evidence.

**Unchanged:** V9 frozen runtime 0.9.0 and read-only API v1/schema 1.3.0, synthetic fixtures, V10 18-file freeze, existing V23 migrator and V24 transaction/receipt algorithms, historical V24 contract, and all pending governance approvals.

**Limits:** V0→1 and V1→2 migrations commit separately; failure between steps can leave empty V1. No customer records, production migration, multi-tenant authorization, disaster recovery, backup or OT/CMMS write is added.

**Rollback:** Revert V24.1 files/integration changes. All databases are temporary synthetic test instances; no production migration or customer state needs reversal.
