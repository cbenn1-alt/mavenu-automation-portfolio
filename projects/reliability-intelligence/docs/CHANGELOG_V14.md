# V14 change record and security delta

**Objective:** Enforce duplicates and idempotency rules. **Proof:** Repeated-ingest comparison.

**Added:** docs/data/IDEMPOTENCY_CONTRACT_V14.json, fixtures/repeated_ingest_v14.json, scripts/ingest_v14.py, scripts/verify_v14.py, tests/test_idempotency_v14.py, explanatory runbook and six-part release packet. GitHub CI executes V14 after V8–V13 and uploads evidence/V14/repeated_ingest_comparison.json.

**Behavior:** Canonical SHA-256 snapshot, in-process exact-repeat suppression, hard-fail conflicting identity or secondary work-order reference, atomic all-or-none staged batches, valid parent-first partitioned ingestion, in-memory rollback proof.

**Unchanged:** Pinned V9 application, V10 18-file source freeze, V11 unsigned dictionary, V12 draft schema, V13 negative fixtures, all original source rows, loopback read-only UI/API.

**Risks:** No cross-process persistence, concurrency, production event IDs, real data rights, CMMS or OT integration. Synthetic numeric limits and uniqueness assumptions are not industrial/business acceptance rules. No falsely claimed sign-off.

**Rollback:** Revert V14 additions and workflow changes. Existing application/fixture files require no migration.
