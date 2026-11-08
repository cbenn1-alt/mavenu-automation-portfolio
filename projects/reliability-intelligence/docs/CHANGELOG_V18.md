# V18 change and security delta

**Added:** Synthetic fixed-clock freshness checks; adverse-case fixture with 44 missing/stale/malformed records and five valid boundary controls; strict JSON byte parser, standalone V18 verifier, 74 regression tests and evidence report.

**Unchanged:** V9 runtime 0.9.0 and API v1/schema 1.3.0, V10 18-file source freeze, V11/V12 unsigned schemas, and V13–V17 simulated correctness code. No production interface, customer data, model or industrial action.

**Security:** Duplicate JSON members and nonstandard NaN rejected; unknown source documents/fields rejected; all mutation is in-memory and error codes exclude input values. Synthetic timestamp window is NOT an approved customer freshness threshold. Revert V18-only additions to roll back; no migration needed.

**Gate:** Technical evidence requires independent human review. V10 formal promotion remains blocked pending authorization and source/data-owner approval.
