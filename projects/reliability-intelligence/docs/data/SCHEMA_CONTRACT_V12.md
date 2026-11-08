# V12 Strict Schema Contract — synthetic only

**Source standard:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**Objective:** Validate required fields and allowed values.
**Required proof:** Schema validation test report.

**Status: technically checkable draft. NOT APPROVED.** V10 promotion remains recommended BLOCKED pending a signed decision. V11 source/field dictionary is unsigned and no customer data owner has authorized a real system of record.

The JSON contract in docs/data/SCHEMA_CONTRACT_V12.json is derived from the V11 proposed field dictionary and applies only to fabricated fixtures. It requires every declared field, rejects any extra field, validates exact types, allowed enumerations, ID formats and element patterns.

| Dataset | Rows | Required fields per row | Origin |
|---|---:|---:|---|
| asset_records | 6 | 4 | Invented assets |
| case_records | 12 | 10 | Invented maintenance cases |
| scripted_review_entries | 4 | 4 | Fictional reviewer roles; no human actions |
| seeded_reference_labels | 12 | 3 | Author-seeded test labels; not independent ground truth |

The contract covers 21 field definitions and 34 fabricated rows, with 196 total required-field occurrences. Existing failure codes and source values are *test vocabulary*, not vetted industrial terminology. A SYN-prefixed reference is not actual evidence, a dispatched work order or authenticated reviewer identity.

The V12 verifier proves the prior V10 frozen source is intact, then checks V11 schema consistency, exact V12 field inventories, allowed values, positive records and **16 negative in-memory mutations**. Negative cases include missing fields, extra/PII-like columns, disallowed failure codes, false synthetic flags, boolean-as-number values, wrong IDs, unrecognized evidence codes, fictitious reviewer decisions and seeded-label leakage controls. No fixture file is modified.

The output is the reproducible evidence/V12/schema_validation_report.json. It records counts and rejection codes, not customer source values. This report is **not** a signed schema approval. Real owner assignments, allowed values, asset hierarchy, timestamps, currency accounting and data rights require independent approval.

V13 separately tests impossible, null and out-of-range values in adverse-case fixtures. Passing V12 does not prove reliable customer input, industrial safety or economic benefit.
