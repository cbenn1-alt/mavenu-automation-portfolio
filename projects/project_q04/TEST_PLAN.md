# Q04 — Conversational Booking Agent: Test Plan

Environment: Python 3.12.3, pytest 9.1.1, Linux, stdlib only at runtime.
Run: `cd ~/workspace/mavenu-portfolio && .venv/bin/pytest tests/ -q`.

## 1. Policy unit tests (`tests/test_booking_agent.py`)

- Service keyword extraction (7 parametrized: hvac/furnace, plumbing/leak,
  electrical/breaker, roofing/shingles, landscaping/lawn) → 1.0; longest
  match wins ("water heater" → plumbing, not hvac).
- No-match input → confidence 0.0.
- Location ZIP, window variants incl. the full confidence table
  (ISO 1.0 / today-tomorrow 0.9 / day+part 0.9 / day-or-part 0.8 /
  next-week 0.8), phone 10-digit 0.95 / 7-digit 0.7, name 0.85,
  yes/no 1.0.
- Turn confidence = min over claimed slots.
- Injection patterns (7 parametrized) → `injection=True`, confidence 0.0,
  nothing extracted.
- Determinism: same input twice → identical decision.
- Threshold/cap constants pinned (0.55 / 16).

## 2. Dialogue-path tests (every state + every handoff trigger)

- `start()` identifies as automated; transition greeting→service.
- Happy path `hvac → 58102 → tuesday morning → Dana Rivera → 7015550142 → yes`
  walks service→location→window→contact→contact→confirm→booked; booking
  ref `QB-…`; slots persisted.
- Opportunistic filling (`hvac 58102`) skips the location state.
- Every transition logged: decision chain contiguous from `greeting` to
  terminal; `turn_index` gapless.
- Handoff triggers, each asserted with reason + queue row:
  low_confidence, suspicious_input (4 parametrized, zero slots filled,
  zero bookings), contradictory_input, same-value repeat is NOT a
  contradiction, slot_declined, unclear confirm answer, max_turns (via a
  stalling test-double policy + direct boundary test at `MAX_TURNS-3`),
  booking_failed (no adapter availability / create raises).
- Terminal states reject further turns (ValueError → API 409).

## 3. Booking-adapter contract tests

- Availability comes only from the adapter: a marker adapter's
  distinctive slot strings appear verbatim in the confirm prompt.
- No booking row when `create_booking` raises (outage-at-confirm double)
  → handoff `booking_failed`, conversation preserved.
- No booking row when availability is empty (`fail=True`).
- Zero-phantom-bookings: mixed booked/handed-off/failed conversations →
  `booking_bookings` rows == adapter-confirmed bookings, each matching a
  `booked` conversation's ref.
- Adapter determinism: same hint → same slots; ref format `QB-…`.

## 4. Confidence-threshold routing (measurable criterion)

- 15 low-confidence inputs × service state → 100% handoff,
  reason `low_confidence`.
- 14 low-confidence inputs × later (window) state → 100% handoff,
  reason `low_confidence`.
- Zip-shaped input at the window state → handoff as `contradictory_input`
  (still a handoff; documented as not-a-low-confidence-turn).

## 5. Adversarial tests

- Gibberish, empty-ish inputs, injection strings, contradictory slots →
  handoff, never obeyed, never booked.
- 2,000 seeded fuzz conversations (token pool mixes valid slots,
  gibberish, injections, long strings, emails): no exception escapes,
  every conversation ends in `booked`/`handoff`, `turn_count ≤ 16`,
  bookings == booked conversations, handoff reasons within the closed set.

## 6. Transcript completeness audit

- After happy-path, handoff, declined, and alternate-script conversations:
  gapless indices, every turn has non-empty text + timestamp, roles
  alternate starting with agent.

## 7. PII masking tests

- `mask_phone_digits`, `mask_text` (phone runs + emails) unit tests.
- Caller turns and slot values stored masked (no raw digits in stored
  text; phone slot `***-***-0142`; name minimized `Dana R.`).

## 8. Handoff queue workflow

- Queue lists escalation packages (reason, masked transcript, slots);
  claim → resolved transitions; bad status → ValueError; unknown id →
  KeyError.

## 9. Retention

- `purge_old_conversations`: 100-day-old closed conversation loses turns
  text + slot values (`[purged]`), keeps state/booking ref; recent
  conversations untouched.

## 10. Migration rollback (for real)

- `rollback_migration(conn, "006_booking_agent.sql")` drops all 5 tables
  and removes the migration record; `run_migrations` re-applies cleanly.

## 11. API tests (`tests/test_booking_agent_api.py`)

- Start → 201 with automated greeting; full chat to booking; validation
  (422 empty text, 404 unknown, 409 terminal); transcript GET incl. 404;
  handoff queue + claim/resolve + 422/404; bookings list; all four pages
  render (chat, handoffs, bookings, hub card) with the synthetic banner.

## Measurable criteria → tests

| Criterion (spec) | Test |
|---|---|
| 100% of low-confidence turns route to handoff | §4 (30 parametrized cases) |
| Zero bookings without adapter confirmation | §3 (outage doubles, mixed-run reconciliation) |
| Max-turn cap never exceeded in fuzzed conversations | §5 (2,000 seeded conversations, `turn_count ≤ 16`) |
| Availability only from the adapter | §3 marker-adapter test |
| Every transition logged | §2 chain-contiguity test |
| Rollback tested for real | §10 |
