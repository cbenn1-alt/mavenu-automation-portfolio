# N01 — Evidence Matrix

Every public claim → the test or artifact that backs it, or its honest label.

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | Seeded synthetic-packet generator for 4 scripted scenarios | **Tested** | `tests/test_netforensics.py::TestGenerator` — determinism, schema, hash coverage, registry |
| 2 | Same (scenario, seed) → identical capture | **Tested** | `test_determinism_same_seed_identical_capture` |
| 3 | Bidirectional 5-tuple session reconstruction with handshake/teardown tracking | **Tested** | `TestSessions` — exfil session exact (405 pkts / 560,000 B / handshake+teardown / index range = ground truth); 24 one-sided probe sessions; bidirectional HTTP merge; every packet in exactly one session |
| 4 | Decoder stubs for 3 documented synthetic protocols | **Tested** | `TestDecoders` — LAB-HTTP / LAB-DNS / LAB-BEACON grammars parse; non-matching → None |
| 5 | Timeline matches scripted ground truth | **Tested** | `TestTimeline` — chronological, capture_start/end markers, one alert per anomaly with matching packet range, beacon alert range = ground-truth range |
| 6 | Port scan flagged (24 ports, denials in range) | **Tested** | `test_port_scan_flagged` — ports 8000–8023, 24 probes, 24 `RST+DENIED` replies inside cited range |
| 7 | Beaconing flagged with correct interval | **Tested** | `test_beaconing_flagged_with_correct_interval` — detected 60.002 s vs 60 s scripted, 10 beacons, CV ≤ 0.15; survives seed jitter |
| 8 | Exfil flagged on byte-count deviation | **Tested** | `test_exfil_flagged_on_byte_deviation` — 560,000 > 102,400 threshold; range = session range |
| 9 | Baseline-clean scenario → zero anomalies | **Tested** | `test_baseline_clean_zero_anomalies` + empty scope |
| 10 | Every anomaly cites a packet range | **Tested** | `test_every_anomaly_cites_packet_range` — all 4 scenarios |
| 11 | Every report claim cites a packet range (structurally enforced) | **Tested** | `test_every_claim_cites_packet_range`; `build_report` raises `NetForensicsError` on missing/inverted/out-of-bounds ranges |
| 12 | Facts/inference separation enforced | **Tested** | Inference without confidence rejected; facts carry no confidence (`test_report_endpoint_fact_inference_separation`) |
| 13 | Incident scoping derived from anomalies | **Tested** | `TestScoping` — hosts, sessions, window; exfil names both hosts; clean → empty scope |
| 14 | Documented baseline (named thresholds) printed in reports | **Implemented + Tested** | `BASELINE` dict; `test_baseline_printed_in_report`; anomalies page renders the baseline table |
| 15 | SQLite persistence (captures/packets/sessions/anomalies/reports) | **Tested** | `test_round_trip`; duplicate `capture_ref` rejected; missing tables → explicit error |
| 16 | Migration rollback tested for real | **Tested** | `test_migration_rollback_for_real` (2026-10-23, Python 3.12.3/pytest 9.1.1/Linux) — apply → use → roll back → re-apply |
| 17 | Web pages: plan, sessions, timeline, anomalies, scoping, report | **Tested** | `TestN01Pages` — 200s, capture-plan content, banner, run-form persistence, 422/404 paths |
| 18 | JSON API: capture/captures/anomalies/report | **Tested** | `TestN01Api` — all 4 scenarios end-to-end with `ground_truth_match: true`; 422/404 envelopes |
| 19 | No socket/pcap code | **Tested** | `TestNoCaptureCode::test_module_contains_no_socket_or_pcap` — token-aware source scan |
| 20 | Lab-only addressing (documentation ranges) | **Tested** | `test_all_addresses_are_documentation_ranges` — 192.0.2.x / 203.0.113.x only |
| 21 | No regressions | **Tested** | 1417/1417 (1363 prior + 54 N01), 0 failed — TEST_RESULTS.md |
| 22 | The "captured network" is synthetic packets, not a real tap | **Simulated** | Module docstring + README banner + lab-only banner on every page/API response |
| 23 | Demo report inferences are script-generated | **Synthetic** (labeled) | `_scripted_inferences()` docstring; report `synthetic: true` |
| 24 | Baseline thresholds are lab choices, not production measurements | **Documented estimate** | REQUIREMENTS.md §6; ARCHITECTURE.md decision #4 |
| 25 | Real networks captured | **NOT claimed** | README "NOT claimed"; SECURITY.md risk #1 control |
| 26 | Forensic casework experience | **NOT claimed** | README "NOT claimed" row; every surface says synthetic/lab-only |
| 27 | Production deployment / real users | **NOT claimed** | README "NOT claimed" row |
| 28 | Attribution beyond the lab | **NOT claimed** | REQUIREMENTS.md §9 non-goals; scoping derives hosts only from anomaly details |
