# V26 — Tenant boundaries and data rights

**Controlled architecture:** Mavenu AI SaaS Development Architecture V4, page 43.
**Exact objective:** Document tenant boundaries and data rights.
**Required proof:** Isolation design decision.

**State: PROPOSED_NOT_RATIFIED.** V26 defines a provisional *synthetic-only* logical tenant/site scoping test, not a selected or approved production architecture. V10 and V20 formal signoffs remain blocked. V21–V25 human reviews and a V26 data-owner/security/legal decision are outstanding.

## Alternative designs and decision

1. **Pooled tables, tenant/site keys:** current V21 model uses composite keys. Low prototype overhead. Without verified principals, RLS/least-privilege DB authorization and independent isolation tests, application WHERE clauses can be bypassed.
2. **Database per tenant:** potentially stronger physical separation with separate migration/backup lifecycle; higher operations and key-management complexity; authentication and rights still required.
3. **Schema per tenant:** logical namespace separation but permission/routing/schema sprawl. Not implemented in the SQLite prototype.

**Production choice: UNDECIDED.** Need authenticated customer identity, source-of-truth ownership, authorized uses, actual workloads, DB platform, risk/cost, incident response and tenancy security review before selecting a production design.

## Synthetic fixture and reference scope guard

Version-2 V23/V24.1 disposable SQLite schema contains **38 fabricated records**: 2 tenants, 4 sites (two reused site IDs per tenant), 8 assets, 12 cases, 12 artificial evidence references. The same SYN-CASE-001 appears in all four tenant/site contexts to exercise composite scope separation. Frozen V5/V10 fixtures and V9 runtime are untouched.

Six fabricated actors have source-controlled test grants; none are authenticated users. Two **read-only**, bound SQL shapes require exact tenant_id and site_id. One site viewer receives case summaries on one site, two invented evidence reviewers receive both case summaries and evidence IDs within their own site, another site viewer receives one site, one dual-site viewer receives two sites within only tenant 001, and the unassigned test actor has no rights.

The complete test probes **6 actors × 4 tenant/site scopes × 2 operations = 48 combinations**, expecting 8 allowed and 40 denied, plus ten malformed/unsupported probes uniformly rejected as scope_denied. No real actor identity, roles, SSO, signed claims, tenant grants or database RLS are implemented. Deliberate raw SQL bypass reads all 12 fabricated cases, proving that application guards alone are **not a security boundary**.

## Data-rights position

The real controller/legal data owner, right to obtain customer records, executed data-processing agreement, actual Mavenu processor designation, purpose/retention schedule, export/deletion rights, subprocessor permissions, cross-border transfers and incident duties are **NOT ESTABLISHED**. Actual ownership and lawful role classification depend on customer agreements and applicable law.

Before live data: identify customer owner and authoritative systems; obtain source-use licenses, DPA/rights schedule and security approvals; decide tenant provisioning/offboarding, verified authn/authz, least-privilege database accounts, RLS or equivalent isolation; test negative cross-tenant access independently; approve encryption, backups, retention/deletion/export and breach response. No OT/PLC/SCADA/CMMS writes without separate authorization.

## Files and acceptance

- docs/data/ISOLATION_DECISION_V26.json — provisional decision, options, six synthetic actor grants, trust boundaries, four data classes, open rights and unsigned approval.
- scripts/isolation_v26.py — disposable test fixture, exact scoped queries, uniform denial and 48-case negative/positive matrix.
- scripts/verify_v26.py — checks prior technical and blocked governance evidence, V10 source hashes and emits three JSON review artifacts.
- tests/test_isolation_v26.py — **118 new tests**; expected full suite 1,388, subject to GitHub CI.
- evidence/V26/isolation_design_decision.json, synthetic_access_probe_matrix.json and unsigned_data_rights_review.json — proof and missing owner signatures.

**Human readiness gate:** A named accountable customer data owner, technical/DB architect, security reviewer and legal/data-protection reviewer must sign a production isolation decision based on actual customer rights and independently tested database authorization. V26 synthetic automated proof is not that ratification.
