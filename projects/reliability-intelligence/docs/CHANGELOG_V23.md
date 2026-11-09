# V23 change and security delta

**Added:** Explicit versioned SQLite up/down schema migrations (0,1,2), contract, transactional DDL with version markers, rejection of destructive nonempty downgrades, four fault-injection rollback scenarios, 74 regression tests, reproducible evidence reports and a reviewer packet.

**Retained:** V9 0.9.0 read-only runtime and API v1/schema 1.3.0; V10 frozen 18-file source; V11–V22 fabricated technical source and contracts; V24's already-merged temporary bootstrap and 1,088 prior regression tests; blocked/pending human gate states.

**Security delta:** The code constrains writes to named files inside newly created temporary test folders and prohibits unexpected physical schema/metadata. It does not implement or prove actual customer tenant authorization, encryption, disaster recovery, backup, live migration, real OT/CMMS data, power-loss durability or production database access. SQLite metadata and hashes provide technical replay evidence, not external signatures.

**Rollback:** Revert V23-only files/workflow changes. V24's existing temporary bootstrap remains unchanged and is not a migration. Further integration requires an independent PR with explicit tests, source owner review and a migration readiness decision.
