# S01 — Demo walkthrough

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**
> Every value below is synthetic. The "lab" is a documented design plus a
> local simulator — no live network is involved.

## 1. The ruleset, executable

```python
from mavenu import firewall as fw

# What would the lab firewall do with this packet?
pkt = fw.Packet(src_ip="10.10.20.5", dst_ip="10.10.10.10",
                proto="tcp", dst_port=445,
                label="guest laptop probing office SMB")
result = fw.evaluate(pkt)
print(result.action, result.rule_id)   # deny deny-guest-internal
```

Try the interesting ones: the admin workstation (`10.10.10.50 → 10.10.99.1`
SSH → allow) versus any other office host (→ deny). That's rule order doing
its job — and `fw.lint()` proves the ordering is sound:

```python
assert fw.lint() == []          # default-deny, no shadows, allows documented
matrix = fw.allow_deny_matrix(list(fw.LAB_TEST_PACKETS))
print(fw.matrix_coverage(matrix))
# {'rules_total': 13, 'rules_hit': 13, 'unhit_allow': [], 'unhit_deny': []}
```

## 2. The alert pipeline, timed

```python
from mavenu import netsec as ns

alert = ns.synthetic_alert("port_scan_detected")   # synthetic event
triaged = ns.triage(alert)                          # severity + runbook steps
walk = ns.walkthrough(triaged)                      # timed harness
print(walk["all_within_timebox"])                   # True
```

Fatigue tuning keeps the noise down without going silent:

```python
ns.log_tuning(conn, "wan_inbound_blocked", "threshold",
              "routine internet background noise")
triaged = ns.triage(ns.synthetic_alert("wan_inbound_blocked"),
                    ns.list_tuning(conn))
print(triaged["suppressed"], triaged["suppression_reason"])
# True 'routine internet background noise'
```

## 3. Incident tickets

```python
iid = ns.create_incident(conn, "Simulated port scan", "high")
for nxt in ("triaged", "contained", "resolved", "closed"):
    ns.transition_incident(conn, iid, nxt, actor="demo")
ns.get_incident(conn, iid)["timeline"]   # 5 actor-stamped entries
```

## 4. In the web UI

- `/project_s01` — topology, lint status, incident counts, seed form
- `/project_s01/ruleset` — the full ordered ruleset with exception reasons
  and the allow/deny matrix as computed live
- `/project_s01/runbook` — severity → steps → time boxes, tuning log,
  daily checklist
- `/project_s01/incidents` — ticket list + create form
- `POST /api/netsec/evaluate` with
  `{"src_ip":"10.10.10.20","dst_ip":"93.184.216.34","proto":"tcp","dst_port":443}`
  → `{"action":"allow","rule_id":"allow-office-web", ...}`
