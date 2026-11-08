# V11 change record — data correctness exploration

**Objective:** Declare data types, meaning, and ownership.
**Proof target:** Approved source/field dictionary; human signatures remain outstanding.

### Added
- Four-dataset, 21-field JSON source/field dictionary recording synthetic fixture types, units, canonical IDs, relationships, meanings, allowed values and proposed stewardship.
- Standalone non-destructive verifier that checks the existing V10 18-file freeze and blocked formal decision before checking all declared fixture rows.
- 34 negative/governance regression tests; CI evidence output in ignored evidence/V11.
- Human review/approval requirements, risk caveats and setup instructions.

### Unchanged
- V9 production Python modules, static CSS, API v1/schema 1.3.0, runtime version 0.9.0.
- V5 fixtures, scripted fictional review data and V8/V9/V10 evidence lineage.
- No customer data access, real human decisions, external connector, write route or predictive model.

### Risk and rollback
Fields are hypotheses based on invented JSON, not verified customer definitions. Cost/downtime values are examples, not savings. Proposed owners are unassigned. Rollback V11 documentation/test additions if needed; frozen V9 runtime requires no migration. Any intentional change to a V10 pinned source or fixture requires a separately reviewed new baseline rather than editing Git hash values in place.
