# Q08 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/test_tagger.py tests/test_reviews.py tests/test_reviews_api.py -q`
from the repo root.

## Latest full run — 2026-10-23

The suite was run in three chunks on 2026-10-23 (Q08 files; baseline
files half 1; baseline files half 2), because a single full run's
per-test `tmp_path` databases exceed this host's 512 MB /tmp tmpfs —
an environment limit, not a code issue (same recurring /tmp pressure
recorded in `AGENTS.md`; one earlier full-run attempt also wedged in a
btrfs writeback stall when pointed at a disk-backed tmp dir, and was
killed and re-run in chunks instead).

| Chunk | Result |
|---|---|
| Q08: `test_tagger.py` + `test_reviews.py` + `test_reviews_api.py` | **65 passed** |
| Baseline files (half 1: approval→kpi) | **490 passed** |
| Baseline files (half 2: leads→workflow) | **379 passed** |
| **Full suite** | **934 passed, 0 failed** (869 baseline + 65 Q08) |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux 7.0.0-39-generic. Run date: 2026-10-23.

## Q08 module breakdown

| Module | Tests | Result |
|---|---|---|
| `tests/test_tagger.py` | 19 | 19 passed |
| `tests/test_reviews.py` | 32 | 32 passed |
| `tests/test_reviews_api.py` | 14 | 14 passed |
| **Q08 total** | **65** | **65 passed, 0 failed** |
| Baseline regression (all prior projects) | 869 | 869 passed |
| **Full suite** | **934** | **934 passed, 0 failed** |

## Measured tagger performance (recorded from the run)

200-row synthetic fixture (`tests/q08_review_fixtures.py`), lexicon v1.0:

| Category | Precision | Recall | tp | fp | fn |
|---|---|---|---|---|---|
| sentiment: positive | 1.000 | 1.000 | 60 | 0 | 0 |
| sentiment: negative | 1.000 | 1.000 | 60 | 0 | 0 |
| topic: service | 0.791 | 0.829 | 68 | 18 | 14 |
| topic: price | 0.821 | 0.920 | 46 | 10 | 4 |
| topic: punctuality | 0.935 | 1.000 | 58 | 4 | 0 |
| topic: workmanship | 0.857 | 0.857 | 48 | 8 | 8 |

- Uncertainty flag: 60/60 weak-evidence rows flagged; 0/120 confident
  rows wrongly flagged.
- Severity-routing recall on critical (1★) fixtures: **52/52 → 100%**
  routed `owner_alert`/critical.
- Fixture routing agreement: 200/200 rows routed to their expected queue.
- All 40 adversarial rows (sarcasm + mixed sentiment) reach a
  human-attended queue; zero auto-resolved, zero dropped.

These numbers describe the lexicon tagger on this fabricated fixture.
They are not a claim about real-world review data.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_reviews.py::test_migration_011_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `011_reviews.sql` applied (in the migrations table); lexicons seeded;
   review ingested, tagged, routed; draft generated; SLA breach recorded.
2. `rollback_migration(conn, "011_reviews.sql")` → returned True; all
   seven `review_*` tables dropped; migration record removed.
3. Verified other projects' tables still present (`leads`, …).
4. `run_migrations(conn)` re-applied `011_reviews.sql` cleanly.
