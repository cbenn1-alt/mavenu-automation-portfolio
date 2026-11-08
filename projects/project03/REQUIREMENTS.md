# Project P03 — Requirements

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Purpose

Ingest business documents (invoices, receipts, contracts), extract their key fields deterministically, validate the results, and surface anything uncertain or invalid to a human reviewer through an exception queue — with a complete audit trail. No field may be auto-accepted below the confidence threshold.

## 2. Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-01 | Ingest a batch of documents as JSON or CSV (list of `{doc_id, doc_type, text}`), reporting per-row errors without aborting the batch | Done |
| FR-02 | Ingest a single text document directly | Done |
| FR-03 | Re-ingesting an already-stored `doc_id` is idempotent: no duplicate document, no duplicate exception, counted as `skipped_idempotent` | Done |
| FR-04 | A second occurrence of the same `doc_id` **within one batch** raises a `duplicate_document` exception (open, linked to the doc) | Done |
| FR-05 | Deterministic, rule-based field extraction for invoices, receipts, and contracts, with per-field confidence (`0.00–1.00`) and provenance (`rule_id`, 1-based source line, raw matched text) | Done |
| FR-06 | Extraction is purely deterministic: same input always yields the same fields; no randomness, no external model, no network | Done |
| FR-07 | Confidence threshold **0.80**: fields at/above it are `accepted`; fields below it are `proposed` and require human review | Done |
| FR-08 | Fields with no matching rule are recorded as `missing` (no value, no confidence, provenance `None`) | Done |
| FR-09 | Validation rules run over extracted values: amount positive; due date ≥ issued date; invoice number matches `INV-YYYY-NNNN`; receipt date not in the future; payment method in the known set; contract term positive; contract value non-negative | Done |
| FR-10 | Any validation failure raises a `validation_failed` exception naming the field and rule, and forces the document to `needs_review`. The field keeps the status its confidence earned (accepted at ≥ 0.80); the document cannot become accepted while the exception is open | Done |
| FR-11 | Unparseable documents (no field matches at all) raise an `unparseable_document` exception | Done |
| FR-12 | Document state machine: `ingested → needs_review | accepted | rejected`; `needs_review → accepted | rejected`; `accepted`/`rejected` are terminal; every transition is recorded in `docintel_doc_events` | Done |
| FR-13 | A document becomes `accepted` only when every field is accepted and no open exception blocks it | Done |
| FR-14 | Human field review: `accept` (proposed → accepted), `correct` (proposed → accepted with a new value, re-validated), `reject` (proposed → rejected); actor stamped; illegal actions return `409` | Done |
| FR-15 | An accepted field may be corrected **only** when an open `validation_failed` exception flags that field (the lock is real, not cosmetic) | Done |
| FR-16 | Exception queue reuses the Q05 workflow: `open → investigating → resolved | written_off`, actor stamps, suggested action per kind, event history per exception | Done |
| FR-17 | Review backlog lists every `needs_review` document with its unresolved fields and open exception kinds | Done |
| FR-18 | Extraction summary: document/field counts by state, accepted-money total (Decimal only, proposed values excluded), exception counts by state/kind, exception aging buckets (0–7 / 8–30 / 31+ days) | Done |
| FR-19 | Run log: every ingest/extract run is recorded in `docintel_runs` with actor, timestamps, and result counts | Done |
| FR-20 | Web UI + JSON API for upload, extract, documents, document detail, field review, document reject, exceptions, exception detail/transition, and reports | Done |

## 3. Non-functional requirements

| ID | Requirement | Status |
|---|---|---|
| NFR-01 | Python 3.12 standard library only; pytest; $0 cost | Done |
| NFR-02 | SQLite via the shared `mavenu.db` helpers; parameterized SQL only — no string-built queries | Done |
| NFR-03 | Money math uses `Decimal` end-to-end; `value_cents` is an integer; totals never use floats | Done |
| NFR-04 | Input validation at every boundary: `doc_id`/`doc_type` sanitised (formula-injection guard), payload shape checked, confidence clamped to `[0, 1]` | Done |
| NFR-05 | Every state change is audit-logged (document events, field events, exception events) with actor and timestamp | Done |
| NFR-06 | Migration `021_docintel` is reversible: the down-step drops all seven tables and is exercised by test | Done |
| NFR-07 | Synthetic data only — no real documents, no real PII, no external service calls | Done |

## 4. Acceptance criteria (Gate C)

1. All 73 P03 tests pass (58 service + 15 API), including the migration rollback test.
2. The fixture oracle in `TEST_RESULTS.md` matches hand-computed values exactly (7 documents, 33 fields, $52,422.89 accepted money, 5 open exceptions).
3. No below-threshold field can reach `accepted` without a human action; the test suite proves it (proposed fields stay proposed after extraction).
4. Migration down-step removes all seven `docintel_*` tables and is exercised by test.
5. Live smoke test: real HTTP upload → extract → accepted document, hub and P03 pages render 200.
