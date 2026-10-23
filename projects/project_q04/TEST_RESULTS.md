# Q04 — Conversational Booking Agent: Test Results

**Run date:** 2026-10-23 (20:01 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/pytest tests/`

## Result

**532 passed, 0 failed in 7.22s** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| Q04 new (`tests/test_booking_agent.py`) | 94 | 94 passed (2.58s for both Q04 files) |
| Q04 new (`tests/test_booking_agent_api.py`) | 8 | 8 passed |
| P01 (51) + P02 (101) + Q01 (89) + Q02 (133) + Q03 (56) | 430 | 430 passed, unchanged |

## Measurable criteria — verified

- **100% of low-confidence turns route to handoff:** 15 inputs × service
  state + 14 inputs × window state = 29 parametrized cases, all handoff
  with reason `low_confidence`
  (`test_below_threshold_turns_always_handoff_service_state`,
  `test_below_threshold_turns_always_handoff_later_states`).
- **Zero bookings without adapter confirmation:** outage-at-confirm double
  and empty-availability double both yield handoff `booking_failed` with
  no `booking_bookings` row; mixed-run reconciliation test asserts
  bookings == booked conversations
  (`test_no_booking_written_when_adapter_create_fails`,
  `test_no_availability_from_adapter_hands_off_without_booking`,
  `test_zero_bookings_without_adapter_confirmation`).
- **Max-turn cap never exceeded:** 2,000 seeded fuzz conversations
  (`random.Random(20261023)`), every one ends in `booked`/`handoff` with
  `turn_count ≤ 16`; no exception escapes `send_turn`
  (`test_fuzz_conversations_never_exceed_turn_cap_and_stay_consistent`).
  Direct boundary test pins the trigger at `MAX_TURNS - 3`.
- **Availability only from the adapter:** marker-adapter test asserts the
  confirm prompt embeds the adapter's slot id/when verbatim
  (`test_availability_comes_only_from_adapter`); `confirm_prompt` takes
  only adapter strings — no code path formats times from the window hint.
- **Every transition logged:** decision-chain contiguity asserted from
  `greeting` to terminal across four conversation shapes; gapless
  `turn_index` (`test_every_transition_logged_and_chain_contiguous`,
  `test_transcript_completeness_audit`).
- **Adversarial inputs:** 7 injection patterns + gibberish +
  contradictory slots → handoff, never obeyed, never booked; injection
  check runs before slot extraction.
- **PII masking:** stored caller text contains no raw phone digits or
  emails; slots masked (`***-***-0142`, `Dana R.`)
  (`test_caller_turns_and_slots_stored_masked`, masking unit tests).
- **Migration rollback (real):** `test_migration_006_down_step_rolls_back_for_real`
  — `rollback_migration(conn, "006_booking_agent.sql")` drops all 5
  tables and removes the migration record; `run_migrations` re-applies
  `006_booking_agent.sql` cleanly. Run 2026-10-23 in this same
  environment.
- **Policy replaceability:** stalling test-double policy drives the
  max-turns path; custom policies plug into `start_conversation` /
  `send_turn` via the `DialoguePolicy` protocol.

## Notes

- The fuzz seed (`20261023`) makes the 2,000-conversation run
  reproducible.
- No test was pre-filled; every count above comes from the run recorded
  here. Re-run any time with the command above.
