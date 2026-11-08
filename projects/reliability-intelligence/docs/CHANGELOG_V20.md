# V20 change record and security delta

Added DATA_QUALITY_BASELINE_V20.json, V20_SIGNOFF.json, gate_v20.py, verify_v20.py, 65 tests, eleven-report evidence manifest, blocked human decision packet, documentation and V8–V20 clean-archive CI check.

Preserved frozen V9 runtime 0.9.0 and read-only API v1/schema 1.3.0, V10 18-file source freeze, V11–V19 technical sources and all signed/unsigned governance boundaries. No customer records, credentials, connectors, persistent database, production service or industrial writes.

The V20 validator fails closed if signatures, phase approval, production permission, evidence inventory, source coverage or critical upstream proof states are misrepresented. Hashes are not signatures.

Rollback removes V20-only files and workflow step. No data migration or customer system restoration exists. Formally required data-quality human acceptance remains outstanding.
