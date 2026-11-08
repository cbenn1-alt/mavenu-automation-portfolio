# Project P03 — AI Document Intelligence & Exception Management

> **Status: Implemented + tested (Gate C ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval, no real documents, no real PII.
>
> Extraction is **deterministic, rule-based** pattern matching with per-field confidence and provenance. It is labelled as such throughout — this project makes **no black-box AI claims**.

## What it does

P03 ingests documents (invoices, receipts, contracts) as JSON or CSV batches or single text, extracts named fields with a deterministic rule-based extractor, validates the extracted values, and routes anything that fails validation, falls below the confidence threshold, or cannot be parsed into a human-gated exception queue. A document is only **accepted** when every field is either accepted by a human or auto-accepted at or above the confidence threshold; there is **no auto-accept path for below-threshold fields** — those stay `proposed` until a human accepts, corrects, or rejects them.

Three modules implement the pipeline:

- **Ingest** — `src/mavenu/docintel.py`: batch ingest (JSON/CSV), single-text ingest, idempotent re-ingest on `doc_id`, row-level error reporting, spreadsheet-formula sanitisation at the boundary (`reconcile.sanitize_cell`).
- **Extract** — `src/mavenu/extraction.py`: deterministic rule-based field extraction with per-field confidence (`0.00–1.00`), provenance (`rule_id`, 1-based source line, raw matched text), a confidence threshold of **0.80**, and a validation-rule set (amounts positive, due ≥ issued, invoice-number format, receipt date not in the future, payment method known, contract term positive, contract value non-negative).
- **Exception queue** — reuses the Q05 exception workflow (`open → investigating → resolved | written_off`) with actor stamps and an audit trail on every transition; plus document state transitions (`ingested → needs_review | accepted | rejected`, `needs_review → accepted | rejected`).

## Documents in this folder

| Doc | Purpose |
|---|---|
| `REQUIREMENTS.md` | Functional + non-functional requirements, acceptance criteria |
| `ARCHITECTURE.md` | Module map, data model, state machines, key decisions |
| `TEST_PLAN.md` | Test strategy, fixture design, coverage map |
| `TEST_RESULTS.md` | Exact test counts and the hand-computed fixture oracle |
| `SECURITY.md` | Threat model, input validation, SQL safety, audit logging |
| `RUNBOOK.md` | How to run, operate, and roll back (migration down-step) |
| `DEMO.md` | Demo script against the synthetic fixture |
| `EVIDENCE_MATRIX.md` | Claim → artifact mapping |

## Quick start

```bash
python3 run.py --port 8000 --db data/app.db
```

Then open **P03 Documents** (`/project03/documents`) and **P03 Exceptions** (`/project03/exceptions`), or use the JSON API:

```bash
curl -X POST localhost:8000/api/docintel/upload \
  -H 'Content-Type: application/json' \
  -d '{"format":"json","payload":"<json array>","actor":"demo"}'
curl -X POST localhost:8000/api/docintel/extract -H 'Content-Type: application/json' -d '{"actor":"demo"}'
curl localhost:8000/api/docintel/summary
```

Upload the fixture in `tests/test_docintel.py` (`DOCS_JSON`) for the canonical demo: 7 documents, 3 accepted / 4 needs_review, 33 fields, accepted money $52,422.89, 5 open exceptions.

## Honest-status banner

- **Implemented + tested (Gate C ✓)** — 73 tests green (58 service + 15 API).
- **Synthetic/demo data only** — every document in tests and fixtures is invented; no real vendor, invoice, or person.
- **No production deployment, no real clients, no bank approval.**
- **No black-box AI** — extraction is deterministic rules, fully inspectable in `src/mavenu/extraction.py`.
