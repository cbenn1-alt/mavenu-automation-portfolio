# Project P03 — Architecture

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Module map

| Module | Responsibility |
|---|---|
| `src/mavenu/extraction.py` | Deterministic rule-based field extraction + validation. Pure functions; no DB, no I/O. |
| `src/mavenu/docintel.py` | Service layer: ingest (JSON/CSV/single text), extraction orchestration, field review, document reject, exception queue access, summary/aging/backlog, run log. |
| `src/mavenu/workflow.py` | Adds `DOC_WORKFLOW` (document state machine) next to the existing workflows. |
| `src/mavenu/web.py` | P03 pages + `/api/docintel/*` JSON endpoints; reuses shared page helpers and the exception list/detail patterns from Q05. |
| `src/mavenu/migrations/021_docintel.sql` | Seven tables (see §2). `021_docintel.down.sql` drops them all. |
| `tests/test_docintel.py` | 57 service-layer tests incl. the hand-computed fixture oracle. |
| `tests/test_docintel_api.py` | 14 API + page tests over the WSGI app. |

## 2. Data model (migration 021)

| Table | Purpose |
|---|---|
| `docintel_documents` | One row per document: `doc_id` (unique), `doc_type` (`invoice`/`receipt`/`contract`), `source_format`, `text` (stored as-is), `state`, `doc_confidence` (Decimal, min accepted-field confidence), `actor`, timestamps. |
| `docintel_fields` | One row per extracted-or-expected field: `field_name`, `value_text`, `value_cents` (integer, money fields only), `confidence` (Decimal), `status` (`accepted`/`proposed`/`rejected`/`missing`), `rule_id`, `source_line`, `raw_text`, `validation_error`. Unique per `(document_id, field_name)`. |
| `docintel_exceptions` | Exception queue rows: `kind` (`low_confidence`, `missing_field`, `validation_failed`, `duplicate_document`, `unparseable_document`), `state` (Q05 workflow), `ref_public_id` (the `doc_id`), `actor`, `detail`, `suggested_action`, timestamps. |
| `docintel_exception_events` | Audit trail for exception transitions (`from_state → to_state`, actor). |
| `docintel_field_events` | Audit trail for field review actions. |
| `docintel_doc_events` | Audit trail for document state transitions. |
| `docintel_runs` | One row per ingest/extract run (`kind`, `actor`, `batch`, counts, timestamps). |

Foreign keys: fields, exceptions, and events reference their parent document/exception with `ON DELETE CASCADE`.

## 3. State machines

**Document** (`DOC_WORKFLOW`, `src/mavenu/workflow.py`):

```
ingested ──► needs_review ──► accepted
    │            │
    └────────────┴──► rejected
```

`accepted` and `rejected` are terminal. Every transition is validated against the workflow and recorded in `docintel_doc_events`. A document moves to `accepted` only when `_recompute_doc_state` finds **every** field `accepted` and no open exception blocks it. A `rejected` field is not a pass — it means "this extraction is wrong, do not use it" — so the document stays in review until a human rejects the document itself (see `test_review_reject_field_blocks_acceptance`).

**Exception** (reuses `EXCEPTION_WORKFLOW` from Q05):

```
open ──► investigating ──► resolved
                       └──► written_off
```

`resolved` and `written_off` are terminal. Illegal transitions raise `ValueError` (service) / HTTP `409` (API).

## 4. Extraction design

`extraction.py` is deliberately boring and inspectable:

- **Field specs** (`FIELD_SPECS`) declare, per document type, the expected fields, their kind (`money` / `date` / `text` / `enum`), and the rules that can produce them. Invoice: vendor, invoice_number, issued_date, due_date, total. Receipt: merchant, receipt_date, total, payment_method. Contract: counterparty, title, effective_date, term_months, total_value.
- **Rules** are compiled regexes with a fixed confidence. Each rule yields `(value, confidence, raw_text, source_line)`. The best (highest-confidence) match wins per field; ties go to the first rule in declaration order.
- **Confidence** is a property of the *rule*, not of the data — e.g. a vendor taken from the first line scores `0.60` (weak: a bare line could be anything), while a `Vendor: X` label scores `0.90`. This is what makes low-confidence review meaningful: the system knows which extractions are guesses.
- **Threshold** `ACCEPT_THRESHOLD = 0.80`. At/above → `accepted` (auto); below → `proposed` (human-gated); no rule matches → `missing`.
- **Validation** (`validate_field`) is a separate, explicit pass over extracted values: amount positive, `due_date >= issued_date`, invoice number matches `INV-YYYY-NNNN`, receipt date not in the future, payment method in the known set (`cash`, `card`, `check`, `bank_transfer`, `mobile_pay`), contract term positive, contract value non-negative. A validation failure raises a `validation_failed` exception and forces the document to `needs_review`. The field keeps the status its confidence earned — a high-confidence but invalid value (e.g. payment method "crypto" at 0.95) stays `accepted` as a field, while the open exception blocks the *document* from being accepted until a human corrects the value or resolves the exception (see §5, point 3).
- **Dates** are normalised to ISO (`YYYY-MM-DD`) at extraction time; long-form dates ("October 1, 2026") are supported.
- **Money** is parsed to `Decimal` and stored as integer `value_cents`. No floats anywhere in money math.

## 5. Key decisions

1. **Reuse, don't rebuild, the exception queue.** Q05's `EXCEPTION_WORKFLOW`, transition validation, actor stamps, and event-table shape are reused verbatim. P03 adds only its own tables and kinds. One queue concept, one set of rules.
2. **Human gate is a real gate.** `proposed` fields cannot become `accepted` except through `review_field` with an explicit actor. The service enforces it; the tests prove it (a proposed field is still proposed after extraction, and the API returns `409` for an illegal accept).
3. **Accepted fields are locked — with one escape hatch.** A field that was auto-accepted at high confidence cannot be corrected, *unless* an open `validation_failed` exception flags that very field. This handles the real case where a high-confidence extraction is nevertheless invalid (e.g. payment method "crypto" extracted at 0.95). The escape hatch is narrow by design: it requires the exception to exist and be open.
4. **Idempotency is a first-class behaviour.** Re-ingest is safe; within-batch duplicates are exceptions, not silent overwrites. The distinction is tested.
5. **Document text is stored as-is; only identifiers are sanitised.** `doc_id` and `doc_type` pass through `reconcile.sanitize_cell` (formula-injection guard); the body text is preserved verbatim so extraction provenance (source line, raw text) stays truthful.
6. **No black-box AI.** The module is named "AI Document Intelligence" because that is the product label in the portfolio plan; the implementation is deterministic rules, and every doc says so. No model, no network, no external service.
