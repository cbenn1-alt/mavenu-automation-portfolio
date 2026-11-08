# V11 candidate source/field dictionary — synthetic-only, NOT APPROVED

**Development standard:** V11–V20 Data Correctness, V11 *Declare data types, meaning, and ownership*. **Required proof:** *Approved source/field dictionary*. The JSON dictionary is complete for the current fabricated fixtures and mechanically checked, but **the approval requirement is not satisfied**. V10's formal promotion into V11–V20 remains blocked pending owner/reviewer sign-off.

**Controlling machine-readable artifact:** docs/data/SOURCE_FIELD_DICTIONARY_V11.json.
**Reference source:** unchanged V9 snapshot 704123eca45628bf504594af39a66036cc0451c5 and its V10 technical freeze.
**Current governance state:** DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED; all proposed steward roles are unassigned; no customer source of record; no production authorization.

## Entity and schema catalog

| Dataset | Rows | Field count | Proposed dataset steward | Authority |
|---|---:|---:|---|---|
| asset_records | 6 | 4 | Maintenance data steward | Fabricated assets in fixtures/cases.json |
| case_records | 12 | 10 | Maintenance data steward | Fabricated maintenance events in fixtures/cases.json |
| scripted_review_entries | 4 | 4 | Maintenance process owner | Fictional reviewer-role script only |
| seeded_reference_labels | 12 | 3 | Quality assurance test steward | Authored test annotations only, NOT blinded validated ground truth |

Field types below describe the checked-in JSON, not a customer ERP/CMMS schema.

### Asset records — 4 fields

| Field | Type | Meaning and proposed stewardship |
|---|---|---|
| asset_id | string, SYN-ASSET-NNN | Fabricated asset identifier; Maintenance data steward |
| asset_class | enumerated string | Invented equipment category; Maintenance engineering SME |
| cohort | enumerated string | Imaginary asset grouping; Maintenance data steward |
| synthetic | boolean, true | Fabricated-only origin; Engineering data steward |

### Case records — 10 fields

| Field | Type/unit | Meaning and proposed stewardship |
|---|---|---|
| case_id | string, SYN-CASE-NNN | Fabricated unique case; Maintenance data steward |
| asset_id | string, foreign key | Joins to synthetic asset; Maintenance data steward |
| work_order_ref | string, SYN-WO-NNN | Example reference only, not a dispatched work order; CMMS data steward |
| occurred_at_utc | UTC timestamp, Z suffix | Invented event time, not source-validated telemetry; Maintenance data steward |
| failure_code | enumerated string | Scenario label, not fault diagnosis; Reliability engineering SME |
| downtime_hours | finite nonnegative number, hours | Made-up duration, no production downtime measurement; Reliability data steward |
| repair_cost_usd | finite nonnegative number, USD | Invented cost, not booked expense or financial benefit; Finance data steward |
| evidence_refs | unique string array, 0–3 | Example SYN-EV references only; no underlying documents; Maintenance data steward |
| synthetic | boolean, true | Mandatory fabricated origin flag; Engineering data steward |
| review_state | literal fixture_only | Prevents interpretation as signed maintenance disposition; Maintenance process owner |

### Scripted reviewer entries — 4 fields

| Field | Type | Meaning and proposed stewardship |
|---|---|---|
| case_id | string, foreign key | Fictional case link; Maintenance data steward |
| reviewer_id | string, SYN-REVIEWER-NNN | Invented persona, not authenticated employee; Maintenance process owner |
| disposition | allowed enum | Simulated action, not a real decision; Maintenance process owner |
| reason_code | allowed enum | Fictional reason coupled to demonstration action; Maintenance process owner |

### Seeded reference labels — 3 fields

| Field | Type | Meaning and proposed stewardship |
|---|---|---|
| case_id | string, foreign key | Example case identifier; Quality assurance test steward |
| expected_review_label | allowed enum | Hand-authored reference label, not independent SME adjudication; Qualified domain reviewer (unassigned) |
| synthetic | boolean, true | Explicit fabricated annotation origin; Quality assurance test steward |

## Data correctness constraints

- Exactly 21 declared field occurrences match the four fixture row types. No extra fields (including customer/employee PII), missing fields, or nulls are allowed.
- IDs use strict SYN prefixes and three-digit shapes. Asset/case IDs and case work order references are unique. Case asset links, reviewer case links and reference-label case links are checked for referential integrity.
- Timestamps are canonical YYYY-MM-DDTHH:MM:SSZ strings. UTC timezone is a *fixture convention*; real device clock/timezone, ingestion latency and shift/calendar semantics are unverified.
- downtime_hours is a finite JSON number from 0 to 240. repair_cost_usd is a finite JSON number from 0 to 1,000,000. Their values are invented; production monetary representation, decimal precision, currency and expense attribution are unapproved.
- An empty evidence_refs list means *no fictional reference ID supplied*, not confirmation that an actual supporting document is missing. Presence of a reference ID is not evidence authentication.
- No statistical inference, case severity prediction, savings, critical recall or performance conclusion is supported by these 12 examples.

## Responsibility and signature requirements

The dictionary separates **proposed steward role** from **assigned steward**; every assigned steward is null. Approval placeholders for a named Mavenu product owner, qualified reliability SME, customer data owner and date are null. None of these are signatures or real customer agreements.

A future authorized approval requires:
1. Product owner validates the real user, purchase case and data use.
2. Customer/system owner identifies authoritative sources of records, column types, provenance, keys, permitted extraction scope and retention.
3. Qualified reliability SME verifies asset hierarchy, event semantics, failure taxonomies, downtime calculations, UTC/timezone interpretation and label adjudication.
4. Finance/data steward validates money type, currency/precision and any realized cost/savings claims.
5. Security/OT owner signs data rights, read-only isolation, privacy and connector boundaries.
6. Responsible approvers sign an explicit dictionary version and resolve the V10 formal promotion BLOCKED status.

Until those signatures exist, the V11 acceptance proof is **partially demonstrated technically but not approved**.

## Reproduce

From the project directory:

~~~~bash
PYTHONPATH=src python scripts/verify_v11.py
~~~~

The script first verifies all 18 V10 frozen source/configuration files, then the V10 BLOCKED/PENDING human decision, then the draft dictionary schema, types, proposed stewardship and actual synthetic fixture contents. A successful result writes evidence/V11/verification.json and reports the field count. It is NOT an approval action.

## Alternative path

Customer discovery may show the existing CMMS/ERP/reporting system can support this review without a new SaaS platform. Retain configure/buy/no-build alternatives. Real plant data and OT writes are prohibited until separately authorized.
