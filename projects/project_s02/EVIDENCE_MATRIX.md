# S02 — Evidence Matrix

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**
> Every public claim about S02 maps below to a test, an artifact, or a
> labeled estimate. "Estimate" means a documented judgment, not a
> measurement.

| Public claim | Evidence | Label |
|---|---|---|
| 15 hardening baselines as structured data with verification functions | `src/mavenu/ossec.py` `BASELINES` (15 items, 5 categories) | Implemented |
| Every baseline item fails on the vulnerable fixture and passes on the hardened fixture | 15 parametrized `test_item_fails_vulnerable_passes_hardened` | Tested |
| Every baseline item has a verification function and a remediation | `test_full_coverage` (`coverage_audit() == []`); live at `GET /api/ossec/coverage` | Tested |
| 6 vulnerability-class records: description → detection → remediation → verification | `FINDINGS` in `src/mavenu/ossec.py` + `test_100_percent_carry_detection_remediation_verification` (structural) | Tested |
| All 6 findings detect on the vulnerable fixture | `test_all_findings_detect_on_vulnerable` | Tested |
| No finding detects on the hardened fixture | `test_no_findings_detect_on_hardened` | Tested |
| Remediation simulator: apply fix → re-verify → pass, with before/after evidence | `test_remediate_finding_verifies` (×6), `test_before_after_report_full` (0/15 → 15/15) | Tested |
| Verification is pure (does not mutate the evaluated state) | `test_verify_does_not_mutate_state` | Tested |
| Tampered states are caught (re-enabled service, reopened SSH password auth, restored setuid, stale updates) | 4 adversarial tests in `TestAdversarial` | Tested |
| Finding lifecycle enforced (`open→remediated→verified→closed`) | `test_record_and_transition_finding`, `test_illegal_transition_rejected` | Tested |
| Migration rollback works for real | `test_migration_rollback_for_real` (drop → record removed → re-apply clean) | Tested |
| Web UI + API work end to end | `tests/test_ossec_api.py` (17 tests: 5 pages, baselines/findings/coverage/evaluate/remediate/seed) | Tested |
| Vulnerable fixture passes 0/15; hardened fixture passes 15/15 | `test_every_item_fails_on_vulnerable`, `test_every_item_passes_on_hardened`, TEST_RESULTS.md M6 | Tested (measured) |
| Privilege-boundary concepts documented (rings, isolation, auth flows) | `ARCHITECTURE.md` §2 + `/project_s02/concepts` | Implemented |
| Lab inventory, snapshot discipline, host-only proof documented | `/project_s02/lab` + `SECURITY.md` §1 | Implemented (documented design) |
| 70 new tests, full suite green | `pytest tests/test_ossec.py tests/test_ossec_api.py` → 70 passed; full suite 1124 passed, 0 failed (see TEST_RESULTS.md) | Tested |
| "The lab proves the baselines work" | **Estimate** — the simulator proves the *baseline logic* against simulated states; it does not prove a physical hardening engagement. Labeled Simulated. | Estimate |

## What is deliberately NOT claimed

- No production systems assessed; no real VMs built or hardened.
- No real credentials, accounts, hosts, or vulnerabilities represented.
- No exploit development, no exploitation workflow, no zero-day material —
  detection and fix only, by design.
- Findings do not transfer to real systems without authorization and
  change control.
- The simulator contains no socket, SSH, shell, or subprocess code; it
  cannot assess anything outside its own process.
