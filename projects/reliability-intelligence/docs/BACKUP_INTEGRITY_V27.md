# V27 — Scheduled backups and integrity checks

**Architecture source:** Mavenu AI SaaS Platform Development Architecture V4, Storage Data Model phase V21–V30, page 43.
**Exact V27 objective:** Schedule backups and integrity checks.
**Required proof:** Backup success telemetry.

**Status:** Synthetic-only technical backup prototype, human approval **PENDING**. This release does **not** start a real scheduler, create a retained backup, authorize customer data, certify power-loss behavior, or establish production disaster recovery. V10 formal phase promotion and V20 data-quality signoff are **BLOCKED**. V21–V26 human reviews are unsigned.

## Proposed schedule and state model

**Schedule design:** daily 02:15 UTC, expressed as cron 15 2 * * *, with a 30-minute grace period. The test harness evaluates supplied UTC instants; it does **not** install a GitHub Actions schedule, cron daemon, automation, background worker or production service.

| State | Meaning in test-only policy |
|---|---|
| NOT_STARTED | Timestamp before policy anchor |
| CURRENT | Latest due slot has a recorded synthetic success |
| DUE | Latest slot is not complete and its 30-minute grace period has not elapsed |
| MISSED | Slot remains incomplete after grace interval |

The UTC policy anchor is November 8, 2026, 02:15 UTC. Six deterministic schedule examples and eight additional boundary probes cover current, due, missed, and not-started cases. Real schedule execution would require an actual scheduler, approved secrets, incident response, retention and monitoring, and an owner-approved operational rollout.

## Synthetic backup mechanism

1. Open a disposable SQLite V23/V24.1 version-2 database in an automatically deleted mavenu-v24-* temporary folder. Bootstrap via V23 migration engine.
2. Commit the existing V24 fixture — **120 fabricated entity rows, 12 invented case events, one import batch and one integrity receipt; 134 rows total** — with no external data source.
3. Validate the source V24 receipt, schema version, foreign keys, SQLite integrity and event hash chain before copying.
4. Create a separate disposable destination SQLite database in a **different** automatic-cleanup directory. Call sqlite3.Connection.backup to copy the live database rather than copying an open database file as raw bytes.
5. Validate the copied database independently against source schema/manifest, full row inventory, event chain, commit receipt and foreign keys. Close and **reopen** the backup using a new connection and verify again.
6. Calculate file byte length and SHA-256 only after the destination handle is closed; record positive telemetry for a verified copy and no false success on partial/missing/tampered copies.
7. Close connections and remove both temporary directories/files at the end of every scenario.

No copy is retained after the test. The file hash is a local integrity diagnostic, **not** an externally authenticated or tamper-proof attestation. The code does not establish backup encryption, cloud/offsite replication, recovery objectives, independently restored customer applications or durable retention.

## Backup telemetry proof

The verifier simulates two successful due-slot backups and three expected failures:

| Test case | Required result |
|---|---|
| Synthetic due-slot A (2026-11-09 02:20 UTC) | SUCCESS, 134-row copy verified and reopened |
| Synthetic due-slot B (2026-11-10 02:20 UTC) | SUCCESS, same deterministic receipt and full integrity |
| Inject before_copy error | FAILED, no accepted copied rows |
| Tamper with copy after backup | FAILED, copied receipt/source digest inconsistency detected |
| Modify source after commit | FAILED, pre-copy source integrity rejection |

Each telemetry record includes intended due time, attempt time, scenario, status, fixed non-sensitive failure code, measured elapsed time, verified row count, file SHA-256 (only for a successful closed copy), receipt identity, bytes and deletion confirmations. Failures never report integrity verified or completed backup rows.

This telemetry is **simulated**. Actual success events from an unattended schedule are zero.

## V27 deliverables

- docs/data/BACKUP_SCHEDULE_V27.json — exact cron design, policy and UTC anchor, immutable test count expectations, simulated states, failure cases, review gates and missing customer rights.
- scripts/backup_v27.py — UTC schedule evaluator, SQLite online backup, source/backup verification, failure telemetry, tamper and before-copy errors, temporary cleanup.
- scripts/verify_v27.py — V10 frozen-source and V20 blocked-gate checks, V26 unsigned isolation evidence, fixture SHA-256 before/after, three JSON verification reports.
- tests/test_backup_v27.py — **81 new tests**: 70 direct and 11 generated boundary/negative checks. Expected cumulative suite: **1,469 tests**, subject to exact-head GitHub Actions.
- evidence/V27/backup_success_telemetry.json — validated, successful-copy telemetry.
- evidence/V27/failure_and_schedule_matrix.json — three negative scenarios plus UTC schedule matrix.
- evidence/V27/unsigned_backup_operations_review.json — missing owner, security and operations approval.

## Release dependencies

A **production backup design** requires named legal data owner, actual data source license, qualified DBA/security review, encryption/key ownership, scheduled job operation and alerting, offsite/durable copies, approved retention/deletion (V28), independent restore testing and measured RPO/RTO (V29), plus explicit tenant-scope isolation (V26). Customer contracts and those human approvals do not currently exist. Technical PASS cannot substitute for them.

**V27 required proof is backup-success telemetry for fabricated ephemeral data only, not production backup readiness.**
