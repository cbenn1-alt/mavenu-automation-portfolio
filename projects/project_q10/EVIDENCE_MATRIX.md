# Q10 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| HMAC-SHA256 verification, constant-time compare | Implemented, Tested | `webhooks.sign` / `verify_signature`; `test_sign_verify_roundtrip`, `test_tampered_body_fails_verification` (3 variants), `test_wrong_secret_fails`, `test_empty_and_malformed_signatures_fail` (9 variants), `test_compare_digest_is_used_for_timing_safety` |
| Strict mode rejects 100% of unsigned events | Tested | `test_strict_rejects_unsigned_or_invalid` (parametrized), `test_strict_rejects_unknown_source`; API: `test_receive_unsigned_strict_401`, `test_receive_invalid_signature_401` |
| Canonical envelope normalization + idempotency on `event_id` | Implemented, Tested | `webhooks.normalize_envelope`; `test_normalize_envelope_*` (6 tests); `test_replay_same_signature_same_event_id_is_duplicate`, `test_duplicate_event_id_delivered_once`, `test_enqueue_delivery_is_idempotent` |
| Append-only event store; status derived from lineage | Implemented, Tested | `007_webhook_hub.sql` (no UPDATE/DELETE paths in code); `webhooks.event_status`; lineage-chain tests |
| Full lineage `received → routed → queued → delivered \| dead_lettered \| rejected` | Implemented, Tested | `webhooks.record_lineage`; `test_full_lineage_received_routed_queued_delivered`, rejected-chain assertion in strict tests, `api_wh_event` detail test |
| Versioned routing rules (type + conditions → actions) | Implemented, Tested | `router.create_rule/update_rule/delete_rule`; version-bump test; `test_rule_matching_event_type_wildcard_disabled`, `test_priority_ordering`, 16-operator condition matrix |
| Dry-run shows what would happen, zero side effects; parity with real run | Implemented, Tested | `router.dry_run`; `test_dry_run_parity_with_real_run`; API `test_dry_run_endpoint` |
| Retry with exponential backoff on injectable clock | Implemented, Tested | `delivery.backoff_delay_seconds`; `test_backoff_schedule_exact` (T0+30/90/210/450s asserted exactly) |
| Dead-letter after N attempts | Implemented, Tested | `delivery.dead_letter`; `test_dead_letter_after_max_attempts` (5- and 3-attempt variants), `test_every_attempt_logged` |
| Unknown endpoints dead-letter immediately | Implemented, Tested | `test_unknown_endpoint_dead_letters_immediately`; API replay test |
| Per-endpoint circuit breaker (closed → open → half-open → closed) | Implemented, Tested | `delivery.get_circuit`, `_circuit_allows`; open/skip/half-open-fail/half-open-recover tests; retry-storm bound test |
| Every delivery attempt logged (append-only) | Implemented, Tested | `webhook_attempts`; `test_every_attempt_logged` (attempt_no + ok per row) |
| Poison events dead-letter; loop never halts | Implemented, Tested | `webhooks.process_batch` per-event isolation; 8 poison shapes; **5,000-payload seeded fuzz, zero crashes** (`test_fuzz_5000_malformed_payloads_zero_crashes`) |
| Every event reaches a terminal state | Tested | `test_every_event_reaches_terminal_state_mixed_batch` (13 events → 4/8/1 split); fuzz terminal-state assertion |
| Dead-letter replay | Implemented, Tested | `delivery.replay_dead_letter`; `test_replay_delivery_dead_letter_requeues`, `test_replay_malformed_dead_letter_refused`; API replay tests |
| Transform actions never re-enter routing | Implemented | `router.apply_routes` loop guard; `test_transform_action_stores_derived_and_never_reroutes`; ARCHITECTURE.md |
| Full payloads never logged (redacted summaries only) | Implemented, Tested | `webhooks.redacted_summary`; `test_redacted_summary_never_contains_values`, `test_log_action_emits_redacted_line` |
| Migration rollback tested for real | Implemented, Tested | `007_webhook_hub.down.sql`; `test_migration_007_down_step_rolls_back_for_real` (run 2026-10-23) |
| Dashboard pages + JSON API | Implemented, Tested | `web.py` `/project_q10*` + `/api/webhooks*`; 17 API tests; page-render tests incl. synthetic banner |
| Demo verifier uses documented test-only secrets | Simulated (labeled) | `TEST_WEBHOOK_SECRETS` docstring; README banner; SECURITY.md real-deployment requirements |
| Stub endpoints (in-process, no real SaaS/HTTP) | Simulated (labeled) | `web._stub_webhook_sink`; README banner; dashboard copy |
| All events/payloads synthetic | Demo | Invented fixtures; SYNTHETIC DEMO DATA banner; fuzz uses RNG |
| No production deployment / no real integrations / no real users | — (not claimed) | Honest-status banner; no such claim anywhere |
| P01/P02/Q01/Q02/Q03/Q04 regression-free | Tested | Full suite `637 passed` 2026-10-23 (TEST_RESULTS.md) |

## Claim-grade summary

- **Measured (tests):** HMAC valid/invalid/tampered/replay behavior;
  strict-mode rejection rate on tested variants; backoff datetimes exact;
  dead-letter thresholds; circuit transitions; fuzz crash count (0);
  terminal-state coverage (100% of test events); dry-run/real-run parity;
  rollback round-trip.
- **Labeled estimates:** none — no performance or business numbers are
  claimed in v1.
- **Not claimed:** production deployment, real SaaS integrations, real
  users, real webhook traffic.
