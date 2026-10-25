# N01 — Requirements (full spec)

**Status:** Implemented + Tested (2026-10-23). Supersedes the §4
spec-sketch in `portfolio-architecture-2026-10-23.md`.

> ⚠ **LAWFUL LAB ONLY.** All traffic is synthetic packets generated
> in-process by a seeded script. This project contains no socket/pcap
> code and cannot capture a real network. Never capture a real network
> without explicit written authorization from its owner.

## 1. Purpose

Demonstrate a defensible, repeatable **packet-capture → evidentiary
report** workflow on synthetic lab traffic: generate a scripted
capture, reconstruct sessions and protocols, build an event timeline,
detect anomalies against a documented baseline, mechanically scope the
"incident," and produce a report that separates facts from inference —
with every claim citing a packet range (the same discipline as S03).

The product is the **method** (citation discipline, baseline
transparency, facts/inference separation), not a network sensor.

## 2. Scope

**In scope:**

- A synthetic packet generator for scripted lab scenarios
  (deterministic, seeded; packets are dicts, never wire data).
- Bidirectional 5-tuple session reconstruction with handshake/teardown
  tracking on synthetic TCP-ish flags.
- Decoder stubs for 2–3 defined synthetic protocols.
- A timeline builder merging session markers and S01-style alert events.
- Anomaly detection against a documented baseline (ports, byte counts,
  beaconing intervals) with published deviation thresholds.
- Incident scoping derived from anomalies (hosts, sessions, window).
- An evidentiary report: facts vs inference, every claim citing a
  packet range; inference without confidence rejected.
- SQLite persistence + migration with a tested down-step.
- Web pages and JSON API (all bannered synthetic).

**Out of scope:** see §9 (non-goals).

## 3. Scripted scenarios (all synthetic, labeled)

Four scenarios, each with published ground truth (`ground_truth` dict
returned by the generator; the pipeline's report asserts
`ground_truth_match`):

| # | Scenario | Script | Ground truth |
|---|---|---|---|
| 1 | `baseline_clean` | Routine lab chatter: LAB-NTP poll/reply, 2 LAB-HTTP sessions, 1 LAB-DNS Q/R | 0 anomalies |
| 2 | `port_scan` | Attacker VM `203.0.113.9` sends 24 SYN probes (ports 8000–8023) at 0.4 s spacing to lab server `192.0.2.21`; defense denies each (`RST`+`DENIED`) | 1 `port_scan` anomaly; probe packet range `[lo, hi]` covering probes AND denials |
| 3 | `c2_beaconing` | Compromised workstation `192.0.2.11` emits 10 `LAB-BEACON` frames to `203.0.113.77:4443` at 60 s mean interval (±0.2 s deterministic jitter) with replies | 1 `beaconing` anomaly; detected interval within 1.0 s of 60 s |
| 4 | `data_exfiltration` | `192.0.2.11` → `203.0.113.50:31337`: 400 × 1400-byte labeled chunks = 560,000 bytes outbound in one session | 1 `byte_exfiltration` anomaly; `bytes_out` = 560,000 > threshold |

Lab addressing uses documentation/test ranges only: `192.0.2.0/24`
(lab) and `203.0.113.0/24` (synthetic external). A test asserts no
other source/destination prefixes appear.

## 4. Session-reconstruction rules

- **Key:** bidirectional 5-tuple — `(proto, {endpoint A, endpoint B})`
  where an endpoint is `(ip, port)`. Both directions merge into one
  session.
- **Initiator:** the SYN sender; if no SYN, the first packet's source.
- **Handshake complete:** SYN (initiator) → SYN-ACK (responder) →
  ACK (initiator), in packet-index order, matched by direction.
- **Teardown seen:** FIN or RST from either side (including
  `RST+DENIED` defense replies).
- **One-sided flows** (single DATA packets, denied probes) are sessions
  too, with `handshake_complete=false` — never silently dropped.
- **Session record:** key, src/dst/ports, `[start_index, end_index]`,
  packet count, total/bytes_out/bytes_in, timestamps, handshake/teardown
  flags, protocol note.
- **Coverage invariant:** every packet belongs to exactly one session
  (asserted in tests).

## 5. Protocol set

Three synthetic application protocols with documented label grammars;
decoders are stubs that parse the label or return `None`:

| Protocol | Grammar | Example |
|---|---|---|
| `LAB-HTTP` | `LAB-HTTP <GET\|POST> /synth/<n>` | `LAB-HTTP GET /synth/3` |
| `LAB-DNS` | `LAB-DNS <Q\|R> <name>.synth.local` | `LAB-DNS Q update.synth.local` |
| `LAB-BEACON` | `LAB-BEACON id=<n> status=<ok\|err>` | `LAB-BEACON id=7 status=ok` |

- Payloads are synthetic **labels**, hashed with SHA-256 for the
  `payload_hash` field — never real content.
- A session's `protocol_note` lists each distinct decoded protocol;
  packets matching no decoder are recorded as undecoded (e.g. the
  `LAB-EXFIL` chunks — honest about the decoder's limits).
- Transport is `LAB-TCP` with flags
  `SYN, SYN-ACK, ACK, FIN, RST, DATA, DENIED` (DENIED = defense-denied).

## 6. Anomaly-detection method

Baseline `BASELINE` ("N01 lab baseline v1", documented 2026-10-23) —
named thresholds, printed in every report and on the anomalies page:

| Threshold | Value | Meaning |
|---|---|---|
| `port_scan_min_ports` | 10 | distinct dst ports from one src→dst… |
| `port_scan_window_s` | 120 | …within this window → `port_scan` (high confidence) |
| `beacon_min_packets` | 5 | minimum outbound beacon frames to judge regularity |
| `beacon_interval_cv_max` | 0.15 | coefficient of variation (std/mean) of inter-arrival gaps |
| `beacon_min_interval_s` | 5.0 | sub-5 s bursts are retransmit noise, not beacons |
| `exfil_byte_threshold` | 102,400 | per-session outbound bytes above → `byte_exfiltration` |
| `normal_session_byte_cap` | 51,200 | routine lab sessions stay under (documented, not enforced) |
| `expected_service_ports` | 80,443,53,123,8080 | reference list |

Detectors:

1. **Port scan:** group SYN-probe packets by (src, dst); if distinct
   ports ≥ 10 within 120 s → anomaly citing the range covering probes
   **and** their denial replies.
2. **Beaconing:** group outbound small (≤128 B) `LAB-BEACON` frames by
   (src, dst, dst_port); if count ≥ 5, mean gap ≥ 5 s, and CV ≤ 0.15 →
   anomaly with `mean_interval_s`, `interval_cv`, citing the full
   conversation range.
3. **Byte exfiltration:** any session with outbound bytes (lab → external)
   > 102,400 → anomaly citing the session's packet range.

Every anomaly carries `type, summary, detail, packet_range, confidence`.
The clean baseline scenario must produce **zero** anomalies.

## 7. Scoping method

`scope_incident(anomalies, sessions, packets)` derives scope
mechanically — no manual attribution beyond the lab:

- **Affected hosts:** union of `src`/`dst` in anomaly details.
- **Affected sessions:** session keys named in anomaly details.
- **Time window:** `[min anomaly start, max anomaly end]` ± 60 s margin
  (packet range `[lo, hi]` also reported).
- **Summary:** one-line memo ("2 anomalie(s) (beaconing, port_scan)
  involving 3 host(s), packet range [16, 63]").
- With no anomalies: empty scope with the explicit statement "no
  anomalies detected; no incident scope to declare."

## 8. Report structure

`build_report(...)` returns:

```json
{
  "capture_ref": "port_scan-20261023", "scenario": "port_scan",
  "seed": 20261023, "ethical_banner": "LAWFUL LAB ONLY…",
  "synthetic": true, "created_at": "…", "packet_count": 64,
  "baseline": {…named thresholds…},
  "scope": {…},
  "facts": [{"statement": "…", "packet_range": [0, 63]}],
  "inferences": [{"statement": "…", "packet_range": [16, 63],
                  "confidence": "medium"}],
  "anomalies": [{"type": "port_scan", "summary": "…",
                 "packet_range": [16, 63], "confidence": "high"}],
  "ground_truth_match": true
}
```

**Citation discipline (enforced in code, asserted in tests):**

- Every fact and every inference MUST carry `packet_range: [lo, hi]`
  with `0 ≤ lo ≤ hi < packet_count` — structurally rejected otherwise.
- Every inference MUST carry `confidence` in `low/medium/high` —
  rejected otherwise (same discipline as S03's hypothesis rule).
- Facts never carry confidence (observed, not interpreted).
- `ground_truth_match`: whether detected anomaly types exactly equal
  the scenario's expected anomaly types.

## 9. Acceptance criteria + non-goals

**Acceptance criteria (all tested):**

- A1. Same `(scenario, seed)` → identical capture (determinism).
- A2. Session reconstruction exact: exfil session = 405 packets,
  560,000 bytes out, handshake + teardown true; 24 one-sided probe
  sessions each `handshake_complete=false`, `teardown_seen=true`.
- A3. Timeline matches scripted ground truth: chronological, starts
  with `capture_start`, ends with `capture_end`, one alert per anomaly
  citing the anomaly's packet range.
- A4. Beaconing flagged with detected interval within 1.0 s of 60 s.
- A5. Port scan flagged with all 24 probed ports and the 24 denial
  replies inside the cited range.
- A6. Exfil flagged on the byte-count deviation (560,000 > 102,400).
- A7. `baseline_clean` → zero anomalies, empty scope.
- A8. Every anomaly and every report claim cites a valid packet range
  (structurally asserted for all four scenarios).
- A9. Facts/inference separation enforced: inference without confidence
  rejected; claim without packet range rejected.
- A10. No socket/pcap code: token-aware source scan fails the build if
  `socket`, `pcap`, `AF_PACKET`, or `SOCK_RAW` appear as code tokens.
- A11. Migration rollback tested for real (apply → use → roll back →
  re-apply).
- A12. Zero regressions across the full suite.

**Non-goals (explicitly NOT built):**

- No real packet capture: no sockets, no pcap, no NIC access — ever.
- No decryption of real traffic; payloads are synthetic labels.
- No attribution beyond the lab (no actor naming, no external
  intelligence).
- No statistical ML detector — the detectors are documented threshold
  rules; no "AI detects intrusions" claim.
- No production/forensic-casework use; this is a method demonstration.
