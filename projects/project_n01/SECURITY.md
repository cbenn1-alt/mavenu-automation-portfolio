# N01 — Security

> ⚠ **LAWFUL LAB ONLY.** This project generates synthetic packets
> in-process. It contains no socket/pcap code and cannot capture a real
> network. Never capture a real network without explicit written
> authorization from its owner.

## Threat model (what this project actually risks)

N01's attack surface is small by design: it processes only packets it
generated itself, in a single-threaded stdlib WSGI app, with no network
I/O at runtime.

| # | Risk | Control |
|---|---|---|
| 1 | Misuse: pointing the "capture" workflow at a real network | **Structural**: no socket/pcap/raw code exists; `TestNoCaptureCode` fails the build if capture tokens appear. Docs banner every surface. The generator only emits synthetic dicts. |
| 2 | Overclaiming: presenting the demo as casework experience | README "NOT claimed" row; `synthetic: true` + ethical banner on every page and API response; EVIDENCE_MATRIX marks simulated/synthetic claims |
| 3 | Uncited claims in reports | `build_report()` structurally rejects claims without a valid `[lo, hi]` packet range; rejected inferences without confidence |
| 4 | SQL injection via capture refs / query params | Parameterized queries only (no string-interpolated SQL anywhere in `netforensics.py`); `capture_id` parsed as `int`, invalid → treated as missing |
| 5 | Synthetic data mistaken for real | Documentation/test-net addressing only (`192.0.2.x`, `203.0.113.x`) — a test asserts no other prefixes appear; payloads are labels, hashed, never content |
| 6 | XSS in rendered packet labels/session keys | All user-influenced strings `html.escape`d in web handlers (labels are generated, but defense-in-depth) |

## Input validation boundaries

- `generate_capture(scenario, seed)`: scenario must be in `SCENARIOS`;
  seed must be `int` — else `NetForensicsError`.
- `save_capture/save_report`: `capture_ref`/`report_ref` required,
  non-blank (`ValidationError`); UNIQUE enforced in SQLite, duplicates
  → `NetForensicsError`.
- `build_report()`: packet ranges validated `0 ≤ lo ≤ hi <
  packet_count`; inference confidence ∈ `low/medium/high`.
- API: unknown scenario → 422; non-int seed → 422; malformed JSON →
  422 envelope; no-capture reads → 404 envelope (never 500).

## What this project does NOT protect against (out of scope)

- Real-world sensor security (there is no sensor).
- Encrypted-traffic analysis — payloads are synthetic labels; the
  decoders parse label grammars, not protocols on the wire.
- Adversarial evasion of the threshold detectors — the baseline is a
  documented lab baseline, not a hardened IDS ruleset.

## Secrets

None. No credentials, keys, or tokens anywhere in the module,
migration, or tests.
