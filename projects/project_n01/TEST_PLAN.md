# N01 — Test Plan

**Module:** `src/mavenu/netforensics.py` · **Web:** `/project_n01*`,
`/api/netforensics*` · **Migration:** `018_netforensics.sql`

> ⚠ LAWFUL LAB ONLY. All fixtures are synthetic packets from the
> seeded generator; the no-socket test fails the build if capture code
> appears.

## Fixture design

No checked-in fixtures: the generator IS the fixture factory.
`generate_capture(scenario, seed)` returns `(packets, ground_truth)`;
`run_full_pipeline()` returns every intermediate artifact. Tests use
seed `20261023` unless determinism itself is under test.

Ground truth per scenario (asserted, not assumed):

| Scenario | Packets | Key ground truth |
|---|---|---|
| `baseline_clean` | 18 | 0 anomalies |
| `port_scan` | 64 | 1 `port_scan`; 24 ports 8000–8023; probes + 24 `RST+DENIED` replies in cited range |
| `c2_beaconing` | 36 | 1 `beaconing`; interval 60 s ± 1.0 s; 10 beacons; CV ≤ 0.15 |
| `data_exfiltration` | 421 | 1 `byte_exfiltration`; `bytes_out` = 560,000 > 102,400; session = 405 pkts, handshake + teardown true |

## Coverage

| Area | Tests |
|---|---|
| Ethical hard line | Token-aware source scan for socket/pcap/AF_PACKET/SOCK_RAW; banner text; documentation-range-only addressing; unknown scenario rejected |
| Generator | Determinism (same seed → identical), seed sensitivity (different seed still detects), packet schema, index ordering, payload SHA-256 coverage, scenario registry |
| Sessions | Exfil session exact (405 pkts / 560,000 B / handshake / teardown / index range = ground truth); 24 one-sided probe sessions (no handshake, RST teardown); bidirectional merge of HTTP sessions; every packet in exactly one session |
| Decoders | LAB-HTTP / LAB-DNS / LAB-BEACON grammars parse; non-matching labels → `None`; `decode_note` first-match |
| Anomalies | Clean → 0; port scan (ports, probe count, denials in range); beaconing (interval, count, CV); exfil (byte threshold, range = session range); every anomaly cites a valid packet range in all 4 scenarios |
| Timeline | Starts `capture_start`, ends `capture_end`, chronological; one alert per anomaly with matching packet range; one `session_start` per session; beacon alert range = ground-truth beacon range |
| Scoping | Hosts/sessions/window derived from anomalies; exfil names both hosts; clean → empty scope |
| Report | `ground_truth_match` true for all 4 scenarios; every claim cites a valid range; inference without confidence rejected; fact without range rejected; inverted range rejected; banner + `synthetic` flag; baseline printed |
| Persistence | Round trip (packets/sessions/anomalies/report); duplicate `capture_ref` rejected; missing tables → clear error; **migration rollback for real** (apply → use → roll back → tables gone → re-apply) |
| Web pages | Dashboard 200 with capture plan + banner; run form persists + renders sessions; unknown scenario → 422; all 5 sub-pages 200 with `?capture_id=` (real QUERY_STRING); latest-capture default; 404 with no captures; report page shows facts/inferences + ground-truth match; anomalies page shows baseline table |
| API | All 4 scenarios end-to-end (`anomalies`, `ground_truth_match`, `synthetic`, banner); bad scenario → 422; non-int seed → 422; captures list; anomalies cite ranges with `bytes_out` = 560,000; report keeps facts/inference separation (no confidence on facts); 404 with no captures |

## How to run

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/pytest tests/test_netforensics.py tests/test_netforensics_api.py -q
# full suite (3 chunks; clear /tmp/pytest-of-root between chunks — the
# 512 MB /tmp tmpfs fills during a single full-suite run; no disk-backed TMPDIR):
.venv/bin/pytest tests/ -q -x --ignore=tests/test_web.py   # chunk plan in TEST_RESULTS.md
```

## Adversarial / negative cases covered

- Unknown scenario name; non-int seed.
- Inference without confidence; fact without packet range; inverted
  range; out-of-bounds range.
- Duplicate `capture_ref` / `report_ref`.
- Persistence calls before migration → explicit `NetForensicsError`.
- Beacon jitter across seeds (detection must survive ±0.2 s jitter).
- 404 paths: sub-pages and API with zero captures; unknown capture id.
