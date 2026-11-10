# V28 change and rollback

Added five-table disposable SQLite lifecycle sidecar, 14/30-day synthetic archive and 90-day purge thresholds, two held objects, scoped fake hold release, logical deletion with hashed tombstones, audit hash chain plus ordinary-write blocking triggers, two fault injections, idempotent replay, 102 regression tests and three evidence JSON reports.

Preserved V9 frozen application/API, V10 fixtures, V21–V26 schemas/migrations/isolation, V27 simulated backups and unsigned governance. V28 does not alter real customer records, production archives or backups. SQLite DELETE is not secure erasure; audit hashes are not external attestations.

Rollback means reverting V28-only files and workflow. Test data exists only in automatically deleted local files.
