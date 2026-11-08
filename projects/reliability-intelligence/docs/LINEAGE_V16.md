# V16 — Synthetic ingestion-origin and transformation lineage

**Controlled standard:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**Objective:** Capture ingestion origin and transform lineage.
**Proof:** Record-level trace sample.

**Scope:** Reproducible record-lineage reconstruction from committed fabricated source JSON files. This is NOT an observed real-world ingestion event. V10 formal phase promotion remains BLOCKED/PENDING human decision, and V11/V12 source approvals are unsigned.

## Source origin and derivation

Each of 34 trace records has a deterministic synthetic ID, source dataset/key, allowlisted fixture path, exact JSON row pointer, source-file byte SHA-256 and canonical source-row SHA-256. If applicable, a step identifies the V15 transformation rule and fixed parameters, original-value hash, canonical value and resulting hash. A complete normalized-record hash and sorted trace-batch hash support independent replay.

All origin records state observed_ingestion_at_utc: null and customer_source_observed: false. The origin method is committed_synthetic_fixture_reconstruction. No real customer CMMS/ERP source, network ingest event, custodian, observation timestamp or signed/immutable custody record has been established.

| Source | Fabricated rows | V15 transforms |
|---|---:|---:|
| Synthetic assets, fixtures/cases.json | 6 | Identity pass-through |
| Synthetic maintenance cases, fixtures/cases.json | 12 | UTC, duration hours, USD (three per case) |
| Scripted fictional reviewer roles | 4 | Identity pass-through |
| Authored reference labels | 12 | Identity pass-through |
| Total | **34** | **36 field-level transforms** |

## Controlled sample

The proof artifact evidence/V16/record_level_trace_sample.json includes five complete traces: SYN-ASSET-001, SYN-CASE-001 and SYN-CASE-009 maintenance cases, SYN-CASE-001 fictional reviewer script, and SYN-CASE-001 unblinded label. The two case traces contain six field transformations. The full 34-record trace is in evidence/V16/synthetic_record_lineage.json; a summary and source checksums appear in evidence/V16/lineage_verification.json.

The source JSON numeric types remain unchanged. Derived values are canonical strings and are NOT automatically persisted to the existing V9 runtime/API or an approved customer data model. The numeric, UTC and currency rules are unapproved synthetic assumptions from V11/V15.

## Reproducible verification

The V16 verifier rechecks V10 frozen 18-file integrity, the V11/V12 draft dictionary/schema, V13 feasibility and V15 conversion reference outcomes. It then constructs and independently verifies every record hash, JSON pointer, and exact transform, reconstructs the full trace twice and confirms deterministic output without modifying input sources.

115 new V16 tests include 34 individually verified record origins, 36 individual conversion steps and 45 tampering/governance checks. The expected complete suite is **544** tests (429 previous plus 115 V16), subject to actual hosted GitHub Actions output.

Tampering checks reject altered source pointers/file hashes, changed record/step digest or transform rule, missing or duplicated records, wrong output/order, false ingest timestamps, fabricated signatures and unauthorized source paths.

## Important limits

**Reconstructed source lineage is not observed production-ingestion provenance.** SHA-256 establishes test reproducibility, not a digital signature, immutable audit trail or custody guarantee. No customer data, personnel records, live plant telemetry, network connector, real work-order action, CMMS/ERP/PLC/SCADA/OT write, certified security or measured savings are involved.

A qualified data steward, customer system owner, and security/OT reviewer must independently approve actual source origins, rights, field definitions, timestamps, retention, masking, custody and verification before any live ingestion. V10 and V11 approvals remain outstanding.
