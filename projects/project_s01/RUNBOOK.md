# S01 — Runbook: triage + rollback

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**

## 1. Alert triage runbook (severity → steps → time boxes)

The executable copy lives in `src/mavenu/netsec.py` (`RUNBOOK`); the web
copy is at `/project_s01/runbook`. Time boxes are the documented SLA the
timed walkthrough harness verifies.

### critical (e.g. `dns_tunneling_suspect`)
1. **acknowledge** ≤ 300 s — page on-call; open incident ticket.
2. **isolate** ≤ 1800 s — quarantine the suspect host at the lab switch
   (port shutdown); preserve logs.
3. **scope** ≤ 3600 s — list every other host the suspect talked to in the
   last 24 h of lab logs.
4. **resolve** ≤ 14400 s — re-image from the known-good lab snapshot;
   verify; close the ticket with notes.

### high (e.g. `port_scan_detected`, `failed_logins_burst`, `mgmt_login_failure`)
1. **acknowledge** ≤ 900 s — open incident ticket; notify owner.
2. **verify** ≤ 1800 s — confirm the alert is not scheduled lab validation
   traffic (check the validation schedule first — the common false positive).
3. **contain** ≤ 3600 s — block the offending source at the firewall as a
   temporary, documented rule.
4. **resolve** ≤ 28800 s — remove the temporary rule after the cause is
   fixed; document; close the ticket.

### medium (e.g. `iot_outbound_tls_spike`, `rogue_dhcp_server`)
1. **acknowledge** ≤ 7200 s — open incident ticket.
2. **investigate** ≤ 28800 s — review 24 h of relevant lab logs; decide
   contain vs. monitor.
3. **resolve** ≤ 172800 s — apply the fix or tune the alert; document; close.

### low (e.g. `wan_inbound_blocked`, `guest_dhcp_churn`)
1. **review** ≤ 86400 s — batch-review at the daily log review; tune if it
   is noise.

### info (e.g. `firmware_update_available`)
1. **note** ≤ 604800 s — log it; act at the next maintenance window.

## 2. Daily log-review checklist

1. Denied WAN inbound: expected background noise? (tuned: batch at >50/hr)
2. Any management-VLAN login failures? → open incident immediately.
3. IoT TLS volume vs. 7-day baseline.
4. Guest DHCP churn anomalies (rogue server?).
5. Firewall rule hit counts: any rule with zero hits in 7 days gets
   re-verified against the allow/deny matrix.

## 3. Incident ticket lifecycle

`open → triaged → contained → resolved → closed`; `closed → open` reopen
allowed. Every transition is actor-stamped on an append-only timeline.
Template fields: title, severity, source alert type, actor, notes per
transition.

## 4. Rollback procedure

### 4a. Database rollback (migration 013)

```python
from mavenu.db import get_connection, rollback_migration, run_migrations
conn = get_connection(db_path)
rollback_migration(conn, "013_netsec.sql")  # drops the 5 S01 tables
run_migrations(conn)                        # re-applies cleanly if needed
```

Scope: drops `netsec_alerts`, `netsec_incidents`,
`netsec_incident_events`, `netsec_tuning`, `netsec_rule_versions` — all
synthetic demo data. Do not run against a database whose S01 records you
need to keep. Tested for real — see TEST_RESULTS.md.

### 4b. Firewall ruleset config revert

The ruleset is versioned in `netsec_rule_versions` (JSON snapshots via
`save_ruleset_version()`). To revert a bad ruleset change: restore the
previous version's JSON, re-run `lint()` (must be clean), re-run the
allow/deny matrix (coverage must stay 13/13), then snapshot the restored
version as the new current.
