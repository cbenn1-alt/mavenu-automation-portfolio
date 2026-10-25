# S01 — Architecture: the defensive lab (documented design)

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**
> This is a documented design plus a local simulator. It describes how a
> small office *should* be segmented and filtered; it configures nothing
> real and touches no real network.

## 1. Lab topology (host-only)

```
                        +------------------+
                        |     INTERNET     |   WAN = any public address
                        +--------+---------+
                                 |
                        +--------+---------+        VLAN 10  OFFICE  10.10.10.0/24
                        |   lab firewall   |        VLAN 20  GUEST   10.10.20.0/24
                        |  (default-deny)   |        VLAN 30  IOT     10.10.30.0/24
                        +---+--+---+---+--+        VLAN 99  MGMT    10.10.99.0/24
                            |  |   |   |
                      +-----+  |   |  +-----+
                      | OFFICE |   |  | MGMT |   10.10.99.1 = fw mgmt iface
                      |.10.0/24|   |  |.99.0/24  (admin workstation only)
                            |   |
                       +----+ +----+
                       |GUEST | IOT |
                       |.20.0/24|.30.0/24
```

All segments attach to the firewall over **host-only** lab networking.
There is no bridge to any real LAN; the lab cannot route to the builder's
home/office network by design (see SECURITY.md).

## 2. Addressing plan

| Zone | VLAN | Subnet | Gateway | DHCP range | Notes |
|---|---|---|---|---|---|
| OFFICE | 10 | 10.10.10.0/24 | 10.10.10.1 | .100–.199 | staff workstations |
| GUEST | 20 | 10.10.20.0/24 | 10.10.20.1 | .100–.199 | guest Wi-Fi, internet-only |
| IOT | 30 | 10.10.30.0/24 | 10.10.30.1 | .100–.199 (reservations) | printers, cameras, sensors |
| MGMT | 99 | 10.10.99.0/24 | 10.10.99.1 | none (static only) | firewall/switch admin ifaces |

Reserved: `10.10.10.50` = the one admin workstation allowed into MGMT.
All addresses are synthetic lab space (RFC 1918). WAN-side test sources use
TEST-NET-3 (`203.0.113.0/24`) documentation addresses.

## 3. VLAN/segmentation design — rationale per segment

- **OFFICE (VLAN 10).** The trusted work zone — but "trusted" only relative
  to the other segments. Workstations get outbound web/DNS; nothing inbound.
  Rationale: the machines holding business data get the narrowest useful
  outbound window, and no other segment can reach them uninvited.
- **GUEST (VLAN 20).** Internet-only. Guests get DNS from the gateway and
  HTTPS/HTTP to the WAN; an explicit deny blocks them from *every* internal
  address. Rationale: guest devices are unmanaged and untrusted — the design
  assumes compromise and contains it by default.
- **IOT (VLAN 30).** Internet-only, tighter still: TLS/443 to the WAN for
  firmware/cloud updates, gateway DNS, nothing else — HTTP/80 is deliberately
  excluded, and an explicit deny blocks IoT-initiated traffic to internal
  addresses. Rationale: IoT devices are the most likely foothold (default
  creds, unpatched firmware); they must not be able to pivot.
- **MGMT (VLAN 99).** Static-only, reachable solely from the pinned admin
  workstation (`10.10.10.50`, SSH/HTTPS). A deny rule covers every other
  office host. Rationale: management interfaces are the keys to the kingdom;
  one key, one holder.

## 4. Switchport baseline (documented procedure for the lab switch)

1. Unused ports: administratively shut down.
2. Access ports assigned to exactly one VLAN (10/20/30); trunk ports only
   where the design requires (firewall uplink).
3. MGMT VLAN ports: static, no auto-negotiation of trunking.
4. Port-security: sticky MAC, max 1, violation = shutdown (lab: log + alert
   `rogue_dhcp_server`-style workflow if a new device appears).
5. BPDU guard on all access ports.

## 5. Wi-Fi hardening checklist

- [ ] WPA3-Personal (or WPA2-AES minimum) with a generated passphrase; guest
      SSID on VLAN 20 with client isolation.
- [ ] Office SSID on VLAN 10, hidden from guest clients by VLAN, not by
      "hidden SSID" (documented as non-security).
- [ ] WPS disabled. Default admin credentials changed (documented in the
      sealed password record, not in this repo).
- [ ] IoT SSID (if wireless IoT) on VLAN 30, passphrase rotated on device
      turnover.

## 6. Firewall ruleset (executable)

The ruleset lives in `src/mavenu/firewall.py` (`RULESET`, v1.0.0): 13
ordered rules, first-match-wins, implicit default-deny. Design notes:

- **Established first** (`allow-established`): mirrors real stateful
  firewalls — return traffic for inside-initiated sessions. The simulator
  trusts the `established` flag; this models conntrack and is documented as
  a simulation caveat (see README).
- **Explicit internal denies** (`deny-guest-internal`, `deny-iot-internal`)
  come *before* the outbound allows, so a mis-ordered allow can never punch
  a hole into another segment.
- **Specific-before-general**: `allow-admin-mgmt` (one host) precedes
  `deny-office-mgmt` (whole VLAN). The linter proves the deny is not
  shadowed and the allow is not redundant.
- **Catch-alls at the bottom**: `deny-wan-inbound` (logged — the internet
  background noise the tuning log aggregates), `deny-inter-vlan` (logged),
  then the implicit default-deny.

Every allow rule carries a documented exception reason; `lint()` fails the
build (test) if any allow lacks one, if any rule is shadowed, or if the
posture is not default-deny.

## 7. Monitoring workflow (as code)

- **Log sources inventory** (documented): firewall deny logs (the
  `log=True` rules), DHCP lease logs per VLAN, management-interface auth
  logs, IoT TLS volume counters, firmware advisories.
- **Alert catalog** (`netsec.py` `ALERT_TYPES`): 9 synthetic types with
  deterministic severities.
- **Triage runbook** (`RUNBOOK`): severity → ordered steps → time boxes;
  the timed walkthrough harness proves the steps complete inside the boxes.
- **Daily review checklist**: on `/project_s01/runbook` and RUNBOOK.md.
- **Alert-fatigue tuning** (`netsec_tuning`): `wan_inbound_blocked` →
  threshold (aggregate at >50/hr); `guest_dhcp_churn` → silence (batch
  review); `firmware_update_available` → de-escalate (monthly window).
  Suppressed alerts stay reviewable with their reasons.

## 8. Code map

| File | Role |
|---|---|
| `src/mavenu/firewall.py` | zones, addressing, `RULESET`, `evaluate()` simulator, linters, `LAB_TEST_PACKETS`, `EXPECTED_VERDICTS`, `matrix_coverage()` |
| `src/mavenu/netsec.py` | `ALERT_TYPES`, `RUNBOOK`, `triage()`, `walkthrough()`, incident tickets, tuning log, `seed_demo()`, ruleset versioning |
| `src/mavenu/migrations/013_netsec.sql` / `.down.sql` | `netsec_alerts`, `netsec_incidents`, `netsec_incident_events`, `netsec_tuning`, `netsec_rule_versions` |
| `src/mavenu/web.py` (`s01_*`, `api_ns_*`) | `/project_s01*` pages, `/api/netsec*` endpoints |
