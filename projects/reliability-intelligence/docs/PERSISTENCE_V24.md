# V24 — Persist validated records and events

**Controlled source:** Mavenu AI SaaS Platform Development Architecture V4, p.43.
**Exact V24 objective:** Persist validated records and events.
**Required proof:** Transactional integrity tests.

**Development state:** technical candidate on top of V22. There is NO V23 branch or reviewed reversible migration path in the connected GitHub repository. Consequently the V24 design boots a **new empty disposable database** for test only; it is explicitly NOT an implementation of V23, a database migration, an approved production store or an authorized formal release. Prior V10 phase promotion, V20 data-quality approval, and V21/V22 human schema/identity review remain blocked/pending.

## Controlled temporary persistence architecture

V24 extends the V21 ten-entity schema with exactly three experimental SQLite test tables:
- v24_import_batch: one fixed fictional batch ID, source-manifest SHA-256, expected row totals.
- v24_case_event: twelve fabricated case-persistence events (case ID, referenced asset, stable sequence, payload SHA-256, previous chain hash and current hash).
- v24_commit_receipt: one manifest, snapshot digest, event chain tip and deterministic receipt SHA-256.

A fresh temporary file under a newly created directory prefixed mavenu-v24- is bootstrapped with the V21 DDL plus V24 ledger tables. SQLite foreign keys are ON, journal mode is DELETE and synchronous is FULL. **No existing database is migrated**, and there is no background service or customer source connection.

Before any disk write, V21 builds a validated **120-row staging snapshot in SQLite :memory:** using the committed fabricated source files and reconstructed V16 lineage. V22 identity checks require 13 scoped uniqueness views and nine parent-child links to be valid. The synthetic source fingerprint is fixed and captured.

Within ONE BEGIN IMMEDIATE / COMMIT transaction, V24 copies the 120 validated rows from staging, inserts one import-batch entry, twelve case events and one commit receipt — **134 inserted rows in total**. Any injected exception during copying/event creation rolls back all rows. Replay of an existing matching batch verifies all stored rows, linked keys, event hashes, the source digest and the receipt before responding ALREADY_COMMITTED with zero new rows; mismatching source identity fails closed.

Checks on each database opening and review:
- V21 original primary-key/foreign-key definitions, V22 identity uniqueness and all nine parent-child links;
- foreign_key_check, SQLite integrity_check, exact 120-row base, 12-event + batch + receipt inventory;
- complete canonical snapshot SHA-256, twelve case-to-asset event payload hashes, ordered event hash chain and final receipt digest;
- 163,800 fictional downtime seconds and 1,273,500 illustrative repair-cost cents, not actual Minn-Dak operations.

The three ledger tables have six SQLite BEFORE UPDATE/DELETE triggers. These test append-only behavior for committed synthetic entries. SHA-256 changes are detectable but **do not prove trusted cryptographic attestations or protection against a database administrator with schema privileges**.

## Transactional negative tests

The tests inject failure after all 120 records are copied, and separately after the fourth fabricated event; each confirms no committed rows, closes/reopens the database and retries successfully. A normal scenario confirms commit, reopen, same receipt, and idempotent replay. Additional negative tests reject duplicate event identity, missing parent links, unauthorized file paths, tampering with case costs that remain numerically valid, altered source manifest, invalid journaling/authorization claims, and mutation of append-only event and receipt rows.

These tests exercise **application exceptions**, NOT actual power-loss, disk corruption or cross-process crash/failover. SQLite synchronous=FULL is a configuration observation, not an external platform durability certification. No retained backup or disaster recovery exists. V27–V29 cover later backup/restore disciplines.

## Reproducibility artifacts

- docs/data/PERSISTENCE_CONTRACT_V24.json: limits, counters, missing V23 prerequisite and unsigned owner fields.
- scripts/persist_v24.py: temporary file-backed SQLite bootstrap, staged synthetic data, atomic insertion, commit receipts, checksum-chain verification, idempotent retry, fault injection and reopened connection validation.
- scripts/verify_v24.py: checks V10/V20/V21/V22 governance state and three transaction scenarios, writes evidence.
- tests/test_persistence_v24.py: 82 additional technical tests; expected full suite **1,088** (1,006 inherited), subject to actual GitHub Actions result.
- evidence/V24/transactional_integrity_report.json: reproducible counts, SHA-256 and blocked approval state.
- evidence/V24/rollback_reopen_matrix.json: normal, fail-after-record and fail-after-four-events scenarios.
- evidence/V24/unsigned_persistence_review.json: unsigned human decision request.

This temporary database is deleted with the test directory at the end of each run. No source file is modified. The V9 application runtime 0.9.0 and read-only API v1/schema 1.3.0 remain unchanged.

## Human release gates and omissions

A V23 reversible up/down migration path must be implemented and tested before relying on schema upgrades. Separately, qualified data/system architects and customer security reviewers must validate real entity semantics, transactional source-of-truth, domain event models, timestamp/clock and site identity rules, recovery objectives, storage permissions, encryption and tenant access, concurrency and crash-safety in the intended production environment.

CI green and synthetic transaction receipts **do not constitute V24 human acceptance or authorization to persist actual customer data**. Formal approval of V10/V20 and V21/V22 reviews is still required. There are no real maintenance work orders, operator activity, customer identities, OT/SCADA/CMMS writes or measured financial returns.
