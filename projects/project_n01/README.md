# N01 — Network Forensics: Packet Capture to Evidentiary Report

**Status: Implemented · Tested** — 54 automated tests, all passing.

> ⚠ **LAWFUL LAB ONLY.** The "capture" in this project is **synthetic
> packets generated in-process** by a seeded script. This codebase
> contains **no socket, pcap, or raw-packet code** — a token-aware test
> (`TestNoCaptureCode`) fails the build if any appears. It cannot tap a
> real network. Never capture a real network without explicit written
> authorization from its owner.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Seeded synthetic-packet generator (4 scripted scenarios); bidirectional 5-tuple session reconstruction with handshake/teardown tracking on synthetic TCP-ish flags; decoder stubs for 3 documented synthetic protocols; chronological timeline merging sessions + alert events; anomaly detection against a documented, named baseline (port-scan, beaconing-interval, byte-exfiltration thresholds); incident scoping derived mechanically from anomalies; evidentiary report with facts/inference separation — inferences without confidence rejected, every claim structurally required to cite a packet range; SQLite persistence (captures, packets, sessions, anomalies, reports); migration `018_netforensics.sql` + real rollback test |
| What is SIMULATED | **Simulated** | The "captured network" — packets are plain dicts, not a real tap; the lab hosts, attacker VM, C2 destination, and payloads are invented |
| What is SYNTHETIC | **Demo** | **All traffic, hosts, addresses (documentation/test ranges 192.0.2.x / 203.0.113.x), ground truth, and report text are synthetic.** Payloads are synthetic labels (e.g. `LAB-BEACON id=3 status=ok`), never real content. Every UI page and API response carries the lab-only banner. This is explicitly **not casework experience** |
| What is NOT claimed | — | No real networks captured. No production deployment. No real users, no real incidents, no forensic casework. No platform or employer endorsement |

## What it does

N01 is a repeatable, defensible packet-to-report workflow over **lab
traffic only**:

1. **Capture plan** — four scripted, seeded, deterministic scenarios
   (`baseline_clean`, `port_scan`, `c2_beaconing`, `data_exfiltration`),
   each with published ground truth.
2. **Synthetic capture** — packets as dicts: `index, ts, src, dst,
   src_port, dst_port, proto, flags, length, payload_label, payload_hash`
   (SHA-256 over the label). Same `(scenario, seed)` → byte-identical
   capture.
3. **Session reconstruction** — bidirectional 5-tuple reassembly; the
   SYN sender is the initiator; handshake complete on
   SYN→SYN-ACK→ACK in order; teardown on FIN/RST.
4. **Protocol notes** — decoder stubs for three documented toy
   protocols (`LAB-HTTP`, `LAB-DNS`, `LAB-BEACON`); anything else is
   recorded as undecoded.
5. **Timeline** — session start markers + S01-style alert events +
   capture start/end, chronological, every event citing a packet range.
6. **Anomaly detection** — documented baseline `BASELINE` (named
   thresholds, printed in every report): ≥10 distinct ports in 120 s →
   port scan; ≥5 beacons with interval CV ≤ 0.15 → beaconing;
   per-session outbound bytes > 102,400 → exfiltration.
7. **Scoping** — affected hosts, sessions, and time window derived
   mechanically from the anomalies.
8. **Evidentiary report** — facts (observed) vs inferences
   (interpreted, confidence `low/medium/high` required); every claim
   cites `[lo, hi]`; report asserts whether detections match ground truth.

## Web + API

- `/project_n01` — capture plan + run form + saved captures
- `/project_n01/sessions`, `/timeline`, `/anomalies`, `/scoping`, `/report`
- `POST /api/netforensics/capture` `{scenario, seed}` →
  `{capture_id, anomalies, ground_truth_match, ...}`
- `GET /api/netforensics/captures|/anomalies|/report`

Every JSON response carries `synthetic: true` and the ethical banner.

## What is simulated (labeled, not hidden)

- **The network**: there is no tap, no NIC, no pcap — the generator
  emits dicts. The "defense" that denies probes is two emitted packets
  labeled `RST`/`DENIED`.
- **The inferences**: demo report inferences are generated from the
  scenario script and marked synthetic; in real use they would be
  analyst-authored.
- **The baseline thresholds**: documented, defensible choices for the
  lab — not measurements from a production network.

## Files

- `src/mavenu/netforensics.py` — the whole pipeline (one module)
- `src/mavenu/migrations/018_netforensics.sql` (+ `.down.sql`)
- `src/mavenu/web.py` — `/project_n01*` pages, `/api/netforensics*`
- `tests/test_netforensics.py`, `tests/test_netforensics_api.py`
