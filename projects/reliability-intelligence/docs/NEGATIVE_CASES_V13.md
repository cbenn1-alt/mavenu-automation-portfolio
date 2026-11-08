# V13 — Negative-case fixtures and feasibility checks

**Development standard:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**V13 objective:** Reject impossible, null, and out-of-range values.
**Required proof:** Negative-case fixtures.

**Delivery state:** Reproducible synthetic-only technical candidate. V10's formal phase promotion remains BLOCKED pending an actual human decision, and V11/V12 source field meaning and schemas are unsigned. No customer system or industrial threshold is validated.

The controlled negative-case corpus is fixtures/negative_cases_v13.json. The executable validator is scripts/verify_v13.py. The committed corpus is data rather than source code: each fixture identifies a previously fabricated data row, a bounded mutation, and the exact error expected. Mutations run only on deep copies, never on the immutable V10-pinned source files.

## Negative-case matrix

| Class | Cases | Detection |
|---|---:|---|
| Null | 8 | Required identifiers, timestamps, numeric values, arrays, provenance or reviewer labels cannot be JSON null |
| Out of range | 5 | Invented 0–240 hour and USD 0–1,000,000 bounds; evidence reference list cannot exceed three |
| Nonfinite | 3 | Explicit encoded NaN and positive/negative infinity test markers, decoded only within Python test memory |
| Impossible / referential | 13 | Gregorian-invalid dates/times, duplicate IDs, nonexistent asset/case references, duplicate evidence entries |
| **Total** | **29** | Every negative fixture must reject with its assigned fixed diagnostic code |

The nonfinite marker is an ordinary JSON string (nan, positive_infinity, negative_infinity) under a limited special operation—not a nonstandard NaN literal in a checked-in JSON file. No program execution, arbitrary path or customer data is permitted by the fixture executor.

## Valid boundary controls

Seven additional mutations MUST be accepted: downtime exactly 0 or 240 hours; invented repair cost exactly $0 or $1,000,000; calendar-valid February 29 in leap year 2028; an empty evidence-reference array; and exactly three distinct synthetic evidence references. These controls guard against the validator rejecting valid edge cases indiscriminately.

An empty evidence-reference array is not the same as JSON null. Zero hours or zero expense remains permitted by the unapproved V11 synthetic contract; it is not evidence about an actual plant's work-order rules.

## Check sequence

1. Recheck the V10 18-file source/configuration freeze and the outstanding blocked human promotion decision.
2. Validate the draft V11 dictionary and V12 strict schema against unchanged V5/V6 fabricated records.
3. Load and validate the V13 controlled fixture corpus, its exact 29 case identities, expected codes, 7 positive controls, and unsigned governance fields.
4. Validate all 34 original fabricated rows as positive controls.
5. Execute all negative mutations against isolated in-memory copies, requiring exact, sanitized errors.
6. Execute seven affirmative edge controls and require successful validation.
7. Write evidence/V13/negative_case_report.json with counts, error codes and absent approvals. The report contains no real customer source content.

Additional V13 controls include Gregorian calendar validity, finite numeric values, inclusive V11-defined numeric ranges, max/uniqueness of synthetic evidence references, uniqueness of asset/case/work-order IDs, and declared asset/reviewer/test-label foreign keys. The original V12 required fields and enums continue to be checked.

## Crucial interpretation

The numeric boundaries originate from a fictional example schema, not equipment design limits, safety standards, a production maintenance policy or a financial control. A nonexistent synthetic asset reference is impossible inside this fictional relational dataset, not a diagnosis that industrial hardware does not exist. Gregorian calendar checks do not authenticate a sensor clock or event provenance.

A successful CI result is not an approved source contract, human domain review, industrial security certification, production data validation, demonstrated uptime gain or measured return on investment. Named customer data stewards and technical owners remain unassigned. V10, V11 and V12 approval dependencies remain open.

## Reviewer gate

An independent engineer should inspect all 29 case definitions and seven accepted boundary values, verify the original fixture files were not touched, and reproduce the JSON evidence on the exact GitHub commit. A qualified source/data owner must independently approve real-world constraints if the product ever proceeds beyond synthetic research. Any claimed phase authorization or human signature blocks acceptance.

The V9 runtime and API remain unchanged at application version 0.9.0 and read-only API v1/schema 1.3.0. No CMMS, ERP, PLC, SCADA or OT connection is added.
