# Q03 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| RFM feature computation over synthetic job history | Implemented, Tested | `rfm.compute_rfm`; `tests/test_reactivation.py` (4 RFM tests, hand-computed 205.0d / 2 / 40000¢) |
| Dormancy scoring behind replaceable protocol, documented weights 0.50/0.30/0.20 | Implemented, Tested | `rfm.DormancyScorer`, `rfm.DeterministicDemoScorer`; weight tests incl. hand-computed 0.681; reason lines per weight |
| Scoring determinism 100% across replays | Tested | 1,000 scorer replays + 50 full re-scoring runs identical (`test_dormancy_score_deterministic_across_replays`, `test_score_customers_deterministic_across_replays`) |
| Segment assignment with documented boundaries | Implemented, Tested | `reactivation.segment_for_score`; 9 parametrized boundary tests; `api_rx_scoring_info` |
| Per-segment win-back sequences | Implemented, Tested | `reactivation.SEQUENCE_PLANS` (cooling 2 / dormant 3 / churned 2 / active 0); due-step tests; `POST /api/reactivation/winback-run` |
| Outbox with idempotency keys; zero duplicates across replays | Implemented, Tested | UNIQUE `idempotency_key` (`rx:<id>:seg:<seg>:step:<n>`); 201 replay runs → 1 row; `ON CONFLICT DO NOTHING` |
| Suppression honored absolutely (DNC / recent complaint / active job) | Implemented, Tested | `suppression_reason()` checked in `run_winback` AND re-checked in `flush_outbox`; 300-customer adversarial test with mid-sequence flips: 0 suppressed customers holding queued/sent touches; mid-sequence complaint/DNC tests prove the adapter is never called |
| Stub send adapter + send log; v1 sends nothing | Implemented, Tested (stub) | `cadence.StubMessageAdapter` (shared seam); `flush_outbox()`; `send_log` UNIQUE(outbox_id); flush tests; labeled stub in README/UI |
| Holdout split + return-rate attribution, CI | Implemented, Tested | `attribution.split_holdout` (SHA-256 deterministic); `attribution_report` (traced bookings, Wald 95% CI); 8 attribution tests |
| Attribution arithmetic verified against hand-computed fixtures | Tested | `test_attribution_matches_hand_computed_fixture` (treated 1/3, control 1/3, lift 0.0, CI ±0.7544, 1 attributed booking); untraced/post-dated touch exclusion tests |
| Segment/suppression reports reconcile to rows | Implemented, Tested | `segment_report`, `suppression_audit`; independent raw-SQL re-computation tests |
| Migration rollback tested | Implemented, Tested | `005_reactivation.down.sql`; `db.rollback_migration()`; `test_migration_005_down_step_rolls_back_for_real` (run 2026-10-23) |
| Actor-stamped audit trail | Implemented, Tested | `reactivation_events` rows + stdout JSON lines; asserted in scoring/suppression/flush tests |
| Outbox is not a messaging system — "the automation is the scoring, the sequence computation, and the audit trail" | Simulated (labeled) | README "What is simulated"; `StubMessageAdapter` docstring; honest stub text; RUNBOOK incident notes |
| Triggered (not scheduled) execution | Simulated (labeled) | Runs via button/API; scheduler wiring documented as an ops step in RUNBOOK |
| All customer/job data synthetic | Demo | Fictional fixtures ("Acme Test Co"); SYNTHETIC DEMO DATA banner in `web.py`; no real PII in code or tests |
| Attribution numbers are a synthetic-data illustration, never measured lift | Demo (labeled) | `SYNTHETIC_LABEL` in the API response, the UI page, and `attribution.py`; README banner |
| No production deployment / no real messages sent / no real users | — (not claimed) | Honest-status banner in README; no such claim anywhere |
| No CAN-SPAM/TCPA-compliance review performed | — (explicitly not claimed) | README banner; SECURITY.md section advising counsel |
| P01/P02/Q01/Q02 regression-free | Tested | Full suite `430 passed` 2026-10-23 (TEST_RESULTS.md) |

## Claim-grade summary

- **Verified on the custom stack:** RFM computation, documented-weight
  dormancy scoring (deterministic), exact segment boundaries, per-segment
  sequences with due-step queueing, idempotent outbox (201 replays, zero
  duplicates), absolute suppression incl. mid-sequence flag changes
  (adapter never called), stub flush + send log, deterministic holdout
  split, traced-booking attribution arithmetic, Wald CI, reconciled
  segment/suppression reports, migration rollback, full audit trail.
- **Simulated, labeled:** message delivery (stub adapter), scheduled
  execution (triggered).
- **Synthetic, labeled:** all customer/job/touch/booking data; every
  attribution lift/interval is an illustration of the arithmetic.
- **Not demonstrated:** real provider integration, consent/opt-out legal
  review, authenticated multi-user access, retention enforcement.
