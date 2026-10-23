# Q10 — Webhook Integration Hub: Requirements

**Status:** Implemented · Tested (2026-10-23). All requirements below are
covered by automated tests; see EVIDENCE_MATRIX.md.

## Functional requirements

1. **Ingest webhook events** — accept a raw HTTP body, normalize it to a
   canonical event envelope
   (`envelope_version`, `event_id`, `source`, `event_type`, `occurred_at`,
   `payload`). Missing `source`/`event_type` or a non-object `payload` is a
   malformed envelope.
2. **HMAC verification (real)** — verify HMAC-SHA256 signatures with
   `hmac.compare_digest` (constant-time). Secrets are per-source.
3. **Demo verifier with documented test secrets (simulated)** — the bundled
   verifier uses `TEST_WEBHOOK_SECRETS`, labeled test-only in code and docs.
   Real deployments must supply secrets via `MAVENU_WEBHOOK_SECRETS`
   (environment JSON) or a secret manager.
4. **Strict mode** — default ON: unsigned, invalid-signature, or
   unknown-source events are rejected (stored + `rejected` lineage, never
   routed). Non-strict mode accepts them flagged `verified=False`.
5. **Idempotency** — same `event_id` ingested twice → the stored event is
   returned, nothing is re-routed, nothing is re-delivered.
6. **Rule-based routing** — versioned rules: `event_type` (+ `*` wildcard)
   and a condition list → ordered actions (`log`, `transform`, `forward`).
   Conditions: `eq/ne/gt/gte/lt/lte/contains/startswith/exists/in` over
   dotted envelope paths; type mismatches never match and never crash.
7. **Dry-run** — show exactly what routing *would* do (matched rules,
   actions, forward targets) with zero side effects; parity with the real
   run is tested.
8. **Retry with backoff** — exponential backoff `30s × 2^(n-1)` capped at
   1h, on an injectable clock (deterministic tests).
9. **Dead-letter queue** — after `max_attempts` (default 5) exhausted
   retries; immediately for unknown endpoints (permanent config error) and
   malformed envelopes. Delivery-level dead letters are replayable;
   malformed-envelope dead letters are inspection-only.
10. **Circuit breaker** — per endpoint: `closed → open` after 3 consecutive
    failures, 60s cooldown, exactly one half-open probe per loop run;
    success closes, failure re-opens.
11. **Attempt logging** — every delivery attempt (success or failure) is
    logged append-only with attempt number, endpoint, outcome, detail.
12. **Full lineage** — append-only `received → routed → queued →
    delivered | dead_lettered | rejected` per event; current status is
    derived from the lineage log, never mutated in place.
13. **Terminal state for every event** — every accepted, rejected, or poison
    event ends in `delivered`, `dead_lettered`, or `rejected` with complete
    lineage.
14. **No real third-party credentials; stub endpoints only** — forwarding
    targets are in-process callables, never real HTTP.

## Non-functional requirements

- **Zero cost**: Python 3.12 stdlib only at runtime (`wsgiref`, `sqlite3`,
  `hmac`/`hashlib`); no network calls.
- **Synthetic data only**: every event and payload is invented.
- **No regressions**: the 532 pre-existing tests keep passing.
- **Reproducibility**: injectable clock for all time-dependent behavior;
  seeded RNG for fuzz tests.
- **Privacy**: never log full payloads (stdout, lineage detail,
  dead-letter detail, API responses) — redacted summaries only.

## Explicit non-requirements (v1)

- No real SaaS integrations, no real HTTP delivery, no OAuth/secret
  rotation (documented as real-deployment requirements in SECURITY.md).
- No at-least-once cross-process guarantees: the loop is invoked via
  `POST /api/webhooks/deliver/run` (a real deployment would run it on a
  scheduler/worker).
- No payload schema registry; transforms are field projections, not a
  mapping DSL.
