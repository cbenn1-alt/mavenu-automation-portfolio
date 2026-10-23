# Q04 — Conversational Booking Agent

**Status: Implemented · Tested** — 102 automated tests, all passing
(532/532 full suite: P01's 51 + P02's 101 + Q01's 89 + Q02's 133 + Q03's 56
+ Q04's 102; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Finite-state dialogue manager (`greeting → service → location → window → contact → confirm → booked | handoff`) with every transition logged to a per-turn decision log; deterministic rule-driven slot-filling behind a replaceable `DialoguePolicy` protocol (`ScriptedDemoPolicy` v1); per-turn confidence scoring with a documented threshold (0.55) — 100% of below-threshold turns route to handoff (tested across 30 parametrized low-confidence inputs); injection-pattern denylist (never obeyed — tested); contradiction detection against stored slots (masked comparison); max-turn cap (16) with headroom so the logged total can never exceed it (fuzz-tested over 2,000 seeded random conversations); booking behind the `BookingAdapter` protocol — availability comes ONLY from the adapter and a booking row is written ONLY after adapter confirmation (zero phantom bookings, tested incl. adapter-failure paths); handoff escalation packages (masked transcript + masked slots + reason) to a human queue with claim/resolve workflow; caller PII masked at write time (phone/email in transcripts, minimized names, masked slot values); 90-day transcript retention purge; migration rollback tested for real |
| What is SIMULATED | **Simulated** | The "intelligence" is a **scripted slot-filler, not a language model**. The word "AI" in the project title refers to the automation architecture (state machine + replaceable policy seam), stated explicitly here. The agent identifies itself as automated in its first message and never presents as human. The `DialoguePolicy` protocol is the seam where a real model could plug in later — it would still be bound by the manager's confidence threshold, turn cap, and terminal-state rules. The booking adapter is a deterministic demo (invented availability slots, SQLite-backed bookings) — no real scheduling system is integrated |
| What is SYNTHETIC | **Synthetic** | Every conversation, caller utterance, contact detail, and booking is invented ("Dana Rivera", "7015550142" is a fictional 555-style number, "Demo Home Services"). No real callers, no real appointments |
| What is NOT claimed | — | No production deployment. No real users, no real bookings, no telephony or scheduling-provider integration. No LLM integration in v1. No platform or employer endorsement |

## Business problem

After-hours inquiries go to voicemail or sit in inboxes until morning. A
structured conversational intake can capture the job details (service,
location, preferred window, contact) and offer a booking slot — with a
clean handoff to a human whenever confidence is low.

## Implemented capabilities

- **Dialogue manager** (`src/mavenu/dialogue.py`): finite-state machine
  over 8 states; `start()` emits the greeting (self-identifies as
  automated); `step()` processes one caller turn — injection check →
  contradiction check → confidence check → slot merge → advance to the
  earliest unfilled state; every transition returned with
  `(state_before, state_after)` and persisted in the turn's decision log
- **Dialogue policy** (`DialoguePolicy` protocol + `ScriptedDemoPolicy`):
  deterministic keyword/regex extraction with a documented confidence
  table (service 1.0, ZIP 1.0, ISO date 1.0, today/tomorrow 0.9, day+part
  0.9, day-or-part 0.8, name 0.85, 10-digit phone 0.95, 7–9-digit phone
  0.7, yes/no 1.0, no signal 0.0); turn confidence = minimum over claimed
  slots; longest-keyword-first service matching ("water heater" beats
  "heater"); opportunistic multi-slot filling from a single message
- **Safety rails**: `CONFIDENCE_THRESHOLD = 0.55` (below → handoff);
  `MAX_TURNS = 16` enforced before processing with 3 turns of headroom
  (full happy path = 13 turns; the 7th caller turn hands off at the
  latest); injection denylist (`INJECTION_PATTERNS`, documented);
  contradiction detection compares masked values so raw PII never enters
  the comparison path
- **Booking adapter** (`src/mavenu/booking_agent.py`): `BookingAdapter`
  protocol (`get_availability` + `create_booking`) following P01's seam
  pattern; `DemoBookingAdapter` returns deterministic invented slots and
  writes bookings to SQLite; `fail=True` simulates an outage. The confirm
  prompt embeds ONLY adapter-returned strings — the agent never invents
  times. `booking_bookings` rows are inserted only after
  `create_booking()` returns a reference
- **Handoff escalation**: closed reason set
  (`low_confidence`, `max_turns`, `suspicious_input`,
  `contradictory_input`, `slot_declined`, `booking_failed`); package =
  masked transcript snapshot + masked slots + reason + detail; human queue
  with open/claimed/resolved workflow (`GET /project_q04/handoffs`,
  `POST /api/booking-agent/handoffs/<id>`)
- **Transcript & audit**: every agent AND caller turn logged with gapless
  `turn_index` and a decision JSON (`state_before`, `state_after`,
  `action`, `confidence`, masked `extracted`, `reason`); stdout JSON
  events on start/handoff/booking/purge
- **PII masking at write time**: phone runs → `***-***-0142`, emails →
  `d***@example.com`, names minimized to `Dana R.`; raw digits never
  stored; 90-day retention purge for closed conversations
  (`purge_old_conversations`)
- **Web UI**: chat-style demo page driving the JSON API
  (`/project_q04`), handoff queue and bookings pages, full REST surface
  under `/api/booking-agent/*`

## Case-study narrative

Nights and weekends were a black hole for new inquiries. We built a
booking agent that asks the right questions in order, books when it's
sure, and hands a clean transcript to a human when it isn't. It never
pretends to be a person — and that's why the owner trusts it.

## Repository layout

- `src/mavenu/dialogue.py` — states, `DialoguePolicy` protocol,
  `ScriptedDemoPolicy`, `DialogueManager`, masking helpers
- `src/mavenu/booking_agent.py` — conversation lifecycle, `BookingAdapter`
  protocol, `DemoBookingAdapter`, handoff escalation, retention purge
- `src/mavenu/migrations/006_booking_agent.sql` (+ `.down.sql`) —
  conversations, turns, slots, handoffs, bookings
- `src/mavenu/web.py` — `/project_q04*` pages, `/api/booking-agent/*`
- `tests/test_booking_agent.py` (94), `tests/test_booking_agent_api.py` (8)
