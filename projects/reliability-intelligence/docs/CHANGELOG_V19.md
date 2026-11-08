# V19 change, security delta and rollback

**Added:** A second synthetic calculation pathway using SQLite in-memory SQL, integer elapsed seconds and USD cents; exact cross-check to V17's authored expected fixture; 16 discrepancy/invalid-input controls; 77 V19 tests; independent-computation summary/detail evidence files; V8–V19 clean-archive GitHub Actions verification.

**Unchanged:** V9 0.9.0 runtime and read-only API v1/schema 1.3.0; V10 18-file freeze; V11/V12 unsigned contracts; V13–V18 artificial fixtures and technical correctness controls.

**Exclusions:** No persisted database, network listener, real customer records/PII, plant operational denominator, CMMS/ERP/OT/SCADA command, predictive scoring, audited cost, realized savings or human sign-off. Two code paths sharing one fictional source are not independent ground truth.

**Rollback:** Revert V19-only files and workflow changes. No migration/recovery of customer state is required. Technical approval does not override the V10 blocked phase decision.
