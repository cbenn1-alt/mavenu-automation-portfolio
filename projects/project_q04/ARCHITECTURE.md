# Q04 — Conversational Booking Agent: Architecture

## Component map

```
caller text
    │
    ▼
POST /api/booking-agent/conversations/:id/turns   (web.py)
    │
    ▼
booking_agent.send_turn()                         (booking_agent.py)
    │  1. log caller turn (MASKED)
    │  2. load filled slots (masked)
    │  3. DialogueManager.step()
    │        ├─ DialoguePolicy.interpret()  ← replaceable seam
    │        ├─ injection → handoff
    │        ├─ contradiction → handoff
    │        ├─ confidence < 0.55 → handoff
    │        ├─ turn cap → handoff
    │        └─ advance to earliest unfilled state
    │  4. persist new slots (MASKED)
    │  5a. action=book  → BookingAdapter.create_booking()
    │        └─ success: write booking_bookings row, state=booked
    │        └─ failure: handoff booking_failed (conversation preserved)
    │  5b. entering confirm → BookingAdapter.get_availability()
    │        └─ prompt embeds ONLY adapter strings; empty → handoff
    │  5c. handoff → write escalation package, state=handoff
    │  6. log agent turn + decision JSON, commit
    ▼
SQLite: booking_conversations / booking_turns / booking_slots /
        booking_handoffs / booking_bookings   (006_booking_agent.sql)
```

## State machine

```
greeting ──start()──▶ service ──▶ location ──▶ window ──▶ contact ──▶ confirm
                                                                          │
                                                              ┌─────────────┼──────────────┐
                                                              ▼             ▼              ▼
                                                           booked        handoff        handoff
                                                         (adapter OK)  (no/unclear/   (no availability)
                                                                        low-conf)
Any non-terminal state ──▶ handoff on: low confidence · max turns ·
suspicious input · contradictory input · booking failure.
Terminal states (booked, handoff) accept no further turns.
```

Every transition is recorded in the turn's `decision_json`
(`state_before`, `state_after`, `action`, `confidence`, masked
`extracted`, `reason`); the chain is asserted contiguous in tests.

## The policy seam

`DialoguePolicy` (in `dialogue.py`) is a Protocol with one method:

```python
def interpret(self, text: str, state: str, filled: dict[str, str]) -> PolicyDecision
```

`ScriptedDemoPolicy` (v1) implements it with deterministic
keyword/regex rules. A future model could implement the same protocol —
but it would still be bound by the *manager's* rails: the confidence
threshold, the turn cap, the injection/contradiction checks, and the
adapter-only availability rule. The seam is where intelligence can be
upgraded without redesigning safety.

### Documented confidence heuristics (the policy's contract)

| Slot | Signal | Confidence |
|---|---|---|
| service | whole-word service keyword/synonym (longest match wins) | 1.0 |
| location | 5-digit ZIP | 1.0 |
| window | ISO date `YYYY-MM-DD` | 1.0 |
| window | "today" / "tomorrow" | 0.9 |
| window | day-name + day-part ("tuesday morning") | 0.9 |
| window | day-name only, day-part only, or "next week" | 0.8 |
| contact_name | letters-only, ≥2 chars, ≤4 words, not a command word | 0.85 |
| contact_phone | 10 digits (or 11 starting with 1) | 0.95 |
| contact_phone | 7–9 digits | 0.7 |
| answer (confirm) | yes-word / no-word | 1.0 |
| any | no recognizable signal for the current state | 0.0 |

Turn confidence = minimum over the slots claimed on that turn.
`CONFIDENCE_THRESHOLD = 0.55`. Injection patterns force 0.0.

The CONTACT state is special: a name-only or phone-only answer "lands"
(the missing half is asked next); every other state requires its own slot.

### Injection denylist (`INJECTION_PATTERNS`)

Documented regexes: "ignore (all|any|the|your) previous instructions",
"disregard … instructions", "you are now ", "pretend (you are|to be)",
"act as a human/person/real", "system prompt", "jailbreak",
"forget/override (your|the) instructions", "book .* without asking",
"skip (the|all) questions". Matched input is never obeyed — it routes to
handoff with reason `suspicious_input` before any slot logic runs.

## Booking adapter seam

`BookingAdapter` protocol (`booking_agent.py`): `get_availability(window_hint)`
→ list of `{"slot_id", "when"}`; `create_booking(payload)` → reference.
`DemoBookingAdapter` is deterministic (availability rotates by hint hash;
references are `QB-<conv>-001`) and supports `fail=True` to simulate an
outage. The demo writes bookings to SQLite — the same interface pattern
as P01's `BookingAdapter`/`FakeBookingAdapter`, so a real provider plugs
in without touching the dialogue manager.

Anti-hallucination rule: `DialogueManager.confirm_prompt(slot_when,
slot_ref)` only interpolates adapter-returned strings. There is no code
path that formats a time from the window hint.

## Data model (006_booking_agent.sql)

- `booking_conversations` — `public_id` (`CONV-000001`), `state` (CHECK
  over the 8 states), `turn_count`, `handoff_reason`, `booking_ref`
- `booking_turns` — gapless `turn_index` per conversation (UNIQUE),
  `role`, masked `text`, `confidence`, `decision_json`
- `booking_slots` — one row per slot, `value_masked`, `confidence`
  (UNIQUE per conversation+slot; upsert on re-fill)
- `booking_handoffs` — `reason` (closed CHECK set), `reason_detail`,
  masked `transcript_json` + `slots_json`, `status`
  (open/claimed/resolved)
- `booking_bookings` — written only post-adapter-confirmation; UNIQUE
  `conversation_id` and `booking_ref`

## Masking (write-time, in `dialogue.py`)

- `mask_text`: phone runs (`\d[\d \-\.\(\)]{6,}\d`) → `***-***-0142`;
  emails → `d***@example.com`
- `mask_slot_value`: phones → last-4; names → first name + initials
  (`Dana Rivera` → `Dana R.`); other slots stored as-is (non-PII)
- Contradiction checks compare masked-to-masked, so raw PII never enters
  the comparison path beyond a transient local

## Retention

`purge_old_conversations(conn, now, retention_days=90)`: for
conversations in terminal states older than the window, deletes
`booking_turns` rows and replaces slot values with `[purged]`; booking
references and handoff metadata survive.

## Web surface (web.py)

- `GET /project_q04` — chat demo page (JS drives the API; user text set
  via `textContent`, never `innerHTML`)
- `GET /project_q04/handoffs`, `GET /project_q04/bookings`
- `POST /api/booking-agent/conversations` → 201 `{public_id, state, agent_message}`
- `POST /api/booking-agent/conversations/<id>/turns` → 200 turn result
  (404 unknown, 409 terminal, 422 empty text)
- `GET /api/booking-agent/conversations/<id>` → transcript + slots
- `GET /api/booking-agent/handoffs`, `POST /api/booking-agent/handoffs/<id>`
  (claim/resolve), `GET /api/booking-agent/bookings`

## Rationale

A scripted agent with honest labeling and a real handoff path is more
credible than a fake "AI chatbot": every behavior is deterministic and
testable, the failure modes (low confidence, injection, contradiction,
outage) all degrade to a human with a full transcript, and the
`DialoguePolicy` seam lets a real model be introduced later without
redesigning the safety rails.
