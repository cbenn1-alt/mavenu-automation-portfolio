# Project P03 — Security

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Threat model

P03 is a local demo with no network exposure beyond the dev server, no real documents, and no real PII. The realistic threats are the ones that would matter if it ever grew up: malicious input smuggled through a document batch, SQL injection through an identifier, formula injection through a spreadsheet export, and silent state changes with no audit trail. All four are addressed below.

## 2. Controls

| Threat | Control | Evidence |
|---|---|---|
| SQL injection via `doc_id`, field names, or query parameters | **Parameterized SQL only.** Every query in `docintel.py` uses `?` placeholders; no string-built SQL anywhere in the module. `doc_id` is never interpolated into a query. | Code review of `src/mavenu/docintel.py`; the service tests exercise hostile-looking ids (e.g. `=cmd\|'/C calc'!A0`) |
| Spreadsheet formula injection | `doc_id` and `doc_type` pass through `reconcile.sanitize_cell` at the ingest boundary (leading `=`, `+`, `-`, `@` are neutralised with a leading `'`). Document body text is stored as-is — it is data, never executed. | `test_formula_doc_id_sanitized_text_untouched` |
| Unvalidated input at the boundary | Payload shape is validated on ingest (JSON must be a list of objects with `doc_id`, `doc_type`, `text`; CSV must have the three columns; unknown `doc_type` is a row error, not a crash). Confidence is clamped to `[0, 1]`. Corrected values are re-validated (`validate_corrected_value`) before they are stored. | `test_ingest_json_row_errors_do_not_abort_batch`, `test_validate_corrected_value_cases`, API 422/409 tests |
| Silent or forged state changes | Every state change writes an audit row with actor + timestamp: `docintel_doc_events` (document transitions), `docintel_field_events` (field review), `docintel_exception_events` (exception transitions). Review actions require an `actor`. | `test_doc_history_single_accept_path`, `test_exception_legal_transitions`, `test_field_review_flow` (API) |
| Below-threshold auto-accept | There is no code path from `proposed` to `accepted` except `review_field` with an explicit actor. Extraction sets status from confidence only. | `test_extract_vendor_first_line_fallback_below_threshold` (vendor at 0.60 stays proposed after extraction); API returns `409` for illegal accepts |
| Secrets in code | None. No credentials, tokens, or keys anywhere in P03. The demo server binds localhost only. | Grep: no `password`, `token`, `secret`, `api_key` in `src/mavenu/docintel.py` or `extraction.py` |

## 3. What P03 does NOT do (by design)

- No OCR, no external model, no network calls — nothing leaves the machine.
- No real documents or PII — all fixtures are invented.
- No authentication/authorisation — the dev server is a single-user demo; do not expose it.
- No deletion of audit rows — events are append-only; the migration down-step drops whole tables, which is a rollback, not a redaction tool.
