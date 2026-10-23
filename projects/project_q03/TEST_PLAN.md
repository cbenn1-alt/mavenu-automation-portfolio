# Q03 — Test Plan

Run from the repo root: `.venv/bin/python -m pytest tests/test_reactivation.py
tests/test_attribution.py tests/test_reactivation_api.py -q` (expect 56 passed).

## 1. RFM feature computation (`tests/test_reactivation.py`)

| Test | What it proves |
|---|---|
| `test_compute_rfm_matches_hand_computed_fixture` | recency 205.0d / frequency 2 / monetary 40000¢ match hand computation exactly |
| `test_compute_rfm_no_history` | no-history customers: recency None, frequency/monetary 0 |
| `test_compute_rfm_ignores_future_jobs` | future-dated jobs are not history |
| `test_compute_rfm_requires_aware_now` | naive datetimes rejected (frozen clock is UTC-aware) |

## 2. Dormancy scoring: weights + determinism

| Test | What it proves |
|---|---|
| `test_dormancy_score_matches_hand_computed_weights` | 0.50/0.30/0.20 weights produce the hand-computed 0.681; 3 reason lines (one per weight) |
| `test_dormancy_score_no_history_is_fully_dormant` | no history → 1.0 with `no-history` flag |
| `test_dormancy_score_perfect_customer_is_zero` | recency 0 + capped frequency/monetary → 0.0 |
| `test_dormancy_score_deterministic_across_replays` | 1,000 scorer replays + key-order variation → identical results |
| `test_dormancy_score_explains_every_weight` | reasons name recency, frequency, monetary |
| `test_score_customers_persists_segment_and_audit` | 0.711 → `dormant` persisted with scored_at + audit event |
| `test_score_customers_deterministic_across_replays` | 50 full re-scoring runs → identical scores/segments |

## 3. Segmentation

| Test | What it proves |
|---|---|
| `test_segment_boundaries` (9 parametrized) | exact boundary behavior: 0.249→active, 0.25→cooling, 0.499→cooling, 0.50→dormant, 0.749→dormant, 0.75→churned |

## 4. Suppression (absolute)

| Test | What it proves |
|---|---|
| `test_dnc_customer_gets_zero_touches` | DNC: nothing queued, nothing flushed, outbox empty |
| `test_recent_complaint_suppresses` | complaint at T suppresses at T+1d |
| `test_old_complaint_does_not_suppress` | complaint 200d old (beyond 180d lookback) does not suppress |
| `test_active_job_suppresses` | active job flag suppresses |
| `test_complaint_set_mid_sequence_blocks_flush` | **adversarial**: complaint after queueing, before flush → second run queues nothing, adapter never called (recording adapter), rows marked `suppressed`, zero sent/queued remain, audit event written |
| `test_dnc_set_mid_sequence_blocks_flush` | DNC set mid-sequence → flush suppresses rows, send log stays empty |
| `test_suppression_adversarial_no_leaks` | 300 customers × flag mixes (DNC / complaint / none) + mid-sequence active-job flips → DB-level assertion: no suppressed customer holds a queued or sent touch |

## 5. Sequence plans + outbox idempotency

| Test | What it proves |
|---|---|
| `test_sequence_plans_are_documented_per_segment` | cooling 2 / dormant 3 / churned 2 / active 0 steps; 1-based step indexes |
| `test_run_winback_queues_only_due_steps` | churned plan: step 1 at day 0, step 2 only after day 30 elapses |
| `test_run_winback_replay_is_idempotent` | 201 runs → 1 outbox row, 1 unique idempotency key |
| `test_touch_copy_is_rendered_and_labeled_demo` | customer name + service rendered; "nothing was sent" footer; synthetic recipient label |
| `test_touch_render_missing_variable_fails_closed` | missing `{{var}}` raises, never a half-filled message |
| `test_flush_writes_send_log_with_stub` | stub flush → `stub-logged` send-log row; second flush no-ops |

## 6. Report reconciliation

| Test | What it proves |
|---|---|
| `test_segment_report_reconciles_to_rows` | per-segment counts and mean dormancy match independent raw-SQL re-computation; totals tie out |
| `test_suppression_audit_lists_every_flagged_customer` | every flagged customer listed with the right reason; zero queued/sent touches among them |

## 7. Attribution (`tests/test_attribution.py`)

| Test | What it proves |
|---|---|
| `test_attribution_matches_hand_computed_fixture` | treated 1/3, control 1/3, lift 0.0, Wald CI ±0.7544, attributed_bookings 1 — all hand-computed; synthetic label present |
| `test_untraced_reactivation_booking_does_not_count` | reactivation-flagged booking with no prior sent touch does not count |
| `test_touch_after_booking_is_not_traced` | touch dated after the booking does not trace |
| `test_attribution_reconciles_to_source_rows` | group membership + control/treated counts match independent SQL |
| `test_attribution_with_empty_groups` | unknown run → None lift/CI, no crash |
| `test_holdout_split_is_deterministic` | same run_name → identical groups; re-split replaces, never duplicates |
| `test_holdout_split_approximate_ratio` | 20% holdout lands in a sane band on 200 customers |
| `test_holdout_split_validates_inputs` | bad pct / blank run_name rejected |

## 8. Web + API (`tests/test_reactivation_api.py`)

Pages render (overview, segments, outbox, attribution, suppression, hub
links); full demo flow through the API (create → job → score → segments →
win-back → outbox → flush → detail); suppression/complaint endpoints block
touches; holdout + attribution endpoints (incl. the synthetic label);
422 on missing attribution params; scoring-info endpoint; 404 on unknown
customer; HTML form POSTs redirect correctly.

## 9. Migration rollback (`tests/test_reactivation.py`)

`test_migration_005_down_step_rolls_back_for_real`: apply → use →
`rollback_migration("005_reactivation.sql")` → all six Q03 tables gone,
migration record removed, P01/P02/Q01/Q02 tables intact → `run_migrations`
re-applies cleanly.

## Coverage summary

56 tests: 37 reactivation (RFM/scoring/segments/suppression/sequences/
reports/rollback) + 8 attribution + 11 web/API. Full suite 430 passed,
zero regressions (see TEST_RESULTS.md).
