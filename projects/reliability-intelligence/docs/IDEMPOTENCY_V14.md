# V14 — Duplicate and idempotency contract (technical draft)

**Source:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**Objective:** Enforce duplicates and idempotency rules.
**Required proof:** Repeated-ingest comparison.

**State:** Synthetic-only exploratory Data Correctness work. The formal V10 prototype decision remains BLOCKED/PENDING human sign-off. The V11 dictionary and V12 schema are unsigned. No real customer, CMMS, ERP or plant input has been authorized.

## Identity and behavior

| Dataset | In-memory identity key | Secondary rule |
|---|---|---|
| Fabricated asset records | asset_id | Unique within synthetic asset dataset |
| Invented maintenance cases | case_id | work_order_ref must be unique across cases |
| Scripted reviewer-role entries | case_id | A case can have at most one scripted disposition |
| Seeded reference labels | case_id | A case can have at most one authored test label |

The implementation is in scripts/ingest_v14.py and is restricted to the V11/V12 four-dataset field model. Its behavior is:

- First-time valid record: insert into the temporary in-memory store.
- Same identity + exactly the same canonical JSON record: count as a duplicate and do nothing.
- Same identity + different content: fail with identity_conflict.
- Different case identity + duplicate work_order_ref: fail with duplicate_work_order_reference.
- Unrecognized asset or case references: reject the batch.
- Invalid field, real-style ID, undeclared personnel column or wrong type: reject the entire batch.
- A batch commits **only after every staged row, cross-record uniqueness rule and foreign key passes**. Failed batches leave the previous snapshot and SHA-256 digest unchanged.

Canonical ordering sorts dataset names and primary identities, not customer timestamps. Canonical JSON serializes sorted object keys with compact ASCII encoding and disallows nonfinite numbers. SHA-256 is a reproducibility digest, **not an immutable audit trail, cryptographic authorization or signature**. Payload order inside evidence_refs remains semantically significant; no unapproved business-level deduplication is performed.

## Repeated-ingest evidence

The fixture plan at fixtures/repeated_ingest_v14.json defines 16 named cases: six accepted replays and ten controlled rejections. scripts/verify_v14.py executes them and writes evidence/V14/repeated_ingest_comparison.json.

The successful comparisons prove the current synthetic snapshot stays identical when all 34 fabricated records are replayed; when rows/datasets are reordered; when assets/cases/reviews/labels are loaded in four atomic parent-first batches; and when only seven already-seen cases are replayed. An identical case repeated within a new batch is inserted once and counted once as a duplicate. Every rejected batch must preserve the pre-call state digest.

The ten rejected cases cover conflicting primary keys, a conflict within a new batch, reused work-order references, orphan cases or scripted entries, a valid staged asset combined with an invalid row (rollback), non-SYN IDs, undeclared personnel fields and unsupported dataset names.

The report counts inserted, ignored and rejected records, and records fixed error codes. It contains **no actual customer records**.

## Scope and limitations

The store is **in-process and ephemeral**: no database, queue, transactions across processes, concurrency guarantees, retry token, distributed exactly-once semantics, idempotency key from a client, network service, durable event log, audit retention, or plant integration. A process restart loses the temporary state.

All IDs, relations and uniqueness assumptions are **authored from synthetic fixtures**. Actual CMMS/ERP identifiers, revision semantics, upsert authorization, late-arriving maintenance events, idempotency across deployments and operational synchronization must be designed and signed separately. Do not infer real plant uniqueness constraints, industrial safety or economic benefit from this demonstration.

**V14 technical verification is not formal Phase 02 approval.** Human owner, data steward and independent reviewer sign-offs remain pending, and customer-data/OT hard stops from V10 are unchanged.
