# V28 — Retention, Deletion and Archives

**Architecture:** Mavenu AI SaaS Platform Development Architecture V4, p.43.
**Objective:** Enforce retention, deletion and archives.
**Proof:** Retention-policy tests.

**State:** synthetic technical candidate, human approval pending. V10 and V20 phase signoffs are blocked; V21–V28 owner/legal/security reviews are unsigned. No production or customer data rights are granted.

## Retention policy and isolated scope

V28 creates an automatically deleted SQLite sidecar, mavenu-v28-*/v28_lifecycle.sqlite3, based only on a fabricated V26 dataset. The original V26 source, V23/V24.1 database schema, V27 synthetic backups, frozen V10 fixtures and V9 runtime remain unchanged.

The sidecar has 24 synthetic objects: 2 fake tenants × 2 sites × 3 repeated case IDs × 2 data classes. It uses five tables: active_record, archive_record, legal_hold, purge_tombstone and audit_event. Audit events are chained by SHA-256 hashes and two SQL triggers block ordinary updates/deletes. Such hashes are not independent authenticated custody.

| Synthetic data class | Archive at age | Purge at age |
|---|---:|---:|
| Case summaries | 30 days | 90 days |
| Evidence references | 14 days | 90 days |

Fixture ages are artificially assigned 5, 40 and 120 days as of November 10, 2026 at 12:00 UTC. These periods are examples, not real contractual or regulatory retention policies.

## Archive, deletion and hold behavior

A policy run moves 40-day objects to a separate archive table and deletes 120-day unheld objects from the active/archive tables. Only opaque SHA-256 object digests, class and test timestamp are written to tombstones. Two synthetic legal holds prevent a 120-day object from being archived or purged. Held objects require a separately invoked, strictly scoped but NOT authenticated test-reviewer release before the next eligible purge.

All actions within a lifecycle run execute as one BEGIN IMMEDIATE/COMMIT transaction; faults injected after the first archive or first purge roll the entire batch back, including its audit entries. Replay is idempotent.

| Point in lifecycle | Active | Archived | Purged | Holds | Audit events |
|---|---:|---:|---:|---:|---:|
| Before holds | 24 | 0 | 0 | 0 | 0 |
| With holds after enforcement | 10 | 8 | 6 | 2 | 16 |
| Repeated enforcement | 10 | 8 | 6 | 2 | 16 |
| After simulated release and rerun | 8 | 8 | 8 | 0 | 20 |

Counts are limited to the disposable V28 sidecar. No original source or V27 backup is deleted. SQLite DELETE does not guarantee secure erasure from journals, pages, replicas or real backups. Hash-only tombstones may still be linkable.

## Files and proof

- docs/data/RETENTION_POLICY_V28.json — exact fixed candidate policy and unsigned decision.
- scripts/retention_v28.py — disposable lifecycle store, transactions, scoped holds, archive, purge, hash tombstones and audit.
- scripts/verify_v28.py — frozen-source checks, blocked prior phase gates, replay and signed-off-state exclusion.
- tests/test_retention_v28.py — **102 added tests**: 78 direct and 24 record/scope/class checks.
- evidence/V28/retention_policy_test_report.json; archive_delete_hold_matrix.json; unsigned_retention_review.json.

Expected full suite **1,571**, including 1,469 inherited; actual GitHub CI is authoritative. Existing 84.5% application source coverage floor and V10 18-file freeze remain in force.

**Formal gate:** Customer controller and legal review of actual retention and legal holds, authenticated authorization and dual-control release, multi-copy deletion including backup and exports, secure erase controls, trustworthy audit, tenant isolation, approved scheduler and prior V10/V20/V21–V27 gates. None is certified by synthetic CI.
