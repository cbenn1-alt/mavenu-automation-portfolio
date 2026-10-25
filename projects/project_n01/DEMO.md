# N01 — Demo Script

> ⚠ **LAWFUL LAB ONLY — SYNTHETIC DATA.** Everything below is generated
> in-process. Nothing here touches a real network.

A 5-minute guided walkthrough of packet-capture → evidentiary report.

## 1. The capture plan (1 min)

Open `/project_n01`. The capture-plan table lists the four scripted
scenarios and their ground truth:

- `baseline_clean` — routine lab chatter; expect **zero anomalies**.
- `port_scan` — 24 SYN probes, all denied; expect 1 port-scan anomaly.
- `c2_beaconing` — 10 beacons at 60 s intervals; expect 1 beaconing
  anomaly with the detected interval ≈ 60 s.
- `data_exfiltration` — 560,000 synthetic bytes on port 31337; expect
  1 byte-exfiltration anomaly.

## 2. Run the port-scan capture (1 min)

Select `port_scan`, seed `20261023`, click **Run (synthetic)**. The
Sessions page shows:

- 2 complete LAB-HTTP sessions (`handshake=yes`, both directions
  merged — bidirectional 5-tuple reassembly).
- 24 two-packet sessions from `203.0.113.9` — `handshake=no`,
  `teardown=yes`: the denied probes. One-sided flows are sessions too;
  nothing is silently dropped.

## 3. Timeline (1 min)

Click **Timeline →**. Events are chronological: `capture_start`, one
`session_start` per session, one `alert` (the port-scan detection),
`capture_end`. Every row cites a packet range.

## 4. Anomalies + baseline (1 min)

Click **Anomalies →**. The detection summary names all 24 probed ports
(8000–8023) and notes the defense denied each. Below it, the
**documented baseline** table shows the exact thresholds that fired
(≥10 ports in 120 s) — no magic numbers.

## 5. Scoping + report (1 min)

Click **Scoping →**: affected hosts `192.0.2.21`, `203.0.113.9`, the
packet range, and a one-line memo — derived mechanically, no manual
attribution. Click **Report →**: facts (observed: "24 distinct ports
probed…", each citing `[16, 63]`) separated from inferences (each with
a confidence level), and `Ground-truth match: true`.

## Talking points (honest)

- **Real:** the pipeline — generation, reassembly, timeline, threshold
  detection, scoping, and citation-enforced reporting are implemented
  and tested (54 tests).
- **Simulated:** the "network" — packets are dicts; the defense is two
  labeled packets; inferences are script-generated and labeled synthetic.
- **Not claimed:** no real capture, no casework, no production use.
