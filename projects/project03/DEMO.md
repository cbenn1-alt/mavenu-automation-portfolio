# Project P03 — Demo

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## Setup (2 minutes)

```bash
cd ~/workspace/mavenu-portfolio
python3 run.py --port 8000 --db /tmp/p03-demo.db
```

## Script

### 1. Upload the fixture

Open `http://localhost:8000/project03`. Paste the `DOCS_JSON` fixture from `tests/test_docintel.py` (7 documents + 1 within-batch duplicate) into the upload box, choose **JSON**, and submit. The upload report shows **7 inserted, 1 duplicate_document exception, 0 row errors**.

Or via API:

```bash
curl -X POST localhost:8000/api/docintel/upload -H 'Content-Type: application/json' \
  -d '{"format":"json","payload":"<paste DOCS_JSON here>","actor":"demo"}'
```

### 2. Extract

Click **Extract** (or `POST /api/docintel/extract`). The run report shows: **7 documents, 3 accepted, 4 needs_review, 4 exceptions raised** (the duplicate was raised at ingest).

### 3. Read the summary

`/project03/reports` (or `GET /api/docintel/summary`):

- 7 documents: 3 accepted, 4 needs_review
- 33 fields: 26 accepted, 1 proposed, 0 rejected, 6 missing
- Accepted money: **$52,422.89**
- 5 open exceptions — one of each kind

### 4. Work the queue (the interesting part)

**DOC-INV-002** — low confidence. The vendor was taken from the first line ("Brightfield Services") at 0.60, so the field is `proposed`. Open the document, click **Accept** on the vendor field. The document flips to `accepted` and the `low_confidence` exception resolves.

**DOC-RCP-002** — invalid but confident. Payment method "crypto" was extracted at 0.95 (high confidence) but fails the known-method validation, so a `validation_failed` exception blocks the document. Open the document, **Correct** the payment method to `card`. The exception resolves and the document flips to `accepted`. Try correcting an accepted field on DOC-INV-001 first — the UI offers no correct action, and the API returns `409`: the lock is real.

**DOC-INV-003** — missing field. No due date in the text. **Correct** the missing due_date to `2026-10-17`; the `missing_field` exception resolves and the document flips to `accepted`.

**DOC-GARBAGE-001** — unparseable. No field matched. Open the document and click **Reject document**.

### 5. Close

Back on `/project03/reports`: the review backlog is empty and only **1 open exception** remains — the `duplicate_document` exception for DOC-INV-001. It is a record-keeping item, not a blocker: open it in the exception queue and transition it `open → investigating → resolved` to close it out.

## Talking points

- Every extraction carries its provenance: rule, source line, raw text, confidence. Nothing is a black box.
- The human gate is real: below-threshold fields cannot self-accept, and accepted fields cannot be silently rewritten.
- Money is Decimal end-to-end; proposed values never enter a total.
