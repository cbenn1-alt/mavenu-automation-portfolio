# Q06 — Test Plan

**Status vocabulary:** `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions). All data synthetic.

## Fixture design

Three sources, 54 invented contacts:

| Source | Label | Rows | Contents |
|---|---|---|---|
| A | `spreadsheet-customers` | 27 | 20 duplicate "left" sides, 5 adversarial left sides, 2 unique |
| B | `form-tool-signups` | 25 | 18 duplicate "right" sides, 5 adversarial right sides, 2 unique |
| C | `phone-export` | 2 | 2 duplicate "right" sides (dups 10, 20) |

- **20 planted TRUE duplicate pairs** (ids 1–20): typos (`Jonathon`,
  `Whitfeld`, `Beatirce`), format variants (`(701) 555-0100` vs
  `7015550100` vs `+1 (701) 555-0102`, `MARCUS bell`, `PRIYA.NAIR@EXAMPLE.COM`,
  `58104-1234`), token reordering (`Vasquez, Elena`), punctuation
  (`Mary-Jane O'Connor`), middle initial (`James P Carter`), and
  single-sided missing fields (email / address / ZIP).
- **5 adversarial NON-duplicates:** twins (`Emma`/`Emily Carter`, same
  household), Jr./Sr. (`Robert Hale Jr`/`Sr`, otherwise identical),
  shared phone (`Nina Patel`/`Omar Haddad`, family-plan number),
  household members (`Daniel`/`Grace Okafor`, spouses), similar names
  (`James Liu`/`James Lu`, scorer unit test only — no shared block).
- **4 unique contacts** sharing no block with anyone (O(n²)-bound test).

Expected bands at threshold 0.85 / 0.60: 20 match, 3 review
(twins, Jr/Sr, household), 1 no-match (shared phone). The Jr/Sr pair
scores 0.70 with the suffix penalty — it would score 0.90 (match) without
it, which is exactly the false-merge the penalty exists to prevent.

## Test inventory (`tests/test_entity_resolution.py`, 122 tests)

| Area | Tests | What is asserted |
|---|---|---|
| Normalizers | 9 + 63 parametrized | Each cleaner correct on cases; **idempotency**: `f(f(x)) == f(x)` for 7 cleaners × 10 inputs |
| Ingest | 6 | Happy path + normalized columns; missing columns fatal; row errors don't abort; re-ingest idempotent; formula sanitization; bad source kind rejected |
| Blocking | 4 | Key shapes; **coverage 20/20** planted pairs share a block; every pair shares a block (correctness); pairs < n·(n−1)/2, unique contacts generate zero pairs |
| Scoring | 6 | `decide` boundaries (0.85/0.849/0.60/0.599); weights sum to 1.00; determinism; scorer replaceability via `PairScorer` protocol; suffix penalty −0.20 moves Jr/Sr from match to review |
| Precision/recall | 1 | Recall ≥ 0.95 on 20 planted dups; precision computed honestly on match band |
| Adversarial | 6 | Twins → review + no auto-proposal; Jr/Sr → review; shared phone → no-match; household → review; similar names → no-match (unit); no proposals outside match band |
| Merge gate | 19 | Run never confirms (all `proposed` + signature-introspection guard); confirm requires human actor (blank/`system`/cased variants rejected); field plan + provenance applied; loser marked merged; double-confirm / nonexistent / already-merged rejected; **reversal restores exact pre-images** (full row-dict equality); reverse guards; reject changes nothing; human propose path for review pairs; no-match propose rejected; duplicate propose rejected; propose requires actor; audit trail events; provenance shape |
| Pipeline | 3 | `run_resolution` idempotent (0 new pairs/scored/proposals); `normalize_all` idempotent; `resolution_stats` snapshot |
| Rollback | 1 | **Real** migration down-step: apply → use → `rollback_migration` → er_* tables gone, other projects' tables intact → re-apply clean |

## Test inventory (`tests/test_entity_resolution_api.py`, 12 tests)

Upload (201 + counts), upload rejects bad kind / missing columns (409),
run (stats), stats endpoint, pairs band filter (+409 on bad band), pair
detail, pair 404, full human loop via API
(propose→confirm→audit→reverse, incl. `system`-actor rejection),
reject, human propose of a review pair, duplicate-propose guard, and page
rendering (`/project_q06`, `/project_q06/pairs`, `/project_q06/merges`,
detail pages, SYNTHETIC DEMO DATA banner).

## How to run

```bash
.venv/bin/python -m pytest tests/test_entity_resolution.py tests/test_entity_resolution_api.py -q  # expect: 134 passed
.venv/bin/python -m pytest tests/ -q                                                              # expect: 827 passed
```

## What is NOT tested (honest gaps)

- Real-world PII volumes/perf beyond fixture scale (54 contacts; the
  design bounds pairs by block structure, but no load test is claimed).
- Phonetic or learned matchers — out of scope by design.
- Concurrent writers (SQLite demo; single-process test client).
- Authenticated users — actor stamps are form/API fields by design.
