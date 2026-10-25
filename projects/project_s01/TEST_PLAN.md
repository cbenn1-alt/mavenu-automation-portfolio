# S01 — Test Plan

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**
> All "lab tests" below execute against the local packet simulator and
> synthetic fixtures. Nothing is transmitted, scanned, or probed.

## 1. Firewall ruleset tests

| Area | Method | Pass criterion |
|---|---|---|
| Default-deny posture | `lint_default_deny()` | `DEFAULT_DENY` true and last explicit rule is a deny |
| Exception documentation | `lint_allow_reasons()` | every allow rule has a non-empty `exception_reason` |
| Shadowing | `find_shadowed()` | zero shadowed, zero redundant rules in `RULESET` |
| Order hygiene | `lint()` | rule orders unique and ascending |
| Negative linter cases | inject bad rulesets (missing reason, shadowed allow, redundant allow, duplicate order) | each injected defect is detected |

## 2. Allow/deny matrix (the lab test plan, executable)

`LAB_TEST_PACKETS` (14 synthetic packets) × `evaluate()`; each packet has an
expected `(action, rule_id)` in `EXPECTED_VERDICTS`:

| Packet | Expectation | Rule under test |
|---|---|---|
| T01 office→WAN https (established) | allow | allow-established |
| T02 guest→gateway DNS | allow | allow-guest-gw-dns |
| T03 iot→gateway DNS | allow | allow-iot-gw-dns |
| T04 guest→office SMB | **deny** | deny-guest-internal |
| T05 iot→office SSH | **deny** | deny-iot-internal |
| T06 office→WAN https | allow | allow-office-web |
| T07 office→WAN DNS | allow | allow-office-dns |
| T08 guest→WAN https | allow | allow-guest-web |
| T09 admin ws→mgmt SSH | allow | allow-admin-mgmt |
| T10 office host→mgmt SSH | **deny** | deny-office-mgmt |
| T11 iot→WAN https | allow | allow-iot-updates |
| T12 WAN→office RDP probe | **deny** | deny-wan-inbound |
| T13 office→guest http | **deny** | deny-inter-vlan |
| T14 office→WAN icmp | **deny** (implicit) | default-deny |

Pass criteria: all 14 verdicts match; `matrix_coverage()` reports
`unhit_allow == []` and `unhit_deny == []` (13/13 rules exercised).
The `/api/netsec/matrix` endpoint serves exactly this matrix.

## 3. Monitoring / alert pipeline tests

| Area | Method | Pass criterion |
|---|---|---|
| Severity mapping | all 9 `ALERT_TYPES` | each maps to a valid severity with ≥1 runbook step |
| Timed walkthrough | `walkthrough()` with injectable clock, per alert type | `all_within_timebox` true; harness wall time < 5 s |
| Time-box violation detection | clock that blows every box | `all_within_timebox` false (the harness actually checks) |
| Fatigue tuning | `log_tuning()` + `triage()` | tuned alert suppressed **with** its logged reason; steps still visible; untuned alerts unaffected |
| Tuning validation | bad alert type / bad action / empty reason | `IncidentError` raised |

## 4. Incident ticket tests

Full lifecycle `open→triaged→contained→resolved→closed` (5 timeline
entries, actor-stamped); illegal jumps (`open→resolved`, unknown status,
unknown incident) rejected; `closed→open` reopen works; list filtering by
status; create validation (empty title, bad severity rejected).

## 5. Rollback test (for real)

On a migrated temp DB: seed a row, `rollback_migration(conn,
"013_netsec.sql")`, assert all five S01 tables are gone and the migration
record is removed, then `run_migrations(conn)` and assert the up-step
re-applies cleanly and the tables exist again.

## 6. API tests

Pages (`/project_s01`, `/ruleset`, `/runbook`, `/incidents`) return 200 and
carry the lab-only banner; endpoints: topology, rules (lint clean, 13
rules), evaluate (allow/deny/422 on bad input), matrix (coverage clean),
runbook, alert ingest (201 + walkthrough within boxes) / list, tuning
create/list (+422 on bad action), incident CRUD + transitions (+422 illegal,
404 unknown), seed (deterministic counts).

## 7. Full suite

Run the entire portfolio suite in chunks (512 MB `/tmp` tmpfs fills in one
full run): clear `/tmp/pytest-of-root` between chunks. Zero regressions
required — the suite must remain green end to end.
