# N03 — Evidence Matrix

Every public claim → the test or artifact that backs it, or its honest label.

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | Action vocabulary is closed to 6 actions | **Tested** | `TestClosedVocabulary` — exact tuple match; 9 out-of-vocabulary actions (incl. `contact_suspect`, `investigate_suspect`) rejected (M2) |
| 2 | No suspect-investigation/contact code path exists | **Tested** | `test_no_suspect_contact_code_path_exists` — identifier scan of module source |
| 3 | No network/messaging code in the module | **Tested** | `test_no_network_or_messaging_imports` — import-line scan; engine cannot contact anyone by construction |
| 4 | DB layer rejects out-of-vocabulary actions | **Tested** | `test_db_check_constraint_rejects_out_of_vocabulary_action` — raw INSERT of `contact_suspect` → CHECK violation |
| 5 | Every playbook step cites an authority | **Tested** | `test_every_step_has_a_cited_authority` — structural assertion over all 8 playbooks, all steps (M1) |
| 6 | All 8 categories have preserve → report → refer playbooks | **Tested** | `test_all_eight_categories_have_playbooks`, `test_every_playbook_covers_preserve_report_refer` |
| 7 | Real public sources cited by name | **Tested** | `test_real_public_sources_cited_by_name` — NCMEC CyberTipline, FBI IC3, StopBullying.gov, CCRI named in authorities |
| 8 | CSAM playbook is no-investigation | **Tested** | `test_csam_playbook_marked_no_investigation`; its only "investigate" mentions are prohibitions |
| 9 | Immediate danger → emergency-services guidance first | **Tested** | `test_immediate_danger_routes_to_emergency_first` (module + API); swatting synthetic case (M4) |
| 10 | Minor involvement → safeguarding guidance | **Tested** | `test_minor_involvement_triggers_safeguarding` |
| 11 | CSAM intake auto-generates NCMEC referral, no investigation | **Tested** | `test_csam_intake_refers_immediately` (module + API `test_csam_intake_auto_refers_ncmec`); `test_csam_case_refers_immediately_no_investigation` (M5) |
| 12 | Sextortion guidance says do-not-pay | **Tested** | `test_sextortion_guidance_says_do_not_pay` |
| 13 | Graphic content rejected in summaries/findings | **Tested** | `TestNonGraphic` — intake + finding + API 422 paths |
| 14 | All 5 synthetic cases are non-graphic, labeled SYNTHETIC | **Tested** | `test_all_synthetic_cases_are_non_graphic` |
| 15 | Checklist tracks preserve → report → refer per case | **Tested** | `TestChecklist` — complete/skip/reason-required/close-gate/status counts |
| 16 | Referrals are guidance text; no outreach performed | **Tested** | `test_referral_moves_stage_and_lists` — "no outreach" note asserted; SECURITY.md residual risk #1 |
| 17 | Referral directory: 10 template entries, each with what-to-bring | **Tested** | `test_directory_has_ten_entries_and_template_note` |
| 18 | "Unknown" is an acceptable finding | **Tested** | `test_unknown_is_an_acceptable_finding` (module + API) (M6) |
| 19 | Verified findings require cited evidence | **Tested** | `test_verified_requires_evidence` (module + API 422) (M6) |
| 20 | Inferences require confidence; facts reject it | **Tested** | `test_inference_requires_confidence`, `test_fact_cannot_carry_confidence` (M6) |
| 21 | All 5 synthetic cases complete preserve → report → refer | **Tested** | `TestSyntheticCasesEndToEnd` — each case ≥1 done step per action class; close reached (M3) |
| 22 | Preservation checklist items all cite authority | **Tested** | `test_preservation_checklist_generic`, `test_preservation_addenda_per_category` |
| 23 | Reporting guide covers platforms + NCMEC + IC3, all cited | **Tested** | `test_reporting_guide_covers_platforms_and_ncmec` — 9 entries |
| 24 | Guided demo runs end-to-end | **Tested** | `TestDemo` + `test_demo_api` — synthetic, closed, referral recorded |
| 25 | Migration rollback tested for real | **Tested** | `test_rollback_for_real` (2026-10-23, Python 3.12.3/pytest 9.1.1/Linux) — 4 tables dropped, `schema_migrations` cleared, re-apply clean (M7) |
| 26 | No regressions | **Tested** | Full suite (TEST_RESULTS.md) (M8) |
| 27 | All data synthetic; no PII | **Tested** | Invented case_refs/summaries throughout; SYNTHETIC labels asserted |
| 28 | Referral directory as live contact data | **NOT claimed** | Labeled a template; every referral record says "verify current channels yourself" |
| 29 | Platform flows as guaranteed current | **NOT claimed** | Authorities named, not link-guaranteed; docs state flows change |
| 30 | Casework experience / investigations performed | **NOT claimed** | README "NOT claimed" row; the framework structurally cannot investigate |
| 31 | Production deployment / real users | **NOT claimed** | README "NOT claimed" row |
| 32 | Legal advice | **NOT claimed** | README + SECURITY.md: legal information only |

Status vocabulary used above: **Implemented**, **Tested**, **Simulated**, **Demo** — nothing else.
