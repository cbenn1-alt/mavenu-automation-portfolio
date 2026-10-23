# Q10 — Webhook Integration Hub

**Status: Implemented · Tested** — 105 automated tests, all passing
(637/637 full suite: 532 prior + 105 new; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | HMAC-SHA256 signature verification (`hmac` + `hmac.compare_digest`, constant-time; tested: valid / invalid / tampered / wrong-secret / malformed / replay); strict mode rejecting 100% of unsigned events (tested across missing/invalid/unknown-source variants); canonical envelope normalization with idempotency on `event_id`; append-only SQLite event store (`webhook_events`) with append-only lineage log (`webhook_lineage`) — current status is *derived*, never mutated; versioned routing rules (event type + JSON conditions → log/transform/forward actions) with dry-run/real-run parity tested; retry queue with exponential backoff on an injectable clock (exact schedule asserted); dead-letter after N attempts (tested); per-endpoint circuit breaker (closed → open → half-open → closed, tested incl. single-probe-per-run); per-event isolation — poison events dead-letter, the loop never halts (5,000-payload fuzz, zero crashes); every delivery attempt logged (append-only); full lineage `received → routed → queued → delivered | dead_lettered | rejected`; migration rollback tested for real |
| What is SIMULATED | **Simulated** | The signature verifier ships with **documented test-only secrets** (`TEST_WEBHOOK_SECRETS`) so the demo and tests can sign bodies with no real credential — they must never be treated as real secrets. Forwarding targets are **in-process stub callables** (`stub:crm-sink`, `stub:calendar-sink`, `stub:sheet-sink`) — no HTTP, no real SaaS, no third-party credentials anywhere. The "sender" in every demo is a curl command or the test suite |
| What is SYNTHETIC | **Synthetic** | Every event, payload, source name, and dead-letter is invented ("demo-form", "Sample Lead"). No real people, no real businesses, no real webhook traffic |
| What is NOT claimed | — | No production deployment. No real users, no real SaaS integrations, no real third-party credentials. Not a hosted integration platform — this is a working reference implementation of the ingest → route → deliver → audit pattern |

## Business problem

Form tools, calendars, and spreadsheets don't talk to each other.
Workarounds are manual copy-paste or fragile zap-chains nobody documented —
when one breaks, nobody knows what was lost.

## Implemented capabilities

- **Ingest** (`src/mavenu/webhooks.py`): raw body → HMAC-SHA256 verification
  against per-source secrets → canonical envelope normalization
  (`envelope_version`, `event_id`, `source`, `event_type`, `occurred_at`,
  `payload`) → append-only store. Strict mode (default ON) rejects unsigned /
  invalid / unknown-source events with a `rejected` lineage row — never routed.
  Duplicate `event_id` → idempotent no-op (same event delivered once).
  Malformed bodies → poison path: stored, immediately dead-lettered
  (`malformed_envelope`), loop continues.
- **Routing** (`src/mavenu/router.py`): versioned rules —
  `event_type` (`*` = wildcard) + JSON conditions (`eq/ne/gt/gte/lt/lte/`
  `contains/startswith/exists/in` over dotted envelope paths) → ordered action
  list. Actions: `log` (structured stdout line, redacted payload), `transform`
  (field projection stored in `webhook_derived`; never re-enters routing —
  documented loop guard), `forward` (enqueue delivery, idempotent on
  `(event_id, endpoint)`). `dry_run()` returns exactly what `apply_routes()`
  would do, with zero side effects — parity is pinned by tests. Rule updates
  bump `version`; deliveries record the rule version that created them.
- **Delivery** (`src/mavenu/delivery.py`): retry queue with exponential
  backoff (`base 30s × 2^(n-1)`, capped at 1h) on an injectable clock;
  dead-letter after `max_attempts` (default 5); unknown endpoints dead-letter
  immediately (permanent config error — no wasted retries, no circuit noise);
  per-endpoint circuit breaker (`closed → open` after 3 consecutive failures,
  60s cooldown, exactly one half-open probe per loop run, success closes /
  failure re-opens); every attempt logged append-only with outcome + detail.
  `settle_event()` moves each event to a terminal lineage state
  (`delivered` / `dead_lettered`) once nothing is pending; replayed dead
  letters get a second chance instead of blocking the terminal state.
- **Isolation** (`webhooks.process_batch` / `process_envelope`): per-event
  try/except converts routing exceptions to `routing_error` dead-letters —
  the loop never halts, verified over 5,000 fuzzed malformed payloads.
- **Privacy**: full payloads are never written to stdout, lineage detail,
  dead-letter detail, or API responses — only `redacted_summary()` (key names
  + value types). See SECURITY.md for the field-allowlist requirements of a
  real deployment.
- **Web UI + JSON API** (`web.py`): `/project_q10` dashboard (status counts,
  recent events, rules, circuit states, dead letters) with a copy-paste curl
  walkthrough; `/project_q10/dead-letters`; `/api/webhooks/events` (receive,
  list, detail+lineage), `/api/webhooks/routes*` (CRUD, dry-run, seed),
  `/api/webhooks/deliver/run`, `/api/webhooks/deliveries`,
  `/api/webhooks/dead-letters` (+ replay), `/api/webhooks/endpoints`.

## Case-study narrative

"Leads came in by form, bookings lived in a calendar, and nobody connected
them except an office manager with two monitors. We built a hub that
verifies, routes, retries, and remembers — with a dry-run mode so every
rule is proven before it touches anything real."
