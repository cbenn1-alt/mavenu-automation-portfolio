# S01 — Network Security: Test Results

**Run date:** 2026-10-23 (21:35 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/pytest tests/`
(run in 3 chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run)

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**

## Result

**1054 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| S01 new (`tests/test_netsec.py`) | 62 | 62 passed |
| S01 new (`tests/test_netsec_api.py`) | 22 | 22 passed |
| P01 + P02 + Q01–Q10 prior (970) | 970 | 970 passed, unchanged |

Chunk breakdown: 379 + 386 + 289 = 1054.

## Measurable criteria — verified

- **100% of deny-rules verified by lab test:** all 5 deny rules
  (`deny-guest-internal`, `deny-iot-internal`, `deny-office-mgmt`,
  `deny-wan-inbound`, `deny-inter-vlan`) are exercised by the canonical
  matrix and `matrix_coverage()["unhit_deny"] == []`
  (`test_every_deny_rule_verified`).
- **Zero allow-rules untested:** 13/13 rules hit, `unhit_allow == []`
  (`test_zero_allow_rules_untested`); all 14 matrix packets match their
  expected `(action, rule_id)` (`test_matrix_packet_verdict`, parametrized).
- **Triage runbook completes within documented time boxes:** all 9 alert
  types walk through their severity-keyed steps with `all_within_timebox`
  true; the harness itself runs in < 5 s wall time
  (`test_walkthrough_within_time_boxes`); a slow clock is correctly flagged
  (`test_walkthrough_detects_timebox_violation`).
- **Config checklist enforced:** default-deny present, zero shadowed /
  redundant rules, every allow documented, orders unique and ascending —
  plus negative injection tests proving each linter defect class is caught.
- **Alert-fatigue discipline:** tuning suppresses with the logged reason,
  steps stay visible, untuned alerts unaffected; invalid tuning rejected.
- **Incident lifecycle:** full `open→triaged→contained→resolved→closed`
  with 5 actor-stamped timeline entries; illegal transitions, empty titles,
  and bad severities rejected; reopen works.
- **Rollback tested for real** (`test_migration_rollback_for_real`):
  seeded an incident, ran `rollback_migration(conn, "013_netsec.sql")`,
  verified all five S01 tables dropped and the migration record removed,
  then re-applied via `run_migrations()` and verified the tables exist
  again. Rollback is repeatable.

## Notes

- The `allow-established` rule models conntrack-verified return traffic;
  the simulator trusts the `established` flag (documented simulation caveat
  in README.md and covered by `test_established_rule_models_conntrack`).
- `record_alert` is idempotent on the natural key `alert_id`, so a repeated
  deterministic seed is a no-op rather than an integrity error
  (`test_seed_demo_is_deterministic`).
