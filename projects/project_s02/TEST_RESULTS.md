# S02 — Test Results

**Run date:** 2026-10-23 (21:50 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/pytest tests/`
(run in 3 chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run; no disk-backed
TMPDIR used)

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**

## Result

**1124 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| S02 new (`tests/test_ossec.py`) | 53 | 53 passed |
| S02 new (`tests/test_ossec_api.py`) | 17 | 17 passed |
| P01 + P02 + Q01–Q10 + S01 prior (1054) | 1054 | 1054 passed, unchanged |

Chunk breakdown: 379 + 375 + 370 = 1124.

## Measurable criteria — verified

| Criterion (REQUIREMENTS.md) | Result |
|---|---|
| M1 — 100% of findings carry detection + remediation + verification | 6/6 records carry all three (structural assert) — **Tested** |
| M2 — every baseline item fails on vulnerable, passes on hardened | 15/15 parametrized tests pass — **Tested** |
| M3 — remediation simulator: fix → re-verify → pass, before/after recorded | 6 finding-level + full-report tests pass — **Tested** |
| M4 — coverage audit: every item has a verification function | `coverage_audit() == []` — **Tested** |
| M5 — tampered state caught by re-verification | 4 adversarial tests pass — **Tested** |
| M6 — documented pass rate on lab states | Vulnerable fixture **0/15 (0%)**; hardened fixture **15/15 (100%)** — measured |
| M7 — zero lab-scope violations | Design (no I/O in `ossec.py`); verified by inspection — **Implemented** |
| M8 — rollback tested for real | `test_migration_rollback_for_real`: `014_ossec.sql` applied → S02 tables present → finding + baseline run inserted → `rollback_migration("014_ossec.sql")` → all three S02 tables dropped and the `schema_migrations` record removed → `run_migrations()` re-applies `014_ossec.sql` cleanly — **Tested**, 2026-10-23, Python 3.12.3 / pytest 9.1.1 / Linux |

## Notes

- Verification is pure: `test_verify_does_not_mutate_state` asserts the
  vulnerable fixture is unchanged after evaluation, so Snapshot A stays a
  stable reference.
- The hardened fixture is *derived* by the simulator, not hand-written:
  `hardened_state()` = `before_after_report(vulnerable_state())` output,
  so a drift between "fix" and "fixed state" is impossible by construction.
