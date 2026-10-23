# Q10 — Webhook Integration Hub: Security

## Threat model (implemented mitigations)

| Threat | Mitigation | Test |
|---|---|---|
| Forged webhooks | HMAC-SHA256 verification with `hmac.compare_digest` (constant-time); strict mode (default ON) rejects unsigned/invalid/unknown-source events — stored with `rejected` lineage, never routed | `test_strict_rejects_unsigned_or_invalid`, `test_compare_digest_is_used_for_timing_safety` |
| Signature replay | Idempotency on `event_id`: a replayed body+signature returns the stored event; nothing re-routes, nothing re-delivers | `test_replay_same_signature_same_event_id_is_duplicate` |
| Poison events crashing routing | Per-event try/except in `process_batch`/`process_envelope` → `malformed_envelope` / `routing_error` dead-letters; loop never halts (5k fuzz, zero crashes) | fuzz + poison tests |
| Retry storms | Exponential backoff (30s·2^(n-1), cap 1h) + per-endpoint circuit breaker (3 failures → open, 60s cooldown, one half-open probe per run) | circuit + storm tests |
| Secret leakage in logs | `redacted_summary()` — key names + value types only — is the sole payload-derived content in stdout, lineage detail, dead-letter detail, and API responses | `test_redacted_summary_never_contains_values`, `test_log_action_emits_redacted_line` |
| SQL injection | Parameterized queries everywhere; no string-interpolated SQL (the one `f-string` in `router.update_rule` interpolates only column names from a fixed allowlist) | code review; test suite passes |
| Transform routing loops | Transform actions store derived envelopes as data; they never re-enter routing (documented loop guard) | `test_transform_action_stores_derived_and_never_reroutes` |

## Secret management — requirements for real deployments

The bundled verifier uses **documented test-only secrets**
(`webhooks.TEST_WEBHOOK_SECRETS`). A real deployment MUST:

1. **Never use the test secrets.** Set `MAVENU_WEBHOOK_STRICT=1` (the
   default) and supply per-source secrets via the `MAVENU_WEBHOOK_SECRETS`
   environment variable (JSON object `{"source": "secret"}`) or, better, a
   secret manager (e.g. the platform's managed secrets). `load_secrets()`
   already prefers the environment over the test defaults.
2. **Generate secrets with `secrets.token_hex(32)`** (or equivalent),
   one per source, rotatable independently.
3. **Rotate on suspicion of compromise**: generate new → deploy alongside
   old (dual-accept window) → retire old. The per-source secret map makes
   this a config change, not a code change.
4. **Never commit secrets** to the repo, logs, or dead-letter details.
   Dead-letter `detail_json` carries redacted summaries only.
5. **Serve ingest over TLS** and put it behind the same auth/rate-limiting
   posture as any other public endpoint (out of scope for this stdlib
   demo, required in production).

## PII — field allowlists (required before any real deployment)

v1 stores the full envelope in the append-only event store because **all
data is synthetic**. A real deployment handling personal data MUST:

1. Define a per-`event_type` **field allowlist** (e.g. `lead.created` may
   keep `payload.name`, `payload.service`, `payload.zip` — never free-text
   notes, never raw phone numbers).
2. Apply the allowlist at ingest: drop or hash non-allowlisted fields
   before `webhook_events` insert. The choke point is
   `webhooks.ingest_event` — add the filter there, not in callers.
3. Keep `redacted_summary()` as the only payload shape in logs, lineage,
   dead letters, and API responses (already the case).
4. Document a retention policy and a purge routine (cf. Q04's 90-day
   `purge_old_conversations` pattern) before storing anything real.

## Residual risks (acknowledged)

- The demo's stub endpoints perform no authentication — by design (no
  network). A real delivery adapter must authenticate to the target SaaS
  (OAuth/API key from the secret manager) and validate TLS.
- The delivery loop runs on demand (`POST /api/webhooks/deliver/run`); a
  real deployment needs a scheduler/worker with at-least-once semantics
  and alerting on dead-letter growth.
- Timing: `hmac.compare_digest` is used, but no formal side-channel
  analysis was performed (out of scope for this demo).
