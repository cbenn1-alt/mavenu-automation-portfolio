# Q04 — Conversational Booking Agent: Requirements

**Status: Implemented** (all requirements below are implemented and tested;
see EVIDENCE_MATRIX.md).

## Functional requirements

1. **Greeting**: on conversation start the agent emits a greeting that
   (a) identifies itself as an *automated* booking assistant, (b) names the
   demo business, (c) states it will connect the caller with a person
   whenever unsure, and (d) asks for the service type.
2. **Slot-filling order**: service → location → preferred window →
   contact (name, then phone) → confirm. A single message may fill
   multiple slots opportunistically; the manager always advances to the
   earliest unfilled state.
3. **Deterministic policy**: v1 interpretation is rule-driven
   (keyword/regex) behind the replaceable `DialoguePolicy` protocol. No
   LLM integration is claimed or present.
4. **Confidence scoring**: every caller turn receives a confidence in
   [0, 1] per the documented heuristics table (see ARCHITECTURE.md);
   turn confidence = minimum over claimed slots.
5. **Below-threshold routing**: any turn with confidence < 0.55 hands off
   to a human with the full transcript and extracted slots. 100% routing
   is a measured criterion (TEST_RESULTS.md).
6. **Injection handling**: inputs matching the documented injection
   patterns hand off with reason `suspicious_input` and are never obeyed
   (no state change, no slot fill, no booking).
7. **Contradiction handling**: a confident new value for an already-filled
   slot that disagrees with the stored value hands off with reason
   `contradictory_input`; repeating the same value is not a contradiction.
8. **Max-turn cap**: at most 16 total turns per conversation; reaching the
   cap hands off with reason `max_turns`. The cap is enforced so the
   logged total can never exceed 16 (fuzz-verified).
9. **Availability from the adapter only**: the confirm prompt offers only
   slots returned by `BookingAdapter.get_availability`; the agent never
   invents times. Empty availability hands off (`booking_failed`).
10. **Booking confirmation gate**: a `booking_bookings` row is written
    only after `BookingAdapter.create_booking()` returns a reference.
    Adapter failure preserves the conversation and hands off
    (`booking_failed`); zero bookings without adapter confirmation.
11. **Confirm semantics**: "yes" books; "no" hands off (`slot_declined`);
    an unparseable answer hands off (`low_confidence`).
12. **Terminal states**: `booked` and `handoff` accept no further turns
    (409 Conflict on the API, ValueError in the service layer).
13. **Transcript completeness**: every agent and caller turn is logged
    with a gapless per-conversation index and a decision log
    (`state_before`, `state_after`, `action`, `confidence`, masked
    `extracted`, `reason`).
14. **Handoff queue**: escalation packages (reason + detail + masked
    transcript + masked slots) listed newest-first; claim/resolve
    workflow for the human operator.
15. **PII masking**: caller text and slot values masked before storage
    (phones, emails, minimized names); raw PII never persisted.
16. **Retention**: closed conversations lose transcript text and slot
    values after 90 days (`purge_old_conversations`); booking references
    and handoff metadata are retained.

## Non-functional requirements

- **Determinism**: identical inputs → identical decisions (policy is pure;
  adapter availability is a deterministic function of the window hint).
- **Zero cost**: Python 3.12 stdlib only at runtime; SQLite; no network calls.
- **Honest labeling**: scripted policy labeled as scripted everywhere
  (README, UI, code docstrings); "AI" in the title refers to the
  automation architecture, stated explicitly.
- **Auditability**: stdout JSON events for start/handoff/booking/purge;
  decision log per turn; migration with tested down-step.

## Out of scope (v1)

Real telephony, real scheduling-provider integration, multi-language
support, a trained model behind the policy seam, authenticated multi-user
access, scheduled execution (conversations are API-triggered).
