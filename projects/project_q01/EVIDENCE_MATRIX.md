# Q01 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| Missed-call ingestion (CSV + JSON webhook shape) | Implemented, Tested | `missed_calls.ingest_csv` / `ingest_event`; `tests/test_missed_calls.py` (ingestion + CSV blocks); `POST /api/missed-calls`, `POST /api/missed-calls/import` |
| Server-side validation with row-level CSV errors | Implemented, Tested | `normalize_event()`; `test_csv_ingest_batch_with_row_level_errors`, validation tests |
| Duplicate protection (dedup key + idempotency key) | Implemented, Tested | `dedup_key` UNIQUE; `call_idempotency_keys`; `test_duplicate_event_does_not_create_new_row`, `test_ingest_idempotency_key_replays_without_duplicate`, API replay tests |
| Deterministic rule-based urgency scoring | Implemented, Tested | `urgency.DeterministicDemoScorer`; `tests/test_urgency_scorer.py` (20 tests incl. 10k-replay determinism) |
| `UrgencyScorer` replaceable protocol | Implemented | `urgency.UrgencyScorer` Protocol; scorer injected into `ingest_event`/`ingest_csv` |
| Priority callback queue (score × age decay) | Implemented, Tested | `priority_queue()`; ordering + decay-formula tests |
| Claim/assign | Implemented, Tested | `claim_call()`; 4 claim tests + API test |
| Outcome tracking `pending → attempted → connected → booked \| lost` | Implemented, Tested | `CALL_WORKFLOW`; `log_outcome()`; 10 parametrized illegal-transition tests |
| SLA-escalation sweep | Implemented, Tested | `sweep_sla()`; 3 escalation tests; `POST /api/missed-calls/sla-sweep` |
| Ingestion-lag alert | Implemented, Tested (stub) | `ingestion_lag_report()`; 3 lag tests; labeled stub in README |
| Caller IDs masked + hashed, raw never stored | Implemented, Tested | `mask_caller_id`/`hash_caller_id`; `test_raw_caller_id_never_stored` (full-table scan) |
| Repeat-ID anomaly flag (never auto-trust) | Implemented, Tested | flag logic in `ingest_event`; `test_third_call_in_window_flags_repeat_id_anomaly` |
| Recovery dashboard; totals reconcile | Implemented, Tested | `dashboard_stats()`; `/project_q01/dashboard`; `test_dashboard_reconciles_with_source_rows` (independent SQL re-computation) |
| Migration rollback tested | Implemented, Tested | `003_missed_calls.down.sql`; `db.rollback_migration()`; `test_migration_003_down_step_rolls_back_for_real` (run 2026-10-23) |
| Ingestion p95 < 5 ms/event | Tested | `test_ingestion_p95_under_5ms_per_event`; measured p95 0.279 ms (TEST_RESULTS.md) |
| Urgency scorer is rules, not a model | Simulated (labeled) | README "What is simulated"; module docstring banner; weights documented in `urgency.py` |
| Fixture ingestion — no telephony integration | Simulated (labeled) | README "What is simulated"; DEMO.md talking points |
| Owner notifications are stubs | Simulated (labeled) | `status='queued-stub'`; honest stub text in message body; README + SECURITY.md |
| All call data synthetic | Demo | Fictional 555 fixtures; SYNTHETIC DEMO DATA banner in `web.py` |
| No production deployment / no real users | — (not claimed) | Honest-status banner in README; no such claim anywhere |
| No TCPA-compliance review performed | — (explicitly not claimed) | README banner; SECURITY.md TCPA section advising counsel |
| P01/P02 regression-free | Tested | Full suite `241 passed` 2026-10-23 (TEST_RESULTS.md) |

## Claim-grade summary

- **Verified on the custom stack:** ingestion, validation, dedup +
  idempotency, deterministic scoring, priority queueing, state-machine
  outcomes, SLA escalation path, dashboard reconciliation, migration
  rollback, caller-ID privacy handling.
- **Simulated, labeled:** the urgency ruleset (not a model), fixture
  ingestion (no telephony), owner notifications (stubs), sweep scheduling.
- **Not demonstrated:** real telephony hookup, actual notification
  delivery, TCPA-compliant dialing, authenticated multi-user access,
  retention enforcement.
