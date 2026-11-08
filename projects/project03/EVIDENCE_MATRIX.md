# Project P03 — Evidence Matrix

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

Every claim in this project's docs maps to a test, a file, or a measured run. If a claim has no evidence row, it is not a claim — it is a TODO.

## 1. Functional claims

| Claim | Evidence |
|---|---|
| Ingest JSON/CSV/single text; row errors do not abort the batch | `test_ingest_json_row_errors_do_not_abort_batch`, `test_ingest_csv_happy_path`, `test_ingest_text_single_document`, `test_ingest_json_invalid_json_is_fatal`, `test_ingest_csv_missing_columns_is_fatal` |
| Re-ingest is idempotent (8 skips on second ingest, no second duplicate exception) | `test_ingest_reingest_is_idempotent` |
| Within-batch duplicate raises exactly one `duplicate_document` exception | `test_ingest_reingest_is_idempotent`, `test_fixture_exception_queue_contents` |
| Deterministic rule-based extraction with confidence + provenance | `test_extract_determinism`, `test_extract_clean_invoice_all_fields_provenance` |
| Threshold 0.80; below-threshold fields are `proposed`, never auto-accepted | `test_extract_vendor_first_line_fallback_below_threshold`, `test_fixture_field_statuses`, `ACCEPT_THRESHOLD` in `src/mavenu/extraction.py` |
| Missing fields recorded as `missing` | `test_fixture_field_statuses`, `test_summary_field_identity` |
| Validation rules (amount, dates, invoice format, future receipt, known payment method, term, value) | `test_validation_due_before_issued`, `test_validation_payment_method_unknown`, `test_validation_receipt_date_future`, `test_validation_term_zero`, `test_validation_skips_missing_fields` |
| Validation failure → exception + document blocked, field keeps its confidence status | `test_review_correct_accepted_but_invalid_field`, `test_fixture_exception_queue_contents` |
| Unparseable document → `unparseable_document` exception, no `missing_field` exceptions for it | `test_extract_garbage_document_zero_fields`, `test_unparseable_document_has_no_missing_field_exceptions` |
| Document state machine enforced + audited | `test_doc_workflow_states`, `test_doc_history_single_accept_path`, `test_reject_document_terminal` |
| Field review accept/correct/reject with actor stamps; illegal actions rejected | `test_review_accept_proposed_field_resolves_doc`, `test_review_correct_missing_field_resolves_doc`, `test_review_reject_proposed_field_keeps_doc_open`, `test_review_accept_missing_field_rejected`, `test_review_unknown_action`, `test_review_unknown_field` |
| Accepted-field lock + validation escape hatch | `test_review_correct_locked_accepted_field_rejected`, `test_review_correct_accepted_but_invalid_field` |
| Rejected field blocks acceptance | `test_review_reject_proposed_field_keeps_doc_open` |
| Exception queue reuses Q05 workflow; illegal transitions rejected | `test_exception_legal_transitions`, `test_exception_illegal_transitions` (6 parametrised cases), `test_exception_unknown_id` |
| Review backlog contents | `test_review_backlog_contents` |
| Summary counts + accepted money (Decimal, proposed excluded) | `test_fixture_extract_all_counts`, `test_summary_matches_hand_computed_expectations`, `test_summary_money_excludes_proposed_values`, `test_summary_money_values_are_decimal` |
| Exception aging buckets (0–7 / 8–30 / 31+ days) | `test_exception_aging_buckets` |
| Run log recorded | `test_run_log_records_ingest_and_extract` |
| Web UI + JSON API for the whole flow | `tests/test_docintel_api.py` (15 tests incl. 409/404 paths, form redirects, page renders) |
| UI offers correction only for validation-flagged accepted fields | `test_detail_page_offers_correction_only_for_flagged_accepted_field` |

## 2. Fixture oracle arithmetic (hand-computed)

From `tests/test_docintel.py` (`EXPECTED`):

| Measure | Arithmetic |
|---|---|
| 33 fields | invoice 5×4 docs (INV-001/002/003, GARBAGE) + receipt 4×2 (RCP-001/002) + contract 5 (CTR-001) = 20 + 8 + 5 |
| 26 accepted / 1 proposed / 0 rejected / 6 missing | proposed: INV-002 vendor (0.60). missing: INV-003 due_date + GARBAGE 5 fields. 33 − 1 − 6 = 26 accepted. |
| $52,422.89 accepted money | 125,000 + 87,550 + 210,000 + 6,499 + 13,240 + 4,800,000 cents (INV-001 $1,250.00 + INV-002 $875.50 + INV-003 $2,100.00 + RCP-001 $64.99 + RCP-002 $132.40 + CTR-001 $48,000.00) |
| 5 open exceptions | low_confidence (INV-002 vendor) + missing_field (INV-003 due_date) + validation_failed (RCP-002 payment_method) + duplicate_document (INV-001 repeat) + unparseable_document (GARBAGE-001) |
| 3 accepted / 4 needs_review docs | accepted: INV-001, RCP-001, CTR-001. needs_review: INV-002, INV-003, RCP-002, GARBAGE-001. |

## 3. Non-functional claims

| Claim | Evidence |
|---|---|
| Stdlib only, pytest, $0 cost | `src/mavenu/extraction.py` + `docintel.py` import only stdlib + repo modules; no new dependency |
| Parameterized SQL only | Code review of `src/mavenu/docintel.py` (all queries use `?` placeholders) |
| Formula-injection sanitisation at the boundary | `test_formula_doc_id_sanitized_text_untouched` |
| Migration 021 reversible; down-step exercised | `test_migration_021_down_step_rolls_back_for_real` |
| Live smoke test (real HTTP) | `TEST_RESULTS.md` §4 — hub 200, P03 200, upload → extract → accepted doc, detail 200 (2026-11-08) |
| Full suite: 1,641 passed / 2 pre-existing date-dependent failures (1,643 collected) | `TEST_RESULTS.md` §1 — both failures reproduced on the pristine tree via `git stash` |

## 4. Honest-status banner (in every doc)

Implemented + tested (Gate C ✓) · synthetic/demo data only · no production deployment · no real clients · no bank approval · extraction is deterministic rules, not a black-box model.
