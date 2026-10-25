# S03 — Security

> Synthetic data only. This document covers contamination controls and
> handling discipline for the *demonstration*. It is not a guide to real
> forensic practice and not legal advice.

## Contamination controls (implemented)

1. **Read-only handling.** The source tree is opened `'rb'` and never
   written by any code path. `build_manifest`/`sha256_file` stream bytes;
   no function in `forensics.py` writes into the acquired tree.
2. **Hash at every stage.** Acquisition captures `start_hash` (listing
   snapshot) and `manifest_hash` (canonical per-file manifest). Each
   examination step, the timeline build, each hypothesis, and the report
   append a hash-chained custody entry
   (`SHA-256(prev_hash:step:payload)`).
3. **Tamper detection.** `verify_acquisition` re-hashes and reports
   mismatches/missing/extra files; `verify_chain` recomputes every link
   and names the first break. Tests cover modify, delete, add, chain
   rewrite, and chain splice.
4. **Single acquisition per case.** A second acquisition is rejected:
   re-imaging would fork the chain of custody. The procedure requires a
   new case instead.
5. **Authorization record required.** Intake refuses to open a case
   without an authorizer name and authorization reference (synthetic —
   a procedure artifact, not a legal instrument).

## Confirmation-bias control (implemented)

- A hypothesis is **rejected** unless it names both supporting and
  contradicting evidence. `none-found-after-review` is accepted only as
  an explicit, documented claim that a contradicting search was
  performed.
- `unresolved` is a valid hypothesis status and a valid finding — the
  workflow never forces a conclusion.

## Overclaiming controls (implemented)

- Inferences without a `low`/`medium`/`high` confidence level are
  **refused at write time** (`draft_report` raises; nothing is stored).
- Facts must cite evidence; the rendered report separates FACTS from
  INFERENCES under different headings.
- Every web page and API response is bannered synthetic/method-demo.

## Write-blocking concept (documented, not hardware)

Real forensic acquisition uses hardware write-blockers so the source
device cannot be altered. This project documents the concept and
implements its software analogue — read-only opens, no writes to the
source, hash verification — against fixture files. It does not interact
with block devices and must never be presented as equivalent to a real
write-blocked acquisition.

## API input hardening

- `POST …/acquire` accepts only a plain directory name (`/` and leading
  `.` rejected); the fixture must exist under `SYNTHETIC_CASES_DIR`.
- All JSON bodies validated; `ValidationError` → 422, `ForensicsError`
  (state violations) → 409; unexpected errors → 500 without internals.

## Residual risks (honest)

1. **Not a forensic tool.** Nothing here qualifies as forensic software
   for real incidents; presenting it as such would be dishonest and
   potentially harmful.
2. **Synthetic authorization ≠ legal authorization.** The intake record
   teaches the *habit* of requiring authorization; it confers none.
3. **Fixture realism is bounded.** MAC times, logs, and carving are
   simplified models of real filesystem forensics.
4. **The demo writes fixture trees** under `synthetic_cases/` (or
   `MAVENU_SYNTHETIC_CASES`). They are inert text files, but operators
   should know the demo creates them.
5. **No access-control bypass exists** in this module by design; keep it
   that way — any future "decrypt/unlock" helper would violate the
   project's ethical hard line.
