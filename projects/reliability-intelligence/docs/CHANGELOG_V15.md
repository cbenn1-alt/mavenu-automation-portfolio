# V15 change and security-delta record

Added conversion_reference_v15.json (27 accepted and 24 rejected references), normalize_v15.py (standard-library Decimal/UTC/locale conversion), verify_v15.py (test and source-immutability evidence), 81 tests, reviewer instructions and clean-snapshot CI evidence.

Retained the pinned V9 application (0.9.0), five read-only API v1 routes, 18-file V10 frozen source, V11 unsigned dictionary, V12 strict contract, V13 invalid fixtures and V14 in-memory idempotency simulator.

Security scope: no live customer data, external network, timezone/FX API, persistence, credential, OT/SCADA/CMMS/ERP integration, real work order or industrial action. The standalone normalizer rejects unsupported numeric/time/locale formats rather than inferring unsafe values.

Rollback: revert V15 scripts/tests/fixtures/docs and workflow changes; no customer state or database migration exists. No human reviewer or customer owner has signed the V15 conversion semantics.
