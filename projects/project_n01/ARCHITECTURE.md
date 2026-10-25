# N01 — Architecture

## Overview

N01 is a single-module pipeline (`src/mavenu/netforensics.py`) plus a
migration, web handlers, and tests. It deliberately reuses two proven
patterns:

- **S01 (`netsec.py`)**: synthetic-alert → triage shape. N01's
  `derive_alerts()` converts anomalies into S01-style alert events
  (`alert_type`, `severity`, `summary`, `packet_range`) that the
  timeline builder merges.
- **S03 (`forensics.py`)**: the facts/inference discipline.
  `build_report()` structurally rejects inferences without confidence
  and claims without packet citations, mirroring S03's
  hypothesis/confidence rules.

## Data flow

```
generate_capture(scenario, seed)          # synthetic packets (dicts) + ground truth
        |
reconstruct_sessions(packets)             # bidirectional 5-tuple reassembly
        |
detect_anomalies(packets, sessions)       # 3 threshold detectors vs BASELINE
        |
derive_alerts(anomalies, packets)         # S01-style alert events
        |
build_timeline(packets, sessions, alerts) # chronological, cited events
        |
scope_incident(anomalies, sessions, pkts)  # hosts / sessions / window
        |
build_report(...)                         # facts vs inference, citations enforced
```

`run_full_pipeline()` executes the whole chain in memory and is the
primary entry point for tests, the web demo, and the API.

## Key design decisions

1. **Packets are dicts, not wire data.** There is no socket/pcap code
   anywhere — by construction, not by policy. A token-aware test
   fails the build if capture-related code tokens appear.
2. **Deterministic generator.** `random.Random(seed)` drives only the
   beacon jitter; timestamps derive from a fixed base epoch. Same
   `(scenario, seed)` → identical packet list (asserted).
3. **Bidirectional sessioning.** Sessions key on the unordered endpoint
   pair so SYN-ACK/ACK replies join the initiator's session; this makes
   handshake detection (SYN→SYN-ACK→ACK in order, direction-matched)
   exact for the scripted sessions.
4. **Baseline as data.** `BASELINE` is a named, versioned dict printed
   in every report and on the anomalies page — thresholds are
   documented choices, not magic numbers, and not production
   measurements.
5. **Citation as a type-level rule.** Packet ranges are `[lo, hi]`
   integer pairs validated against `packet_count`; the report builder
   raises `NetForensicsError` on any violation, so an uncited claim
   cannot be persisted or rendered.
6. **Facts vs inference.** Facts are mechanical (`auto_facts()` derives
   them from packets/sessions/anomalies). Inferences are interpretations
   and must carry confidence. The demo's `_scripted_inferences()` are
   explicitly labeled synthetic; a real deployment would take
   analyst-authored text through the same validator.

## Persistence

Migration `018_netforensics.sql`:

- `netforensics_captures` — `capture_ref` UNIQUE, scenario CHECK,
  seed, packet_count.
- `netforensics_packets` — one row per synthetic packet
  (`UNIQUE(capture_id, pkt_index)`), label + SHA-256 hash.
- `netforensics_sessions` — reassembly output with
  handshake/teardown flags and protocol notes.
- `netforensics_anomalies` — type CHECK, summary, detail JSON,
  packet range, confidence CHECK.
- `netforensics_reports` — `report_ref` UNIQUE, full report JSON.

`.down.sql` drops indexes then tables. `db.rollback_migration()`
removes the `schema_migrations` record so the up-step can re-apply.

## Web layer (`web.py`)

- Pages: `/project_n01` (capture plan + run form + saved captures),
  `/sessions`, `/timeline`, `/anomalies` (baseline table),
  `/scoping` (memo), `/report` (facts/inference tables).
- API: `POST /api/netforensics/capture` (validated scenario/seed),
  `GET /api/netforensics/captures|/anomalies|/report`
  (`?capture_id=`, defaults to latest).
- Every page carries the lab-only banner; every JSON response carries
  `synthetic: true` + `ethical_banner`.
- Query strings use `parse_qsl(environ["QUERY_STRING"])` (the portfolio
  convention); the test client sets a real `QUERY_STRING`.

## Clock

`now_iso(clock)` — injectable, same pattern as `forensics.py`;
defaults to `db.utcnow_iso()`.

## Non-goals reflected in architecture

No capture driver abstraction (there is nothing to drive — the
generator is the only source). No plugin detector interface (three
documented threshold rules; adding ML would contradict the honesty
requirements). No real-time streaming path (captures are complete,
scripted runs).
