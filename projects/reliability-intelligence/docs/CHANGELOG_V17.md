# V17 change and security delta

**Added:** 25 precomputed synthetic expected-output references covering summary totals, six per-asset aggregates and twelve ordered case-history rows; pure Decimal calculation/comparison service; 59 tests; two evidence reports and reviewer documentation.

**Unchanged:** V9 runtime 0.9.0 and read-only API v1/schema 1.3.0, V10 18-file freeze, V11/V12 draft data contracts, V13 negative cases, V14 ephemeral idempotency, V15 normalization and V16 reconstructed lineage.

**Risk controls:** No source records changed, customer input, true reliability labels, financial savings/ROI claim, forecast, new API, production persistence, credentials, customer approval or industrial writes. Money and time are synthetic Decimal sums. SHA-256 digests are reproducibility checks, not approvals.

**Rollback:** Revert V17 fixtures/scripts/tests/docs/CI evidence step. No migration or customer state exists. Domain sign-off and V10 formal phase authorization remain pending.
