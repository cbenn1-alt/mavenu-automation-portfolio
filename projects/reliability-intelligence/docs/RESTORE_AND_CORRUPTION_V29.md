# V29 — Timed restore and corruption-response drill

**Controlling standard:** Mavenu AI SaaS Platform Development Architecture V4, page 43.
**Exact objective:** Execute restore and corruption response drill.
**Required proof:** Timed restore evidence.
**Release state:** synthetic-only technical candidate. V10/V20 formal approval blocked and V21–V29 independent human reviews pending.

## 1. Scope of recovery

V29 uses V23/V24.1 SQLite schema version 2 and the V24 134-row synthetic transaction: 120 fictional entity rows, 12 fabricated events, one batch and one commit receipt. A source, backup and target are opened in **three separate automatically deleted temporary directories**. The experiment uses Python's sqlite3.Connection.backup, read-only backup preflight and independent target reopen. Every source, backup and target file is deleted before the test exits.

V27's successful backup trials were temporary and retained no recoverable copy. V29 creates its own temporary snapshots. It does **not** create persistent/offsite backups, an unattended scheduler, a real recovery center, actual customer-data recovery or production disaster-recovery authorization. The V28 legal-hold/retention sidecar is explicitly outside this restore scope.

## 2. Timed restore evidence

Three successful scenarios are executed:
- **Intact source and backup:** copy verified invented transaction to a new target.
- **Logical active-source corruption:** mutate a fabricated maintenance record after taking a good backup; V24 receipt mismatch detects source corruption; restore the good backup into a separate target.
- **Physical active-source corruption:** deliberately invalidate the first 16 bytes of a disposable SQLite source after a good snapshot; opening its metadata fails; restore the untouched backup.

Each scenario records measured milliseconds using time.perf_counter_ns: backup preflight, restore copy, integrity/reopen verification and total. An absolute **10,000 ms upper limit** applies as a permissive CI guardrail, not an operational SLA. There is one sample per scenario; no statistical tail latency, concurrent workload, or production system failover is measured.

The restored target must pass SQLite PRAGMA integrity_check, PRAGMA foreign_key_check, V23 schema version 2 and structural checks, complete 134-row inventory, 12-event hash chain, and the original V24 commit receipt/manifest, then reopen independently. No post-snapshot synthetic writes occur, so zero example data-loss rows is a fixture property—not a proven customer RPO.

## 3. Corruption-response and failure cases

| Case | Required result |
|---|---|
| Missing backup | Refuse before a target is created |
| Backup record tampered after snapshot | Detect V24 receipt mismatch, refuse |
| Backup physical header corrupted | Refuse unreadable backup |
| Injected exception after restore copy | Delete partial/unaccepted target |

All failures must use stable diagnostic codes and have zero accepted restore rows. Restore never overwrites the active source or an existing target. Corrupting the active source does not damage a separate valid backup. This tests bounded SQLite corruption response, NOT actual media failure, power-loss or infrastructure failover.

## 4. Evidence and acceptance

- docs/data/RESTORE_DRILL_CONTRACT_V29.json — exact synthetic restore scope, expected cases, fixed time guardrail and unsigned production decisions.
- scripts/recovery_v29.py — read-only backup preflight, isolated SQLite restore, injected corruption, target re-open and verified cleanup.
- scripts/verify_v29.py — prior V27/V28 technical evidence, V10 frozen source, V20 blocked signoff, SHA-256 source integrity, technical reports.
- tests/test_recovery_v29.py — **72 new tests**, expected complete suite 1,643 including 1,571 inherited; exact-head GitHub Actions controls the result.
- evidence/V29/timed_restore_evidence.json — time measurements and validated recovered row counts.
- evidence/V29/corruption_response_matrix.json — refusal classifications and damaged active-source recoveries.
- evidence/V29/unsigned_recovery_review.json — human acceptance not recorded.

Historical V8 combined application coverage floor 84.5% and V10 frozen 18-file source remain mandatory.

## 5. Human production readiness

The customer/controller and DBA must establish a lawful right to restore actual source records and their backups; approved encryption/key and offsite copies; isolation, RLS and recovery credentials; tenant-specific retention, holds and deletion continuity (V28); workload-dependent RTO and RPO with writes occurring during failover; incident alerts and recovery playbook; and an independently reviewed recovery-site test. V10/V20 formal gates and V21–V29 approvals remain unsigned.

**Technical success is not proof of actual disaster recovery, production RTO/RPO, or customer data authorization.**
