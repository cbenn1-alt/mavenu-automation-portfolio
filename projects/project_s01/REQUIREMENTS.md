# S01 — Requirements

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**
> All requirements below are satisfied in an isolated, documented lab design
> plus a local simulator. Never scan, probe, or test any network you do not own.

## Functional requirements

| ID | Requirement | Satisfied by | Status |
|---|---|---|---|
| R1 | Segmentation design: VLAN plan for office/guest/IoT with per-segment rationale | `ARCHITECTURE.md` §2; `firewall.py` `SUBNETS`/`GATEWAYS` | Implemented |
| R2 | Firewall rule sets: ordered, commented, default-deny, every allow documented with an exception reason | `firewall.py` `RULESET` (13 rules, v1.0.0) | Implemented |
| R3 | Secure baseline configs: switchport baseline, Wi-Fi hardening checklist | `ARCHITECTURE.md` §4–5 (documented procedures; lab has no physical switch to configure) | Implemented (documented) |
| R4 | Defensive monitoring workflow: log sources inventory, daily review checklist, alert triage runbook | `netsec.py` `ALERT_TYPES`/`RUNBOOK`; `/project_s01/runbook` daily checklist | Implemented |
| R5 | Incident ticket template + lifecycle | `netsec_incidents` / `netsec_incident_events`, enforced transitions | Implemented |
| R6 | Executable lab test plan: port-scan *own lab* from the attacker VM, verify denies | Local packet simulator replaces the live scan: `LAB_TEST_PACKETS` includes a WAN→office probe (T12) and inter-VLAN probes; `evaluate()` verdicts verified per rule | Simulated (documented design; no real scan — the simulator is the honest equivalent) |
| R7 | Alert pipeline tested end-to-end with synthetic events | `triage()` → `walkthrough()` harness, timed within documented time boxes | Tested |
| R8 | Measurable: 100% of deny-rules verified by lab test | `matrix_coverage()`: `unhit_deny == []` pinned by test | Tested |
| R9 | Measurable: zero allow-rules untested | `matrix_coverage()`: `unhit_allow == []` pinned by test | Tested |
| R10 | Measurable: triage runbook completes on synthetic incidents within documented time boxes | `walkthrough()` asserts `all_within_timebox` for all 9 alert types | Tested |
| R11 | Rollback procedure, tested for real | Migration `013_netsec.sql` + `.down.sql`; rollback test drops tables and re-applies | Tested |

## Non-functional requirements

| ID | Requirement | Satisfied by | Status |
|---|---|---|---|
| N1 | Zero cost | Python 3.12 stdlib only at runtime (`ipaddress`, `sqlite3`, `json`, `random`, `time`) | Implemented |
| N2 | Synthetic data only | All IPs from RFC 1918 / TEST-NET-3; all names invented | Implemented |
| N3 | No network calls, no scanning | The simulator constructs packets in memory; nothing is transmitted. The only "WAN" addresses are documentation ranges | Implemented |
| N4 | Honest status vocabulary | Implemented / Tested / Simulated / Demo used exactly | Implemented |
| N5 | Input validation at every boundary | `api_ns_evaluate` validates IPs via `ipaddress`; incident/tuning APIs validate enums and non-empty reasons | Tested |
| N6 | UTF-8 text only, no binaries | Docs and code are UTF-8; the ASCII topology diagram is plain text | Implemented |

## Out of scope (explicitly NOT claimed)

- No live firewall deployment; no production config.
- No real packet capture (that is N01's territory, lab-scoped).
- No offensive tooling beyond the lab-scoped verification packets in the simulator.
- Findings do not transfer to production without change control.
