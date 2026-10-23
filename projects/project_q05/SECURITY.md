# Q05 — Security Notes

Scope: a local demonstration application. This is a security-conscious
design for its scope — it is **not** a claim of compliance, certification,
or production readiness.

## CSV injection (the core of this project's threat model)

CSV cells beginning with `=`, `+`, `-`, or `@` are interpreted as
formulas by spreadsheet applications — a classic CSV-injection vector
(e.g. `=cmd|'/C calc'!A0`, `=HYPERLINK("http://evil")`). Controls:

| Control | Implementation |
|---|---|
| Neutralize on ingest | `reconcile.sanitize_cell()` prefixes any cell whose first non-space character is a formula trigger with a single quote → rendered as literal text |
| Count reported | ingest results report `sanitized` so the operator sees what was neutralized |
| Formulas never reach money | `parse_amount_cents()` accepts only plain decimal numbers — `=1+1` is a row error, never an amount |
| Verified by test | `test_formula_cells_neutralized_in_db` (full table scan: no customer cell starts with a trigger char), `test_formula_amount_rejected_as_row_error`, `test_payment_note_formula_sanitized` |
| Documented | This file + RUNBOOK + README banner |

Residual risk: the sanitized text (`'=cmd|...`) is still *stored* — the
protection is at the spreadsheet-rendering layer. Exports from this demo
should go through the same sanitizer before being handed to Excel/Sheets.

## Synthetic data handling

- **All financial data is synthetic.** Amounts, names, and dates are
  invented. Nothing here may be presented as real accounting data.
- No PII exists in the demo (fictional stand-in names only), and the UI
  carries the "SYNTHETIC DEMO DATA" banner.
- Actor stamps are form/API fields — not authenticated identities. A
  real deployment needs authentication before `written_off` transitions
  mean anything.

## Other controls (shared with P01/P02/Q01–Q04/Q10)

| Threat | Control in place |
|---|---|
| Malformed / malicious input | Server-side validation; length/shape checks; row-level CSV errors |
| Duplicate / replay abuse | Natural-key idempotency (`invoice_id`/`payment_id` UNIQUE); within-batch duplicate → visible exception |
| Silent false matches | Exact pass is structural; fuzzy pass has a documented threshold; below-threshold candidates route to human review (zero silent auto-matches) |
| Information leakage via errors | Consistent error envelopes; generic 500; no tracebacks |
| SQL injection | Parameterized queries everywhere; CHECK constraints on `kind`/`state` |
| Fake data mistaken for real | "SYNTHETIC DEMO DATA" banner; fictional fixtures; README honest-status table |
| Unauthorized write-offs | `written_off` reachable only via an explicit, actor-stamped human transition; the system proposes, never posts |

## Accounting integrity — read before any real deployment

**This project is not accounting software and is not an audit tool.**
Amounts are plain decimals (no tax, no discounts, no multi-currency);
there is no GL, no posting, and no segregation of duties. Any real
deployment must be reviewed by an accountant and, for regulated
contexts, legal counsel — before it touches real books.
