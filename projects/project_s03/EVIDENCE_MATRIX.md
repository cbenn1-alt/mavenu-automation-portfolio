# S03 — Evidence Matrix

Every public claim → the test or artifact that backs it, or its honest label.

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | Case intake requires a synthetic authorization record + handling plan | **Tested** | `TestIntake` — missing authorizer/auth-ref/plan-steps → `ValidationError`; `POST /api/forensics/cases` 422 path |
| 2 | Acquisition hashes every file with SHA-256 (stdlib) and captures start/end hashes | **Tested** | `TestAcquisition` — 3 files, 64-hex `start_hash`/`manifest_hash`, manifest deterministic across runs |
| 3 | Re-acquisition on the same case is rejected (chain-of-custody discipline) | **Tested** | `test_reacquire_rejected`; API second acquire → 409 |
| 4 | Post-acquisition modification is detectable | **Tested** | `TestIntegrity` — modify/delete/add each detected and named; `verify` API endpoint |
| 5 | Hash chain links every handoff and detects rewrite/reorder | **Tested** | `test_chain_tamper_detected`, `test_chain_reorder_detected`; `/api/forensics/cases/<id>/chain` |
| 6 | 100% planted-artifact recovery on fixtures | **Tested** | 3/3 files via listing, 1/1 deleted via carving vs. `_ground_truth.json` (M1) |
| 7 | MAC times come from the synthetic metadata layer | **Tested** | `test_mac_times_come_from_meta` |
| 8 | Log parser handles valid lines, skips garbage | **Tested** | 5/5 fixture lines parsed; 5 garbage classes → `None`; whole-log + garbage → 5 events |
| 9 | Carving verifies recovered bytes against expected hash | **Tested** | `hash_match` true on fixture; wrong expectation → `hash_match: False` recorded (not silent); out-of-bounds → `ValidationError` |
| 10 | Timeline is chronological and scored against ground truth | **Tested** | 5/5 within 60 s → 1.0; 59 s/61 s boundary; type-mismatch → no match (M3) |
| 11 | Hypotheses require supporting AND contradicting evidence | **Tested** | Missing either → rejected (module + API 422); `supported`/`refuted`/`unresolved` transitions |
| 12 | Inferences without confidence are refused at write time | **Tested** | `draft_report` raises; API → 422; nothing stored (M4) |
| 13 | Facts/inference separation is audited and rendered separately | **Tested** | `audit_findings` unit tests; report text has `## Facts` before `## Inferences`; fact lines carry no confidence tag |
| 14 | `unresolved` is an allowed finding | **Tested** | `test_unresolved_is_allowed_finding` (module + API report flow) |
| 15 | Migration rollback tested for real | **Tested** | `test_rollback_for_real` (2026-10-23, Python 3.12.3/pytest 9.1.1/Linux) — 7 tables dropped, `schema_migrations` cleared, re-apply clean |
| 16 | No regressions | **Tested** | 1211/1211 prior tests pass; total 1298 (TEST_RESULTS.md) |
| 17 | All data synthetic; no PII | **Tested** | `test_all_fixture_files_are_utf8_text`; invented names/hosts/timestamps throughout; bannered on every page + API response |
| 18 | The "disk image" is a simulated directory tree + manifest | **Simulated** | `generate_synthetic_case()`; stated in README banner, module docstring, ARCHITECTURE.md — never a real device |
| 19 | Write-blocking concept | **Documented** | Module docstring + SECURITY.md; read-only opens implemented; no hardware involved — labeled as concept, not equivalence |
| 20 | Method demonstration, not casework experience | **NOT claimed** | README "NOT claimed" row; SECURITY.md residual risk #1; authorization record labeled synthetic procedure artifact |
| 21 | No bypassing of encryption or access controls | **NOT claimed** | No such capability exists in the module; SECURITY.md residual risk #5 |
| 22 | Production deployment / real users | **NOT claimed** | README "NOT claimed" row |
| 23 | Legal advice | **NOT claimed** | README + SECURITY.md state legal information only, never legal advice |
| 24 | Timeline tolerance as a forensic standard | **NOT claimed** | Documented fixture parameter (60 s), boundary-tested; ARCHITECTURE.md states it is not a standard |

Status vocabulary used above: **Implemented**, **Tested**, **Simulated**, **Demo** — nothing else.
