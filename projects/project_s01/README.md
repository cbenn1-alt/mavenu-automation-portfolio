# S01 — Network Security: Defensive Lab & Monitoring

**Status: Implemented · Tested** — 84 automated tests, all passing
(1054/1054 full suite: 970 prior + 84 new; zero regressions).

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**
> Everything in this project is a documented defensive design plus a local
> packet *simulator*. No live network was touched, scanned, or probed.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Firewall ruleset as ordered, commented data (`src/mavenu/firewall.py`, v1.0.0, 13 rules + implicit default-deny); deterministic packet simulator (`evaluate()` — first-match-wins, full per-rule trace); config linters (default-deny present, no shadowed/redundant rules, every allow carries a documented exception reason — all enforced in code); canonical lab test plan of 14 synthetic packets with per-rule expected verdicts; synthetic alert pipeline (synthetic event → severity → runbook triage steps) with a timed walkthrough harness asserting every step lands inside its documented time box; SQLite incident tickets with enforced lifecycle (`open→triaged→contained→resolved→closed`, reopen allowed) and append-only actor-stamped timelines; alert-fatigue tuning log (what was silenced/throttled and why); migration `013_netsec.sql` + down-step, rollback tested for real |
| What is SIMULATED | **Simulated** | The "lab" is a documented design (topology, addressing plan, VLAN plan, configs) plus the local packet simulator — **not a live network**. The `allow-established` rule models conntrack-verified return traffic; the simulator trusts the flag and documents that caveat. Timed walkthroughs run against an injectable clock, not a live SOC |
| What is SYNTHETIC | **Synthetic** | Every IP (RFC 1918 lab space + TEST-NET-3 `203.0.113.0/24` sources), packet, alert, incident, tuning entry, and timeline note is invented. No real people, networks, or events |
| What is NOT claimed | — | No production deployment. Findings do **not** transfer to production without change control. No real networks scanned, probed, or touched — the simulator never transmits a packet |

## Business problem

Small businesses run flat networks: one subnet, default credentials, no
visibility. They can't justify an enterprise SOC, but they need segmentation
basics, a firewall policy someone can actually review, and a monitoring
routine a generalist can run.

## Implemented capabilities

- **Firewall as code** (`src/mavenu/firewall.py`): 13 ordered rules —
  established-first, guest/IoT pinned to gateway DNS, guest and IoT
  internet-only (explicit internal denies), office web/DNS out, single pinned
  admin workstation into MGMT, catch-all inter-VLAN deny, WAN inbound deny,
  implicit default-deny. `evaluate()` returns verdict + rule + full trace.
- **Config review checklist as code** (`lint()`): default-deny present; last
  explicit rule is a deny; zero shadowed/unreachable rules (componentwise
  subsumption check); every allow rule carries an exception reason; rule
  orders unique and ascending.
- **Lab test plan as code** (`LAB_TEST_PACKETS`, `EXPECTED_VERDICTS`): 14
  synthetic packets — every deny rule verified, zero allow rules untested
  (pinned by `matrix_coverage()`; the web matrix shows exactly what the tests
  assert).
- **Monitoring workflow as code** (`src/mavenu/netsec.py`): 9 synthetic alert
  types → deterministic severity → severity-keyed runbook steps with time
  boxes; timed walkthrough harness (injectable clock) verifies every step
  lands inside its box; alert-fatigue tuning (`silence`/`threshold`/
  `de-escalate` with mandatory reasons) keeps suppressed alerts reviewable.
- **Incident tickets** (SQLite `netsec_incidents` + append-only
  `netsec_incident_events`): enforced lifecycle, actor stamps, timeline.
- **Ruleset versioning** (`netsec_rule_versions`): snapshots of the ruleset as
  JSON — the config-rollback record.
- **Web UI + JSON API** (`web.py`): `/project_s01` (topology, lint status,
  incidents), `/project_s01/ruleset` (ruleset + allow/deny matrix),
  `/project_s01/runbook` (severity→steps→time boxes, tuning log, daily
  checklist), `/project_s01/incidents`; `/api/netsec/*` (topology, rules,
  evaluate, matrix, runbook, alerts, tuning, incidents, seed).

## Test summary

84 new tests: ruleset lint (10), allow/deny matrix incl. per-packet verdicts
(14 parametrized + 7), alert pipeline × 9 alert types (timed, within boxes),
fatigue tuning (4), incident lifecycle (5), seed determinism + versioned
snapshot, **migration rollback tested for real** (drop → re-apply →
verified). Full suite: **1054 passed, 0 failed**. See TEST_RESULTS.md.

## Rollback

`db.rollback_migration(conn, "013_netsec.sql")` drops all five S01 tables
(synthetic data only) and removes the migration record so the up-step can be
re-applied. Tested for real — see RUNBOOK.md and TEST_RESULTS.md.
