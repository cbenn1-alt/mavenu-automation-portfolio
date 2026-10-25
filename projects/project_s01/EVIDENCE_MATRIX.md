# S01 — Evidence Matrix

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**
> Every public claim about S01 maps below to a test, an artifact, or a
> labeled estimate. "Estimate" means a documented judgment, not a
> measurement.

| Public claim | Evidence | Label |
|---|---|---|
| Firewall ruleset is ordered, commented, default-deny | `src/mavenu/firewall.py` `RULESET` (13 rules, v1.0.0) + `DEFAULT_DENY=True` | Implemented |
| Default-deny posture enforced | `test_default_deny_enforced` | Tested |
| No shadowed/unreachable rules | `test_no_shadowed_or_redundant_rules` + negative injection tests (`test_lint_catches_shadowed_rule`, `test_lint_catches_redundant_rule`) | Tested |
| Every allow rule has a documented exception reason | `test_every_allow_has_exception_reason`, `test_lint_catches_missing_allow_reason` | Tested |
| 100% of deny rules verified by lab test | `test_every_deny_rule_verified`: `matrix_coverage()["unhit_deny"] == []` (5/5 deny rules) | Tested |
| Zero allow rules untested | `test_zero_allow_rules_untested`: `unhit_allow == []`, 13/13 rules hit | Tested |
| Each matrix packet's verdict is correct | 14 parametrized `test_matrix_packet_verdict` vs `EXPECTED_VERDICTS` | Tested |
| Admin-workstation specificity works via rule order | `test_admin_workstation_specificity` | Tested |
| Triage runbook completes within documented time boxes | 9 parametrized `test_walkthrough_within_time_boxes` (`all_within_timebox`, harness wall < 5 s) | Tested |
| Time-box checking actually works | `test_walkthrough_detects_timebox_violation` (slow clock → fails as it should) | Tested |
| Alert fatigue is tuned with logged reasons | `test_tuning_suppresses_with_logged_reason`, seeded entries in `SECURITY.md` §2 | Tested |
| Suppression stays reviewable | tuning reason attached in `triage()`; steps remain visible (asserted) | Tested |
| Incident lifecycle enforced | `test_full_lifecycle` (5-step timeline), `test_illegal_transitions_rejected`, `test_reopen_closed_incident` | Tested |
| Migration rollback works for real | `test_migration_rollback_for_real` (tables dropped, record removed, re-apply clean) | Tested |
| Web UI + API work end to end | `tests/test_netsec_api.py` (22 tests: pages, evaluate, matrix, alerts, tuning, incidents, seed) | Tested |
| The lab is host-only; nothing real is touched | Design doc (`ARCHITECTURE.md` §1, `SECURITY.md` §1); the simulator has no socket/scan code | Implemented (documented design) |
| "The lab proves the rules work" | **Estimate** — the simulator proves the *ruleset logic*; it does not prove a physical deployment. Labeled Simulated. | Estimate |
| 84 new tests, full suite green | `pytest tests/test_netsec.py tests/test_netsec_api.py` → 84 passed; full suite 1054 passed, 0 failed (see TEST_RESULTS.md) | Tested |

## What is deliberately NOT claimed

- No production deployment; no live firewall configured.
- No real packet capture or real incident data.
- Findings do not transfer to production without change control.
- No scanning/probing capability exists in this codebase (the T12 "probe"
  is a synthetic packet through `evaluate()`).
