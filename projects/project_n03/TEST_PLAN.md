# N03 — Test Plan

Methodology (from the spec): structural assertions over the playbook
data (vocabulary closed, every step cites authority, no forbidden
operations); synthetic-case walkthroughs exercising preserve → report →
refer end-to-end with no real-world contact; adversarial checks on the
triage, vocabulary, content-discipline, and attribution rules; a real
migration rollback; full-suite regression. All tests run via the repo
venv: `cd ~/workspace/mavenu-portfolio && .venv/bin/python -m pytest tests/`.

## Test classes → spec criteria

| Class | What it proves | Spec criterion |
|---|---|---|
| `TestClosedVocabulary` | `ACTIONS` is exactly the 6 actions; `contact_suspect`/`investigate_suspect`/etc. rejected; no suspect-contact code path in module source; no network/messaging imports in module source; DB CHECK rejects `contact_suspect` on raw INSERT | M2 |
| `TestPlaybookAuthority` | 8 categories ↔ 8 playbooks; every step has a non-empty authority; every step action ∈ vocabulary; step_ids unique; every playbook covers preserve+report+refer; real sources named (NCMEC, IC3, StopBullying.gov, CCRI); CSAM playbook `no_investigation`; no step targets a suspect | M1, M5 |
| `TestNonGraphic` | Graphic terms rejected in intake summaries and findings; all 5 synthetic cases non-graphic and labeled SYNTHETIC | content discipline |
| `TestIntakeTriage` | Checklist opens from playbook; bad category/ref/role rejected; duplicate ref rejected; emergency → `EMERGENCY FIRST` guidance first; minor → safeguarding; CSAM → auto NCMEC referral + do-not-investigate guidance; sextortion → do-not-pay | M4, M5 |
| `TestChecklist` | Complete/skip (skip needs reason); unknown step rejected; close requires complete checklist; status counts per action | preserve→report→refer |
| `TestReferrals` | Unknown org rejected; referral moves stage to `referred`; guidance carries the "no outreach" note; directory has 10 entries each with what-to-bring | referral |
| `TestFindings` | `unknown` accepted; `verified` requires evidence; inference requires confidence; fact rejects confidence; bad claim_type/status rejected; lead vs verified separation | M6 |
| `TestSyntheticCasesEndToEnd` | All 5 cases: intake → complete preserve/report/safety steps → referral → close; each action class has ≥1 done step; CSAM: NCMEC referral exists at intake, playbook's only "investigate" mentions are prohibitions; swatting: emergency guidance first; cyberstalking: `unknown` finding recorded | M3, M4, M5, M6 |
| `TestChecklistAndGuide` | Preservation checklist items all cite authority; per-category addenda present; CSAM addendum never asks for the material; reporting guide has 9 entries all cited | preservation/reporting |
| `TestDemo` | `run_demo` completes: synthetic, Demo mode, stage closed, referral recorded, 2 findings | demo |
| `TestMigrationRollback` | Real rollback: rows → `rollback_migration("020_safeguard.sql")` → 4 tables gone, `schema_migrations` cleared → `run_migrations()` re-applies | M7 |
| API tests (`test_safeguard_api.py`) | Intake/list/detail; 422 on bad category, graphic summary, duplicate ref; emergency triage via API; CSAM auto-referral via API; checklist complete + skip-without-reason 422; referral endpoint + unknown-org 422; findings endpoint (unknown ok, verified-without-evidence 422); preservation/reporting-guide/directory endpoints; demo endpoint; 404 paths; all pages render with banner + nav | web/API |

## Negative / adversarial cases (explicit)

- Attempt `contact_suspect` / `investigate_suspect` / `message_suspect` /
  `track_suspect` / `confront_suspect` / `dox_suspect` → rejected.
- Raw SQL INSERT of `contact_suspect` into `safeguard_checklist` → CHECK violation.
- Intake with explicit-content terms → `ValidationError` (module) / 422 (API).
- Finding `verified` without `evidence_ref` → rejected; inference without confidence → rejected.
- Skip a checklist step without a reason → rejected.
- Close a case with pending steps → rejected.
- Playbook data containing "investigate the suspect" or "vigilante" would fail at import (validator) — asserted via `_check_no_forbidden_operations` over all steps.
- Unknown category / case / step / org_key → 404/422, never a silent default.

## Full-suite regression

The whole suite runs in chunks (see TEST_RESULTS.md) because the 512 MB
`/tmp` tmpfs fills during a single full run; `/tmp/pytest-of-root` is
cleared between chunks. No disk-backed TMPDIR is used.
