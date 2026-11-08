# V5 synthetic fixture provenance register

Fixture ID: SYN-RI-V5-20261107-A
Authoring date: 2026-11-07
Origin: Mavenu manually fabricated maintenance events, not actual customer or vendor records.
Source systems: NONE. Customer data used: NO. Independent validation: NOT PERFORMED.

## Files
- cases.json: 6 imaginary asset references and 12 fabricated maintenance cases, all prefixed SYN-.
- reference_labels.json: invented case annotations, kept separate from the user-facing API/UI, not an independently adjudicated ground truth.
- manifest.json: authorship, method, scope, restrictions, record counts and pinned Git blob SHA-1 IDs.

All cases are deliberately constructed for testing the software boundary, not sampled from a real population.

## Semantics
- case_id: SYN-CASE-001 through SYN-CASE-012; fictional case identifier
- asset_id: references fictional SYN-ASSET-001 through SYN-ASSET-006
- work_order_ref: SYN-WO-style identifier; not an actual work order
- occurred_at_utc: invented ISO UTC timestamp
- failure_code: illustrative categorical value, not a machine diagnosis
- downtime_hours: invented numerical duration, not validated plant downtime
- repair_cost_usd: invented expense amount, not observed cash impact
- evidence_refs: invented document reference IDs, no actual source document or telemetry
- synthetic: true; review_state: fixture_only — no human disposition or automated decision

Asset names are fictional: Assembly Test Line, Utility Test Zone, Mock Workshop. Labels include single_event, repeat_history_candidate, missing_evidence, solely to test synthetic scenarios. The separate labels file is visible to repository collaborators and is **not a genuine blinded holdout**.

## Reproduction and integrity

From the project directory:
~~~~bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m reliability_intelligence serve
curl http://127.0.0.1:8765/api/v1/cases
~~~~

The validator enforces fixed file paths, Git blob object hashes (SHA-1 over the Git blob header plus raw bytes), exact allowed fields, counts, duplicate detection, synthetic IDs, known asset references, canonical timestamps, finite nonnegative monetary and time values, and approved evidence refs. It rejects unexpected PII fields.

Git blob IDs protect against inadvertent fixture changes within this checked-in set; **they are not signatures or cryptographically strong provenance attestations**. Content changes require review and an updated release record, not silent checksum changes.

No real maintenance failures, actual machine risk estimates, staff actions, economic outcomes, production permissions or independent SME validation are claimed.
