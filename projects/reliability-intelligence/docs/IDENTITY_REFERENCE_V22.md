# V22 — Identity and reference-data rules

**Controlled source:** Mavenu AI SaaS Platform Development Architecture V4, Storage Data Model V21–V30.
**Exact V22 objective:** Define identity and reference-data rules.
**Required proof:** Uniqueness and link tests.

**Classification:** Candidate synthetic-only engineering rules; real customer domain approval **PENDING**. V10 formal phase promotion and V20 Data Correctness sign-off remain **BLOCKED**. V21 entity-schema human review remains pending. V22 does not create a durable database, authorize tenant access, or implement the later V23 migration.

## Canonical identity standard

The V22 reference policy, docs/data/IDENTITY_REFERENCE_POLICY_V22.json, pins nine synthetic identifier token types:

| Token | Exact pattern | Intended meaning |
|---|---|---|
| tenant_id | SYN-TENANT-NNN | Invented tenant namespace |
| site_id | SYN-SITE-NNN | Invented site |
| asset_id | SYN-ASSET-NNN | Fictional equipment |
| case_id | SYN-CASE-NNN | Fictional maintenance case |
| work_order_ref | SYN-WO-NNN | Work-order-*like* ID, not operational instruction |
| evidence_ref | SYN-EV-NNN | Fabricated evidence reference, no real file |
| reviewer_id | SYN-REVIEWER-NNN | Fictional reviewer, no directory account |
| source_document_id | SYN-DOC-NNN | One of three committed fixture documents |
| trace_id | SYN-LINEAGE-[dataset]-SYN-[ASSET or CASE]-NNN | Reconstructed source record trace |

NNN means exactly three ASCII digits. The validator uses full-token ASCII case-sensitive matching, **not** trim, Unicode normalization, case folding, inferred aliases, fuzzy matching, merge or external ID resolution. Those behaviors must await real system-of-record identity governance. For real identity systems, tenant/asset/site naming conventions, alias lifetimes, canonical case/work-order relationships and collision recovery need customer approval. An invented synthetic ID is not a customer system-of-record key.

## Uniqueness and links

V22 checks **13 explicitly scoped uniqueness rules**: primary identities for tenant, site, asset, maintenance case, evidence-reference, scripted review, reference label, source document, record origin and transform step, plus independent per-site work-order uniqueness, fixture-path uniqueness and reconstructed source identity uniqueness.

It verifies **nine directed links** (site → tenant, asset → site, case → asset, three case-child references, source document → site, record origin → source document, transform step → record origin). Foreign keys use the V21 in-memory SQLite relational schema and tenant/site components. The synthetic input layer separately rejects duplicate cases/assets/work references, duplicate case evidence IDs, duplicate reviews and labels, and orphaned asset/case links.

**Composite foreign keys are not tenant authorization.** No authenticated actor, role policy, row-level access security, real tenant isolation, customer rights or production database security is implemented. The V21 temporary SQL schema is unaltered.

## Fixed synthetic reference categories

Ten allowlisted categories: asset class, cohort, failure code, case review state, scripted disposition, scripted reason, authored reference label, V16 source dataset, three allowed source-fixture paths, and V15 transform-rule IDs. Reference values are illustrative tokens only: they are not validated equipment taxonomies, personnel identities, real failure diagnoses, human review dispositions or independently confirmed labels.

The V22 validator rejects unknown enum values, unsupported external documents and unexpected fields. It does not auto-correct source data, silently drop bad records or infer missing references.

## Evidence and regression scope

- docs/data/IDENTITY_REFERENCE_POLICY_V22.json: explicit nine identifier patterns, 13 scoped unique rules, nine FK links, ten controlled reference sets, 25 fixed negative scenarios and no-signature approval ledger.
- scripts/identity_v22.py: pure source validation plus V21 :memory: uniqueness/link checks; rejects 25 mutated fixture copies with exact fixed error codes.
- scripts/verify_v22.py: checks V10 frozen source, V20 blocked and V21 pending governance, 120-row V21 synthetic model, nine links/13 uniqueness views/10 reference categories, fixture SHA-256 before/after and creates three evidence reports.
- tests/test_identity_v22.py: **102 added unit/regression tests**, expected **1006 total** (904 inherited), subject to hosted exact-head CI. Tests include 25 individual bad-input cases, the nine patterns, ten reference sets, thirteen uniqueness scopes, nine links, false approval claims and cross-tenant negative checks.

Generated under evidence/V22:
1. identity_reference_validation.json — exact stage result and numeric checks;
2. uniqueness_link_matrix.json — duplicate/orphan inventory, negative case results;
3. unsigned_identity_review.json — blank human decision, still blocked.

All V22 tools use invented source files only; the V21 database is created with sqlite3 :memory: and closed. The source files and V9 runtime 0.9.0/read-only API v1/schema 1.3.0 remain unchanged. The 84.5% V8 historical coverage threshold, prior CI tests and V10 18-file freeze are retained.

## Human readiness gates

A named data architect, customer CMMS/data steward and security/OT reviewer must verify actual site/tenant identity, stable keys, alias/merge/split processes, uniqueness scope, reference-data maintenance and ownership, provenance, and customer permissions. A dated signed identity review and prior V10/V20 phase decisions are required before claiming formal V22 acceptance.

**No production persistence, migration (V23), recovery, real system integration, operational authorization or savings claim is established by V22.**
