# S04 — Test Results

**Run date:** 2026-10-23 (21:54 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
(run in 3 chunks of 15 test files with `/tmp/pytest-of-root` cleared
between chunks — the 512 MB `/tmp` tmpfs fills during a single
full-suite run; no disk-backed TMPDIR used)

> **⚠ SYNTHETIC DATA ONLY — SYSTEM DEMONSTRATION, NOT LEGAL AUTHORITY.**
> Every fixture, tag, hash, actor, transfer, and incident is invented.

## Result

**1363 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| S04 new (`tests/test_custody.py`) | 47 | 47 passed |
| S04 new (`tests/test_custody_api.py`) | 18 | 18 passed |
| P01 + P02 + Q01–Q10 + S01–S03 + S05 prior (1298) | 1298 | 1298 passed, unchanged |

Chunk breakdown: 524 + 483 + 356 = 1363.

## Measurable criteria — verified

| Criterion (REQUIREMENTS.md) | Result |
|---|---|
| M1 — 100% tamper detection on adversarial fixtures | 8/8 tamper modes detected (`TestAdversarialFixtures`): alter payload / actor / timestamp / seq / item_id / event type → `hash_mismatch` or `prev_hash_link`; delete middle entry → break; backdated insert → `seq_gap`/`hash_mismatch`/`backdated_timestamp`; alter-payload-then-recompute-hash → next row's link breaks. **Tested** |
| M2 — zero transfers without dual hash verification | `assert_dual_hash_verified`: every completed transfer has hash_out AND hash_in present and equal to the acquisition SHA-256; an adversarially-planted completed row with missing `hash_in` is flagged. Hash-in before hash-out is refused (module `CustodyError`, API 409). `TestTransfers` + API tests. **Tested** |
| M3 — every synthetic-case artifact traceable through the custody chain | `full_trace` per item in `TestSyntheticCaseWalkthrough`: intake entry present, transfers complete with dual-hash entries, disposition entries for the 3 terminal items; seeded statuses exactly `{EV-047-001: archived, EV-047-002: returned, EV-047-003: destroyed, EV-047-004: in_custody}`; global chain verifies after the whole walkthrough (44 entries). **Tested** |
| M4 — access-log completeness audit | `audit_access_coverage` clean (0 gaps, 11 checks) on the seeded case; deleting a transfer_in row → exactly 1 gap named. **Tested** |
| M5 — rollback tested for real | `test_rollback_for_real`: `017_custody.sql` applied → synthetic case seeded (4 items) → `rollback_migration("017_custody.sql")` → all 7 S04 tables dropped and the `schema_migrations` record removed → `run_migrations()` re-applies `017_custody.sql` cleanly. **Tested**, 2026-10-23, Python 3.12.3 / pytest 9.1.1 / Linux |
| M6 — no regressions | 1298/1298 prior tests pass unchanged. **Tested** |

## Notes

- The deliberate hash-mismatch drill (EV-047-004) is part of the seeded
  case: rejected transfer #4, open quarantine incident, resolution,
  then a clean re-transfer — all asserted in
  `TestSyntheticCaseWalkthrough::test_drill_transfer_traceable`.
- All five forms render from the live data model and carry the
  `SYNTHETIC` banner + print CSS; asserted in
  `TestPages::test_form_pages_printable`.
- Known boundary (SECURITY.md): a total consistent rewrite of the log
  by a privileged operator is structurally indistinguishable from the
  truth (trusted-admin model) — asserted as documented behavior, not a
  failure.
