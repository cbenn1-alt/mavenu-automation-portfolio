# Project P03 — Test Results

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Headline

| Suite | File | Tests | Result |
|---|---|---|---|
| Service layer | `tests/test_docintel.py` | 58 | ✅ 58 passed |
| API + pages | `tests/test_docintel_api.py` | 15 | ✅ 15 passed |
| **P03 total** | | **73** | **✅ 73 passed** |

Run: `.venv/bin/python -m pytest tests/test_docintel.py tests/test_docintel_api.py -q`
— `73 passed in 2.07s` (2026-11-08).

Full repo suite after P03 (chunked runs, `/tmp/pytest-of-root` cleared between chunks): **1,641 passed, 2 failed** out of 1,643 collected (baseline 1,570 + 73 new). The 2 failures are **pre-existing and unrelated to P03** — both reproduce on the pristine tree via `git stash` (verified 2026-11-08):
- `tests/test_reconciliation_api.py::test_aging_endpoint` — date-dependent: the fixture's due dates were written for 2026-10-23; on 2026-11-08 invoice INV-0007 (due 2026-11-01) has moved from "current" to "1–30 days overdue", so the current bucket is 0, not 60,000 cents.
- `tests/test_estimates_api.py::test_api_cadence_run_queues_due_steps` — same cause (cadence computed against the real clock).

Both were passing on 2026-10-23 and fail now purely because time moved on. They are **not fixed** here: the task instruction is to not change other projects, and the fix (freezing the clock in those tests) belongs to their owners.

## 2. Fixture oracle (hand-computed, asserted by tests)

Fixture `DOCS_JSON` in `tests/test_docintel.py`: 8 rows → 7 unique documents + 1 within-batch duplicate.

| Measure | Expected | Actual |
|---|---|---|
| Documents ingested | 7 | 7 |
| Documents accepted | 3 (INV-001, RCP-001, CTR-001) | 3 |
| Documents needs_review | 4 (INV-002, INV-003, RCP-002, GARBAGE-001) | 4 |
| Fields total | 33 | 33 |
| Fields accepted / proposed / rejected / missing | 26 / 1 / 0 / 6 | 26 / 1 / 0 / 6 |
| Accepted money | $52,422.89 (5,242,289 cents) | $52,422.89 |
| Open exceptions | 5 (low_confidence, missing_field, validation_failed, duplicate_document, unparseable_document) | 5 |
| Exceptions raised by extract_all | 4 (duplicate raised at ingest) | 4 |

Money check (accepted money *fields*, Decimal — the summary sums `value_cents` over fields with `status = 'accepted'`, regardless of document state): INV-001 total $1,250.00 + INV-002 total $875.50 + INV-003 total $2,100.00 + RCP-001 total $64.99 + RCP-002 total $132.40 + CTR-001 total value $48,000.00 = 125,000 + 87,550 + 210,000 + 6,499 + 13,240 + 4,800,000 = **5,242,289 cents = $52,422.89**. Note the totals of INV-002, INV-003 and RCP-002 are included even though those documents are still `needs_review` — their *total fields* are accepted; what blocks the documents is a different field (vendor proposed / due_date missing / payment_method validation). Proposed values never count: `test_summary_money_excludes_proposed_values` proves a proposed money field (DOC-LOW-001 total at 0.70) contributes 0 until a human accepts it.

## 3. Rollback test

`test_migration_021_down_step_rolls_back_for_real` applies migration 021 to a fresh database, confirms all seven `docintel_*` tables exist, applies `021_docintel.down.sql`, and confirms all seven are gone. ✅ Passed.

## 4. Live smoke test (2026-11-08)

Real server (`python3 run.py --port 8123 --db /tmp/p03-live.db`), real HTTP:
- `GET /` → 200; `GET /project03` → 200; `GET /api/docintel/summary` → 200 (empty summary).
- `POST /api/docintel/upload` (invoice DOC-SMOKE-001) → 201, 1 inserted.
- `POST /api/docintel/extract` → 200, 1 accepted, 0 exceptions.
- `GET /api/docintel/documents/DOC-SMOKE-001` → 200, state `accepted`, confidence 0.90.
- `GET /project03/documents/DOC-SMOKE-001` → 200.
- Server stopped afterwards; temp DB deleted.

## 5. Bugs caught pre-ship (fixed before commit)

1. **`_DATE_LONG` regex had 3 capture groups; the transform only receives `group(1)`.** Long-form dates ("October 1, 2026") crashed extraction. Fixed to a single wrapping group; verified `October 1, 2026 → 2026-10-01` at 0.80.
2. **Field review tried `open → resolved` directly** — illegal under `EXCEPTION_WORKFLOW`. Added the `_resolve_exception` two-step helper (`open → investigating → resolved`). Caught by the first smoke test.
3. **An accepted-but-invalid field could not be corrected.** Payment method "crypto" extracted at 0.95 (auto-accepted) then failed validation; the accepted-field lock blocked correction. `correct` is now allowed on accepted fields **only** when an open `validation_failed` exception flags that field. Narrow escape hatch, tested both ways (allowed with the exception, `409`/ValueError without it).
4. **Duplicate document-event audit row from a stale row object.** `_recompute_doc_state` now re-fetches the current document row before transitioning, so a second transition in the same call cannot write a duplicate history row. Caught by the history assertions in `test_document_detail_with_fields_and_history` / service history tests.
5. **Two test-expectation bugs (tests, not code):** re-ingest counts 8 idempotent skips (7 unique + the within-batch repeat row), not 7; and the `duplicate_document` exception belongs to DOC-INV-001 (accepted), so it does not appear in DOC-INV-002's backlog entry. Both expectations corrected; the underlying behaviour is correct and idempotent.

## 6. Known limitations

- **Rejected fields block acceptance; the document stays in review.** This is deliberate (see ARCHITECTURE.md §3), but it means a reviewer who rejects a field must then either correct it or reject the document — there is no "accept the document without this field" path.
- **Aging buckets use the real clock** (`now=None` → `datetime.now(timezone.utc)`), so any future date-dependent test of P03's aging must freeze `now`. P03's own aging test passes an explicit `now`.
- **Extraction is regex-based.** It handles the fixture formats well and degrades gracefully (missing/unparseable), but it is not OCR and not a language model — by design.
