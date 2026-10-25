# Q06 — Requirements

**Status:** Implemented · Tested (2026-10-23). Every requirement below is
covered by automated tests; the evidence matrix maps each to its tests.

## Functional requirements

### R1 — Multi-source CSV ingest
- Ingest contact CSVs from named sources (spreadsheet, form tool, phone
  export, other). Columns: `name,phone,email,address,zip,notes`.
- Missing required columns abort the ingest with a clear error (fatal).
- Row problems (e.g. blank name) are collected as row-level errors with
  1-based row numbers; they never abort the batch.
- CSV-formula cells (`=`, `+`, `-`, `@` leading) are neutralized with a
  leading quote on ingest.
- Re-ingesting the same CSV under the same source label inserts zero new
  rows (idempotent on `(source_id, source_row)`).

### R2 — Deterministic normalization
- Cleaners for name, phone, email, address, ZIP (see `normalize.py`):
  case folding, whitespace collapsing, phone digit extraction with NANP
  `+1` handling and `(XXX) XXX-XXXX` rendering, email lowercasing,
  street-suffix canonicalization (`St`→`Street`, `Ave`→`Avenue`, …),
  ZIP+4 → 5-digit ZIP.
- **Idempotency:** `normalize(normalize(x)) == normalize(x)` for every
  cleaner and every input (tested over a parametrized input set).
- Normalization never invents data: unverifiable phone formats are kept as
  bare digits, never reformatted into a guess.

### R3 — Blocking (no O(n²))
- Candidate pairs are generated ONLY from shared blocking keys:
  `phone:<digits>`, `email:<lowercased>`, `zipname:<zip>:<surname>`.
- There is deliberately no all-pairs fallback. Pair count must stay
  strictly below n·(n−1)/2 on fixtures (tested), and every generated pair
  must share at least one block (tested — blocking correctness).
- Block coverage on the planted-duplicate fixture: 100% of true duplicate
  pairs share ≥1 block (measured 20/20).

### R4 — Pairwise scoring with documented weights
- Weighted feature scorer behind the replaceable `PairScorer` protocol
  (same seam pattern as P01's `LeadClassifier` and Q05's matcher config):
  - name similarity (difflib ratio on token-sorted `name_key`): **0.45**
  - phone exact (digits equal, both non-empty): **0.25**
  - email exact (both non-empty): **0.15**
  - address similarity (difflib ratio on `address_norm`): **0.10**
  - ZIP exact (both non-empty): **0.05**
  - weights sum to 1.00; total quantized to 2 decimals, clamped 0..1.
- Generational-suffix conflict (Jr/Sr/II/III/IV/V present on one side only
  or differing): **−0.20 penalty** (documented adversarial guard).
- Thresholds: **match ≥ 0.85**, **review ≥ 0.60**, else **no-match**.
  Boundaries are inclusive and boundary-tested.
- The scorer is deterministic: identical rows → identical score.
- The scorer is a transparent formula, never described as a trained model.

### R5 — Match / review / no-match banding
- Every scored pair lands in exactly one band, recorded with its component
  breakdown and human-readable reasons.
- Match band → a merge *proposal* is created (state `proposed`).
- Review band → visible in the human review queue; a human may propose a
  merge explicitly.
- No-match band → recorded; can never be proposed for merging
  (rejected in code).

### R6 — Human-confirmed merges only
- `run_resolution` creates proposals ONLY in state `proposed`. There is no
  auto-confirm parameter and no auto-confirm code path (asserted by tests,
  including a signature-introspection guard).
- `confirm_merge` requires a non-blank, non-`"system"` human actor; blank
  and `"system"` are rejected with an explicit error.
- Double-confirm, confirm-after-reverse, and confirm touching an
  already-merged record are all rejected.

### R7 — Full before/after audit of every merge
- Each confirmed merge writes an audit row with: the winner's and loser's
  FULL pre-merge row images, per-field provenance (winning value, source
  record id, reason), actor, and timestamp.
- `reverse_merge` restores both records' exact pre-images (tested with
  full row-dict equality — 100% reversibility), moves the proposal to
  `reversed`, and stamps the audit row. Audit rows are never deleted.
- Every consequential action (ingest, resolve, propose, confirm, reject,
  reverse) is also an append-only, actor-stamped row in `er_events` plus a
  structured JSON stdout log line.

### R8 — Synthetic data only
- Every fixture contact is invented. No real names, phone numbers, emails,
  or addresses exist anywhere in code, tests, or docs.
- The demo UI carries the SYNTHETIC DEMO DATA banner.

## Non-functional requirements

### N1 — Measurable criteria (spec §2)
- Recall ≥ 95% on planted-duplicate fixtures at the chosen threshold
  (0.85), with precision reported honestly. **Measured: recall 1.000
  (20/20), precision 1.000 (20/20).**
- 100% merge reversibility (exact pre-image restore, tested).
- Normalization idempotent (tested per cleaner).

### N2 — Adversarial fixtures
- Twins (same household, near-identical names) → review, never auto-merge.
- Jr./Sr. (same name + suffix, otherwise identical) → review via the
  suffix penalty (would score 0.90/match without it — tested).
- Shared phone (family plan, different people) → no-match.
- Household members (spouses, same address/phone) → review.
- Similar names, different people → no-match.

### N3 — Rollback
- Migration `009_entity_resolution.sql` ships with a tested down-step
  (`009_entity_resolution.down.sql`); rollback is exercised for real in the
  test suite (apply → use → roll back → re-apply).

### N4 — Stack & cost
- Python 3.12 stdlib only at runtime (`sqlite3`, `csv`, `difflib`,
  `wsgiref`); pytest for tests. $0 spend, no network calls.

## Out of scope (explicitly not required)
- Real PII handling beyond synthetic fixtures (hashing strategy is
  documented in SECURITY.md for real deployments; not implemented here).
- Phonetic matching (Soundex/Metaphone), learned match models, or
  cross-database global dedup at scale.
- Authenticated multi-user access; actor stamps are form/API fields.
