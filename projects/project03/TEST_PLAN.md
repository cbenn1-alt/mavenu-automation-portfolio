# Project P03 — Test Plan

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Strategy

- **Service tests** (`tests/test_docintel.py`, 58 collected incl. 5 parametrized expansions of `test_exception_illegal_transitions`) exercise `docintel.py` + `extraction.py` directly against a fresh in-memory SQLite database with migration `021_docintel` applied. No HTTP, no server.
- **API + page tests** (`tests/test_docintel_api.py`, 15 tests) exercise the WSGI app through the shared `wsgi_call` helpers: JSON endpoints, form posts, page renders, status codes.
- **Fixture oracle**: one hand-built fixture (`DOCS_JSON` in `tests/test_docintel.py`) with hand-computed expected counts. Every aggregate (documents, fields, money, exceptions) is asserted against the oracle — the tests cannot pass by construction, only by correct behaviour.
- **Determinism check**: extraction is run twice on the same fixture and the field rows are compared byte-for-byte (test `test_extraction_is_deterministic`).

## 2. Fixture design (synthetic only)

`DOCS_JSON` — 8 rows, 7 unique documents + 1 within-batch duplicate:

| Doc | Type | Notes |
|---|---|---|
| DOC-INV-001 | invoice | Clean. All 5 fields ≥ 0.80. → accepted |
| DOC-INV-002 | invoice | Vendor only on the first line (rule `vendor_first_line`, 0.60) → proposed, `low_confidence` |
| DOC-INV-003 | invoice | No due date in the text → `missing` field, `missing_field` exception |
| DOC-RCP-001 | receipt | Clean. → accepted |
| DOC-RCP-002 | receipt | Payment method "crypto" extracted at 0.95 (field stays `accepted` — confidence is what it is) but fails the known-method validation → `validation_failed` exception, document blocked from acceptance until a human corrects it |
| DOC-CTR-001 | contract | Clean, incl. long-form date "October 1, 2026". → accepted |
| DOC-GARBAGE-001 | invoice | No field matches at all → 5 missing fields, `unparseable_document` exception |
| (repeat of DOC-INV-001) | — | Within-batch duplicate → `duplicate_document` exception at ingest |

Hand-computed oracle: 7 documents (3 accepted / 4 needs_review), 33 fields (26 accepted / 1 proposed / 0 rejected / 6 missing), accepted money **$52,422.89** (5,242,289 cents), 5 open exceptions.

## 3. Coverage map (real test names — verify with `pytest --collect-only -q`)

| Area | Tests |
|---|---|
| Ingest | `test_ingest_json_happy_path_counts`, `test_ingest_json_row_errors_do_not_abort_batch`, `test_ingest_json_invalid_json_is_fatal`, `test_ingest_json_non_array_is_fatal`, `test_ingest_csv_happy_path`, `test_ingest_csv_missing_columns_is_fatal`, `test_ingest_text_single_document`, `test_ingest_reingest_is_idempotent` (also proves the within-batch duplicate raises exactly one `duplicate_document` exception and re-ingest raises none), `test_formula_doc_id_sanitized_text_untouched` |
| Extraction | `test_extract_clean_invoice_all_fields_provenance`, `test_extract_vendor_first_line_fallback_below_threshold`, `test_extract_garbage_document_zero_fields`, `test_extract_determinism`, `test_extract_date_formats_and_boundary`, `test_extract_bare_invoice_number`, `test_extract_total_largest_fallback_below_threshold`, `test_amounts_parse_via_decimal`, `test_document_confidence_weakest_link` |
| Validation | `test_validation_due_before_issued`, `test_validation_payment_method_unknown`, `test_validation_receipt_date_future`, `test_validation_term_zero`, `test_validation_skips_missing_fields` |
| Document state machine | `test_doc_workflow_states`, `test_doc_history_single_accept_path`, `test_reject_document_terminal`, `test_extract_twice_rejected`, `test_extract_unknown_doc_id`, `test_extract_unknown_doc_type_rejected` |
| Field review | `test_review_accept_proposed_field_resolves_doc`, `test_review_correct_missing_field_resolves_doc`, `test_review_correct_accepted_but_invalid_field`, `test_review_correct_locked_accepted_field_rejected`, `test_review_correct_rejects_bad_value`, `test_review_reject_proposed_field_keeps_doc_open`, `test_review_accept_missing_field_rejected`, `test_review_unknown_action`, `test_review_unknown_field` |
| Exceptions | `test_exception_legal_transitions`, `test_exception_illegal_transitions` (6 parametrised cases), `test_exception_unknown_id`, `test_fixture_exception_queue_contents`, `test_exception_aging_buckets`, `test_unparseable_document_has_no_missing_field_exceptions` |
| Summary / backlog / runs | `test_fixture_extract_all_counts`, `test_fixture_field_statuses`, `test_summary_matches_hand_computed_expectations`, `test_summary_field_identity`, `test_summary_money_excludes_proposed_values`, `test_summary_money_values_are_decimal`, `test_review_backlog_contents`, `test_run_log_records_ingest_and_extract` |
| Migration | `test_migration_021_down_step_rolls_back_for_real` — `021` up applies 7 tables; down drops all 7 |
| API (15 tests) | `test_upload_and_extract`, `test_upload_invalid_format_rejected`, `test_upload_reports_row_errors`, `test_documents_list_and_filter`, `test_document_detail_with_fields_and_history`, `test_document_detail_unknown_id`, `test_field_review_flow`, `test_field_review_illegal_actions`, `test_document_reject_flow`, `test_exceptions_list_and_transition`, `test_exception_transition_unknown_id`, `test_pages_render`, `test_detail_page_offers_correction_only_for_flagged_accepted_field`, `test_form_upload_and_extract_redirect`, `test_hub_and_nav_link_p03` |
| Security | Formula-injection sanitisation (`test_formula_doc_id_sanitized_text_untouched`); parameterised SQL — by construction, see SECURITY.md |

## 4. What is NOT tested (deliberate)

- No real documents, no OCR, no external service — out of scope by design.
- No performance/load testing — the SQLite demo scale (tens of documents) is the target.
- No multi-user concurrency — single-writer demo; SQLite WAL is the repo default.
