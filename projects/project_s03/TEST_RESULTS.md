# S03 — Test Results

**Run date:** 2026-10-23 (21:44 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
(run in 3 chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run; no disk-backed
TMPDIR used)

> **⚠ SYNTHETIC DATA ONLY — METHOD DEMONSTRATION, NOT CASEWORK.**
> Every fixture, case, log line, and ground-truth record is invented.

## Result

**1298 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| S03 new (`tests/test_forensics.py`) | 63 | 63 passed |
| S03 new (`tests/test_forensics_api.py`) | 24 | 24 passed |
| P01 + P02 + Q01–Q10 + S01 + S02 + S05 prior (1211) | 1211 | 1211 passed, unchanged |

Chunk breakdown: 459 + 446 + 393 = 1298.

## Measurable criteria — verified

| Criterion (REQUIREMENTS.md) | Result |
|---|---|
| M1 — 100% of planted artifacts recovered on fixtures | File listing: 3/3 planted files recovered; carving: 1/1 planted deleted file recovered with hash match (`TestExamination`) — **Tested** |
| M2 — zero hash mismatches across the chain | Untouched fixture: `verify_acquisition` ok with 0 mismatches / 0 missing / 0 extra; `verify_chain` ok end-to-end. Tamper cases: modify → 1 mismatch named; delete → 1 missing named; add → 1 extra named; chain rewrite and chain splice each detected with the breaking step named (`TestIntegrity`) — **Tested** |
| M3 — timeline matches ground truth within documented tolerance | Fixture: 5/5 ground-truth events matched within 60 s → score 1.0. Tolerance boundary: 59 s matches, 61 s does not; wrong event type does not match (`TestTimeline`) — **Tested** |
| M4 — every inference in reports carries a confidence level | `draft_report` refuses inferences without confidence (module test + API 422); bad confidence value → audit error; fact without evidence → error; fact with confidence → warning only; `unresolved` accepted as a finding (`TestReport`, `TestReportApi`) — **Tested** |
| M5 — confirmation-bias control | Hypothesis without contradicting evidence → `ValidationError` (module) / 422 (API); `none-found-after-review` accepted as a documented explicit claim — **Tested** |
| M6 — rollback tested for real | `test_migration_rollback_for_real`: `016_forensics.sql` applied → rows inserted → `rollback_migration("016_forensics.sql")` → all 7 S03 tables dropped and the `schema_migrations` record removed → `run_migrations()` re-applies `016_forensics.sql` cleanly — **Tested**, 2026-10-23, Python 3.12.3 / pytest 9.1.1 / Linux |
| M7 — no regressions | 1211/1211 prior tests pass unchanged — **Tested** |

## Notes

- The timeline tolerance (60 s) is a documented fixture parameter (clock
  skew between the synthetic filesystem layer and the synthetic log),
  verified at its boundary (59 s / 61 s) — not a forensic standard.
- The `verify` API endpoint re-hashes the original fixture tree; the
  demo records the fixture directory in the acquisition's source label
  so verification resolves it. If the tree is removed, the endpoint
  returns 404 rather than a false integrity verdict.
