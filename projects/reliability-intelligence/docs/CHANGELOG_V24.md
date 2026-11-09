# V24 change record, security delta and rollback

**Added:** docs/data/PERSISTENCE_CONTRACT_V24.json; scripts/persist_v24.py and verify_v24.py; 82 transactional persistence regression tests; synthetic SQLite file-backed bootstrap confined to automatically deleted TemporaryDirectory, 120 staged validated rows, 12 invented events, one batch and one integrity receipt; SHA-256 event chain, V22 uniqueness/links, idempotent replay, two exception-based rollback scenarios, reopen check and six append-only SQL triggers. Full V8–V22 plus V24 CI evidence.

**Not present:** V23 reversible schema migration. The V24 experiment does not supply it, and the human review package reports it missing.

**Preserved:** V9 application runtime 0.9.0, read-only API v1/schema 1.3.0, V10 18-file frozen source, V11–V22 technical releases and all blocked/unsigned approval records.

**Security/limitations:** No production database, customer data/PII, real tenant auth/RLS, backup, HA, audited durability, true process-crash or power-loss proof, CMMS/ERP/OT/SCADA write or real-world saved expense. Receipt hashes are integrity tests, not externally trusted signatures. V24 database files vanish with test context.

**Rollback:** Revert V24-only code/tests/docs/workflow additions. No production migration or customer state needs reversal; temporary test files are automatically removed. Formal release requires human review and outstanding V10/V20/V23 prerequisites.
