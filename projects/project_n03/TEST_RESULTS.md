# N03 — Test Results

**Run date:** 2026-10-23 (22:24 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
(run in 5 chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run; no disk-backed
TMPDIR used)

> **⚠ SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, NOT CASEWORK.**
> Every case, summary, finding, and referral is invented. This framework
> refers; it does not pursue.

## Result

**1570 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| N03 new (`tests/test_safeguard.py`) | 61 | 61 passed |
| N03 new (`tests/test_safeguard_api.py`) | 25 | 25 passed |
| Prior (P01 + P02 + Q01–Q10 + S01–S05 + N01 + N02 = 1484) | 1484 | 1484 passed, unchanged |

Chunk breakdown: 543 + 273 + 301 + 442 + 11 = 1570.

Note: one ad-hoc chunk combination (estimates→reconciliation in a
single process) produced errors in `test_reconciliation.py` — verified
**pre-existing** by re-running the identical combination on the
pristine tree with all N03 changes stashed (`git stash -u`): same
errors without N03. The chunk splits above avoid that interaction;
every chunk ran green.

## Measurable criteria — verified

| Criterion (REQUIREMENTS.md) | Result |
|---|---|
| M1 — every playbook step cites its authority | Structural assertion over all 8 playbooks / all steps: 0 steps without a non-empty authority (`TestPlaybookAuthority`) — **Tested** |
| M2 — action vocabulary closed | `validate_action` rejects 9 out-of-vocabulary actions incl. `contact_suspect`/`investigate_suspect`; no suspect-contact identifier in module source; no network/messaging imports in module source; raw SQL INSERT of `contact_suspect` → CHECK violation (`TestClosedVocabulary`) — **Tested** |
| M3 — synthetic cases complete preserve → report → refer | All 5 cases run intake → checklist → referral → close; each action class (preserve/report/refer) has ≥1 completed step; no real-world contact at any point (`TestSyntheticCasesEndToEnd`) — **Tested** |
| M4 — immediate danger → emergency guidance first | `safety_status=emergency`; guidance[0] is the EMERGENCY FIRST / 911 message (module + API; swatting case) — **Tested** |
| M5 — CSAM → NCMEC referral, no investigation | NCMEC CyberTipline referral auto-generated at intake before any checklist work; playbook `no_investigation=True`; its only "investigate" mentions are prohibitions; import-time validator rejects forbidden operational phrases (module + API) — **Tested** |
| M6 — attribution discipline | `unknown` accepted as a finding (module + API); `verified` without `evidence_ref` rejected; inference without confidence rejected; fact with confidence rejected (`TestFindings`) — **Tested** |
| M7 — rollback tested for real | `test_rollback_for_real`: `020_safeguard.sql` applied → row inserted → `rollback_migration("020_safeguard.sql")` → all 4 N03 tables dropped and the `schema_migrations` record removed → `run_migrations()` re-applies `020_safeguard.sql` cleanly — **Tested**, 2026-10-23, Python 3.12.3 / pytest 9.1.1 / Linux |
| M8 — no regressions | 1484/1484 prior tests pass unchanged — **Tested** |

## Notes

- The non-graphic content filter is a coarse term list — a safety net,
  documented as such in SECURITY.md; the synthetic cases themselves
  are hand-written non-graphic.
- Referral directory entries are a template; every generated referral
  record carries the "verify current channels yourself; no outreach
  performed" note.
- Platform reporting flows are described from public help centers;
  authorities are named, not link-guaranteed (flows change).
