# Q10 — Webhook Integration Hub: Test Plan

**Method:** pytest via `.venv` (Python 3.12.3, pytest 9.1.1, Linux).
**Suites:** `tests/test_webhooks.py` (core services), `tests/test_webhooks_api.py`
(HTTP/API layer). All fixtures synthetic; signatures use the documented
test-only secrets; stub endpoints are in-process callables.

## 1. HMAC verification (`test_webhooks.py`)

| Case | How |
|---|---|
| Valid signature verifies | `sign` → `verify_signature` round-trip |
| Tampered body fails | append / flip-byte / truncate parametrized |
| Wrong secret fails | sign with another secret |
| Malformed signatures fail | `""`, `None`, `sha256=`, short/long hex, wrong prefix, non-signature — parametrized, never raise |
| Constant-time comparison | spy on `hmac.compare_digest`, assert it is called |

## 2. Strict-mode rejection

- Unsigned / invalid-signature / unknown-source events → `accepted=False`,
  correct `rejection_reason`, stored with `rejected` lineage, zero
  deliveries, zero routing (parametrized).
- Non-strict mode accepts unsigned but flags `verified=False`,
  `signature_ok=0`.
- Replay: same body+signature twice → second is `duplicate=True`, one event
  row, one set of deliveries.

## 3. Envelope normalization & privacy

- Happy path, generated `event_id`/`occurred_at` defaults, empty
  `event_id` regenerated; 9 malformed shapes raise `EnvelopeError`.
- `redacted_summary` exposes keys + types, never values.

## 4. Routing rules

- CRUD + version bump on update + duplicate-name rejection + field
  validation.
- Matching: exact event type, `*` wildcard, disabled rules skipped,
  priority ordering.
- All 16 condition operators parametrized (`eq/ne/gt/gte/lt/lte/contains/
  startswith/exists/in`); `exists:false`; missing fields never match;
  type mismatches never match and never crash.
- **Dry-run parity**: `dry_run()` plan == `plan_actions()` == real-run
  executed actions; dry-run creates no deliveries, no derived rows.
- Transform stores derived envelope, never creates a new event.
- Log action emits redacted stdout (secret values absent, keys present).

## 5. Retry / backoff (injectable clock)

- Exact schedule asserted: attempt N → `next_attempt_at` = T0 + 30/90/210/450s.
- Dead-letter after `max_attempts` (3 and 5 variants): state, reason,
  lineage, attempt-row count.
- Flaky-then-healthy endpoint recovers to `delivered`.
- Unknown endpoint → immediate `unknown_endpoint` dead-letter (no retries,
  no circuit noise).

## 6. Circuit breaker

- Opens after 3 consecutive failures; while open, due deliveries are
  skipped (`skipped_circuit_open`), zero attempts.
- Half-open after 60s cooldown: exactly one probe; probe failure re-opens
  (failures=4); probe success closes and resets.
- Retry-storm bound: 20 failing deliveries over 6 loop runs → total attempts
  ≤ 8 (3 to open + one probe per run).

## 7. Poison isolation & fuzz

- 8 malformed-body shapes → `malformed_envelope` dead-letter, loop continues.
- **5,000-payload seeded fuzz** (`random.Random(20261023)`) through
  `process_batch`: exact accounting invariants
  (`accepted+rejected == 5000`; `poison+duplicate+routed+routing_failed ==
  accepted`), zero exceptions, every event in a terminal state.
- Routing exception (invalid transform spec) → `routing_error`
  dead-letter; batch continues with the next event.

## 8. Idempotency

- Duplicate `event_id` → one delivery per endpoint, one attempt per
  endpoint after the loop (delivered once).
- `enqueue_delivery` twice → same row (UNIQUE + INSERT OR IGNORE).

## 9. Lineage & terminal states

- Full chain asserted: `received → routed → queued → delivered`;
  rejection chain: `received → rejected`.
- Every attempt logged with attempt number + outcome.
- Log-only actions settle to `delivered` with no deliveries.
- **Mixed batch (13 events)**: signed→failing endpoint, signed→good
  endpoint, unsigned (strict), 2 poison → drain loop → every event in
  `{delivered, dead_lettered, rejected}` with full lineage
  (4 / 8 / 1 split asserted).

## 10. Dead-letter replay

- Delivery-level dead letter → replay resets to queued, loop delivers,
  event reaches `delivered`, dead letter marked `replayed=1`.
- Malformed-envelope dead letter → replay raises `ValueError` (refused).

## 11. API layer (`test_webhooks_api.py`)

- Signed POST → 201 + routing plan; unsigned → 401; invalid signature →
  401; duplicate → 200; poison → 201 + dead-lettered; invalid JSON → 422.
- Events list + `status` filter; detail with lineage + deliveries; 404 on
  unknown.
- Routes CRUD incl. version bump, validation 422s, dry-run endpoint (+422
  on bad envelope), idempotent seed.
- Deliver queue view + `state` filter (+422 on bad state); `deliver/run`;
  dead-letters list; replay (200, 404 on unknown); endpoints view.
- `/project_q10` and `/project_q10/dead-letters` render 200 with the
  synthetic-data banner.

## 12. Migration rollback

- `007_webhook_hub.sql` down-step: 8 tables dropped, migration record
  removed, `run_migrations` re-applies cleanly — tested for real.

## Measurable criteria (from spec) → tests

| Criterion | Test |
|---|---|
| 100% of unsigned events rejected in strict mode | `test_strict_rejects_unsigned_or_invalid` (parametrized), `test_strict_rejects_unknown_source` |
| Zero loop crashes across fuzzed payloads | `test_fuzz_5000_malformed_payloads_zero_crashes` |
| Every event reaches a terminal state with full lineage | `test_every_event_reaches_terminal_state_mixed_batch`, fuzz terminal assertion, `test_full_lineage_received_routed_queued_delivered` |
