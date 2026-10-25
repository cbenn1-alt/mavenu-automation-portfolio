# S01 — Security (lab-escape prevention + alert-fatigue discipline)

> **⚠ LAWFUL LAB ONLY — do not try this on networks you don't own.**

## 1. Lab-escape prevention

The lab is a documented design plus a local simulator, so "escape" here
means the design or its tests ever touching a real network. Controls:

1. **Host-only by design.** The documented topology attaches every segment
   to the firewall on host-only lab networking. Bridging to a real LAN is
   explicitly forbidden in the design; any real deployment of this topology
   requires change control (see RUNBOOK.md).
2. **The simulator never transmits.** `evaluate()` constructs verdicts from
   in-memory `Packet` objects. There is no socket, no raw-packet, no scan
   code anywhere in S01 — verified by inspection (`grep -rn "socket" src/`
   returns nothing in S01 modules).
3. **Documentation-range addresses only.** Lab space is RFC 1918; WAN-side
   test sources are TEST-NET-3 (`203.0.113.0/24`). No real host, customer,
   or employer address appears anywhere.
4. **The "attacker VM" is a role in the test plan, not a tool.** The WAN→
   office probe (T12) is a synthetic packet through `evaluate()` — the
   honest equivalent of "port-scan your own lab" without any scanning
   capability existing in the codebase.
5. **No credentials anywhere.** The Wi-Fi checklist requires generated
   passphrases kept in a sealed record — never in this repo.

## 2. Alert-fatigue tuning log (what was silenced and why)

| Alert type | Action | Reason | Status |
|---|---|---|---|
| `wan_inbound_blocked` | threshold | Routine internet background noise: the deny is expected and logged; aggregate at >50/hr instead of paging. The log line stays — the page doesn't. | Seeded |
| `guest_dhcp_churn` | silence | Phones joining/leaving guest Wi-Fi is normal; reviewed in the daily batch instead of alerting. | Seeded |
| `firmware_update_available` | de-escalate | Informational; handled at the monthly maintenance window. | Seeded |
| `port_scan_detected` | — (not tuned) | Deliberately left loud: unexpected during non-validation hours. | Active |
| `dns_tunneling_suspect` | — (not tuned) | Critical; never silenced. | Active |
| `failed_logins_burst`, `mgmt_login_failure` | — (not tuned) | Management-plane signals stay loud. | Active |

Design rule: suppression is reviewable, never silent. `triage()` attaches
the tuning reason to the alert, and the runbook steps remain visible, so a
silenced alert can be audited. Tuning entries require a non-empty reason
(enforced in code).

## 3. Data handling

- All incident titles, alert details, and tuning reasons in the demo are
  invented. The schema stores no PII by design (source IPs are lab or
  documentation ranges).
- Structured stdout logging is limited to identifiers and state names —
  never payload contents.

## 4. Change control note

These rules describe a lab. Applying them to a real office network is a
production change: review, back up the existing config, schedule a
maintenance window, and verify with the same allow/deny matrix before and
after. Nothing here authorizes touching a network you don't own.
