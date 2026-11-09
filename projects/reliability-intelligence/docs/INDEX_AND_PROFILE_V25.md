# V25 — Indexes and performance profiling

**Controlling architecture:** Mavenu AI SaaS Platform Development Architecture V4, p.43.
**Exact objective:** Add indexes and performance profiling.
**Required proof:** Query-plan and threshold report.

**Scope:** Synthetic-only candidate, not production deployment. V24.1 has already been merged into the V22 baseline. V25 installs its candidate indexes **only in an isolated, automatically deleted SQLite version-2 database**; V23 migration/version, V24 application storage and frozen V9 runtime remain unchanged.

## Four candidate indexes and read-only queries

| Index | Physical columns | Purpose |
|---|---|---|
| idx_v25_case_site_recent | tenant_id, site_id, occurred_at_utc DESC, case_id | Recent cases per fictional site |
| idx_v25_case_asset_recent | tenant_id, site_id, asset_id, occurred_at_utc DESC, case_id | Fictional asset chronology |
| idx_v25_case_failure_recent | tenant_id, site_id, failure_code, occurred_at_utc DESC, case_id | Fictional failure-code triage |
| idx_v25_evidence_reverse | tenant_id, site_id, evidence_ref, case_id | Reverse fictional evidence ID lookup |

Query text and bound parameters are strictly fixed in docs/data/INDEX_PROFILE_CONTRACT_V25.json. Tenant/site columns provide synthetic query scope, not authentication or RLS. Candidate DDL in docs/data/INDEX_DESIGN_V25.sql is allowlisted to four statements. Index creation is one BEGIN IMMEDIATE/COMMIT operation; simulated failure after index #2 confirms complete rollback. Schema version stays at 2 and the indexes are not versioned V23 migrations.

## Deterministic fabricated benchmark

Version-2 SQLite schema initialized via V24.1 and populated with 9,301 artificial rows:

| Entity | Rows |
|---|---:|
| tenant | 1 |
| site | 300 |
| asset | 1,800 |
| maintenance_case | 3,600 |
| evidence_reference | 3,600 |
| **Total** | **9,301** |

The V24 event ledger remains empty in the profiling database. The generated cases are *not* reclassified as frozen V5 fixtures or authenticated customer records. Existing source fixtures are hash-checked before/after.

## Query-plan and threshold evidence

For each of four fixed queries V25 records baseline/indexed EXPLAIN QUERY PLAN, result sets and SHA-256 fingerprints, five warmups and 37 measured executions per stage, median/P95/maximum elapsed milliseconds from time.perf_counter_ns, expected physical index choice and absence of a temporary sorting B-tree.

**CI guardrail:** each indexed query must use its expected index, require no temp sort, return identical results and have median <=80 ms / nearest-rank P95 <=200 ms. The thresholds are deliberately permissive and reflect this synthetic CI environment only, **not production latency SLOs**. The before/after ratio is recorded but no minimum speedup is required or claimed.

## Deliverables and reviews

- docs/data/INDEX_PROFILE_CONTRACT_V25.json and INDEX_DESIGN_V25.sql: formal candidate specification and DDL.
- scripts/index_v25.py and scripts/verify_v25.py: index installation, fabricated workload, plan/timing checks and evidence.
- tests/test_index_performance_v25.py: 54 new regression tests; expected total 1,270 (1,216 inherited), subject to hosted CI.
- evidence/V25/query_plan_threshold_report.json, indexed_vs_baseline_profile.json, unsigned_index_review.json: technical proof and unsigned decision.

Human reviewers must still approve representative query distributions, planner behavior on the target database, write amplification, concurrency, migration/versioning, backup, access controls, data rights and the future index rollout. V10 formal promotion/V20 data-quality signoff blocked and V21–V24.1 review decisions pending. No production database, customer sources, actual plant records, live integrations, power-loss certification or realized economic value.
