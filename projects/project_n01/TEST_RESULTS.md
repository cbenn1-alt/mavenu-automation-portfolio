# N01 — Test Results

**Run date:** 2026-10-23 (22:05 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/pytest tests/`
(run in 3 chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run; no disk-backed
TMPDIR used)

> ⚠ **LAWFUL LAB ONLY.** All fixtures are synthetic packets from the
> seeded generator; no real network was touched.

## Result

**1417 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| N01 new (`tests/test_netforensics.py`) | 39 | 39 passed |
| N01 new (`tests/test_netforensics_api.py`) | 15 | 15 passed |
| Prior (P01–P02, Q01–Q10, S01–S05) baseline | 1363 | 1363 passed, unchanged |

Chunk breakdown: 531 + 530 + 356 = 1417.

## Measurable criteria — verified

| Criterion (REQUIREMENTS.md §9) | Result |
|---|---|
| A1 determinism | `test_determinism_same_seed_identical_capture` — identical packet lists for same seed |
| A2 session exactness | Exfil session: 405 packets, 560,000 bytes out, handshake + teardown true, index range = ground truth; 24 probe sessions one-sided with RST teardown |
| A3 timeline = ground truth | `TestTimeline` — chronological, capture_start/end markers, one alert per anomaly with matching packet range, beacon alert range = ground-truth beacon range |
| A4 beacon interval | Detected 60.002 s vs 60 s scripted (< 1.0 s), 10 beacons, CV 0.000 ≤ 0.15 |
| A5 port scan | 24/24 ports 8000–8023 in detail; 24 `RST+DENIED` replies inside cited range |
| A6 exfil threshold | 560,000 > 102,400; anomaly range = session range |
| A7 clean baseline | `baseline_clean` → 0 anomalies, empty scope, "no anomalies detected" |
| A8 citation structure | Every anomaly + every fact/inference claim in all 4 scenarios cites a valid `[lo, hi]` |
| A9 facts/inference | Inference without confidence → `NetForensicsError`; claim without range → `NetForensicsError`; inverted range → `NetForensicsError` |
| A10 no socket/pcap | Token-aware source scan passes (docstring discussion excluded; code tokens only) |
| A11 rollback | `test_migration_rollback_for_real` — apply → save → roll back (tables gone) → re-apply |
| A12 no regressions | 1363/1363 prior tests unchanged |

## Rollback test (real, this run)

`TestPersistence::test_migration_rollback_for_real` — 2026-10-23,
Python 3.12.3/pytest 9.1.1/Linux: applied `018_netforensics.sql` via
`run_migrations()`, saved a capture (id 1), called
`rollback_migration("018_netforensics.sql")`, verified all five
`netforensics_*` tables absent, then re-applied the up-step cleanly.
