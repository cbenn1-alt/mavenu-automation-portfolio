# Q04 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| Finite-state dialogue manager, 8 states, every transition logged | Implemented, Tested | `dialogue.DialogueManager`; `test_every_transition_logged_and_chain_contiguous` (decision chain contiguous greeting→terminal); `test_transcript_completeness_audit` |
| Deterministic rule-driven slot-filling behind replaceable `DialoguePolicy` protocol | Implemented, Tested | `dialogue.DialoguePolicy`, `ScriptedDemoPolicy`; `test_policy_deterministic`; stalling test-double policy drives the max-turns path (replaceability proven) |
| Per-turn confidence scoring, documented threshold 0.55 | Implemented, Tested | Confidence table in `dialogue.py` + ARCHITECTURE.md; `test_confidence_threshold_and_turn_cap_documented`; `test_turn_confidence_is_min_over_claimed_slots`; window/phone/name table tests |
| 100% of below-threshold turns route to handoff | Tested | 29 parametrized cases (`test_below_threshold_turns_always_handoff_service_state`, `..._later_states`) — all handoff, reason `low_confidence` |
| Injection-pattern denylist, never obeyed | Implemented, Tested | `dialogue.INJECTION_PATTERNS`; 7 parametrized patterns + fuzz coverage; `test_injection_input_hands_off_and_fills_nothing` (zero slots, zero bookings) |
| Contradiction detection (masked comparison) | Implemented, Tested | `test_contradictory_slot_hands_off`; `test_repeating_same_value_is_not_contradiction`; `test_zip_shaped_input_at_window_state_hands_off_as_contradiction` |
| Max-turn cap 16, never exceeded in fuzzed conversations | Implemented, Tested | `test_fuzz_conversations_never_exceed_turn_cap_and_stay_consistent` (2,000 seeded conversations, `turn_count ≤ 16`); `test_max_turn_cap_hands_off_and_is_never_exceeded`; boundary test at `MAX_TURNS - 3` |
| Booking behind `BookingAdapter` protocol; availability only from adapter | Implemented, Tested | `booking_agent.BookingAdapter`, `DemoBookingAdapter`; `test_availability_comes_only_from_adapter` (marker strings verbatim in prompt) |
| Zero bookings without adapter confirmation | Tested | `test_no_booking_written_when_adapter_create_fails`; `test_no_availability_from_adapter_hands_off_without_booking`; `test_zero_bookings_without_adapter_confirmation` (mixed-run reconciliation) |
| Handoff escalation packages to human queue (claim/resolve) | Implemented, Tested | `booking_agent._escalate`, `handoff_queue`, `set_handoff_status`; `test_handoff_status_transitions`; API tests; `/project_q04/handoffs` page |
| Caller PII masked at write time | Implemented, Tested | `dialogue.mask_text`, `mask_slot_value`; `test_mask_phone_digits`, `test_mask_text_redacts_phone_and_email`, `test_caller_turns_and_slots_stored_masked` |
| 90-day transcript retention purge | Implemented, Tested | `booking_agent.purge_old_conversations`; `test_purge_old_conversations`, `test_purge_keeps_recent_conversations` |
| Migration rollback tested for real | Implemented, Tested | `006_booking_agent.down.sql`; `test_migration_006_down_step_rolls_back_for_real` (run 2026-10-23) |
| Chat demo page + JSON API | Implemented, Tested | `web.py` `/project_q04*` + `/api/booking-agent/*`; 8 API tests; page-render tests incl. synthetic banner |
| Scripted policy, NOT a language model; "AI" = automation architecture | Simulated (labeled) | README honest-status banner; greeting self-identifies as automated; `ScriptedDemoPolicy` docstring; DEMO.md |
| Demo booking adapter (invented slots, SQLite) — no real scheduling integration | Simulated (labeled) | README banner; `DemoBookingAdapter` docstring; bookings page copy |
| All conversations/contacts/bookings synthetic | Demo | Fictional fixtures; SYNTHETIC DEMO DATA banner in `web.py`; masking tests use synthetic numbers |
| No production deployment / no real users / no real bookings | — (not claimed) | Honest-status banner; no such claim anywhere |
| P01/P02/Q01/Q02/Q03 regression-free | Tested | Full suite `532 passed` 2026-10-23 (TEST_RESULTS.md) |

## Claim-grade summary

- **Verified on the custom stack:** FSM with logged transitions,
  deterministic policy + documented confidence table, 100%
  below-threshold handoff routing, injection denylist, contradiction
  detection, turn cap (2,000 fuzz conversations, never exceeded),
  adapter-only availability, zero phantom bookings, handoff queue
  workflow, write-time PII masking, retention purge, migration rollback,
  full API + chat demo.
- **Simulated, labeled:** the "intelligence" (scripted rules, not a model);
  booking-provider integration (demo adapter).
- **Synthetic, labeled:** all conversations, contacts, and bookings.
- **Not demonstrated:** real telephony, real scheduling providers,
  model-backed policy, authentication, rate limiting, legal review of
  retention/consent for real caller data.
