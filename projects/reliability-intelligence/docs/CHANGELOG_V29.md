# V29 change, security delta and rollback

**Added:** Independent three-directory disposable SQLite restore harness with read-only preflight and online backup, source logical and physical corruption detection, missing/damaged backup refusal, post-copy injected failure cleanup, timed integrity/reopen verification, 72 regression tests and three unsigned proof reports.

**Preserved:** V9 frozen application/read-only API, V10 source hashes, V21/V22 schema keys, V23 migrations, V24/V24.1 transaction integrity, V25 synthetic index prototype, V26 unratified tenant isolation, V27 simulated backup telemetry and V28 retention/legal-hold sidecar. V29 does not modify or restore the V28 sidecar.

**Security delta:** Refuses invalid backups *before creating targets*, rejects already-present target paths, validates checksum/receipt and schema after copy and removes partial targets after failure. All files are temporary. This is not production authentication, disaster recovery authorization, backup encryption, external attestation, RPO/RTO certification, or actual data protection.

**Rollback:** Revert only V29 files and workflow integration; all disposable tests are already cleaned, with no real customer data, persistent backup or recovery state to migrate.
