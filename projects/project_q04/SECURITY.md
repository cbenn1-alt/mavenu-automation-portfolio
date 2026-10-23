# Q04 — Conversational Booking Agent: Security

## Threat model

The agent accepts arbitrary caller text and persists it. It must never
store raw PII, never obey embedded instructions, never invent
availability, and never write a booking without adapter confirmation.
All data is synthetic in v1, but the controls are implemented as if it
were real.

## PII masking (implemented, tested)

Masking is applied **at write time**, before anything reaches SQLite
(`dialogue.mask_text`, `dialogue.mask_slot_value`):

| Data | Stored as |
|---|---|
| Phone runs in caller text | `***-***-0142` (last 4 digits only) |
| Email addresses in caller text | `d***@example.com` |
| `contact_phone` slot | `***-***-0142` |
| `contact_name` slot | minimized: `Dana Rivera` → `Dana R.` |
| Service / location / window slots | as-is (non-PII) |

Raw PII never reaches the database: caller turns are masked in
`_log_turn`, slots in `_store_slots`, and the handoff escalation package
is built from already-masked rows. Contradiction checks compare
masked-to-masked so raw values never enter the comparison path beyond a
transient local variable.

Tests: `test_mask_phone_digits`, `test_mask_text_redacts_phone_and_email`,
`test_caller_turns_and_slots_stored_masked`.

## Injection-style input handling (implemented, tested)

A documented regex denylist (`dialogue.INJECTION_PATTERNS`) is checked
**before** any slot extraction. Matches route to handoff with reason
`suspicious_input`; the input is never acted on — no state change, no
slot fill, no booking. Tested with 7 parametrized injection strings plus
injection attempts inside the 2,000-conversation fuzz run. The list is a
deterministic denylist for a scripted agent, not an LLM guardrail claim.

## Availability hallucination (prevented by construction)

The confirm prompt is built only from `BookingAdapter.get_availability()`
return strings (`DialogueManager.confirm_prompt`). There is no code path
that formats a time from the caller's window hint. Empty availability
hands off (`booking_failed`) rather than guessing. Tested with a marker
adapter (`test_availability_comes_only_from_adapter`).

## Booking integrity

`booking_bookings` rows are inserted only after
`create_booking()` returns a reference; adapter exceptions are caught,
the conversation is preserved, and the flow hands off
(`booking_failed`). Tested with outage doubles and a mixed-run
reconciliation test. The `conversation_id` UNIQUE constraint makes
double-booking one conversation structurally impossible.

## Retention policy (implemented)

Closed conversations (`booked`/`handoff`) older than 90 days lose
transcript text and slot values via `purge_old_conversations`
(booking references and handoff metadata survive for accounting).
Run it on a schedule in real deployments; in this demo it is
API-triggerable service code, tested in
`test_purge_old_conversations` / `test_purge_keeps_recent_conversations`.

## Input validation & injection (SQL/XSS)

- All SQL is parameterized; schema changes go through the migration
  runner with a tested down-step.
- API bodies are JSON-parsed with type checks; empty turn text → 422;
  unknown conversation → 404; turns on terminal conversations → 409.
- The chat demo page inserts caller/agent text via `textContent`, never
  `innerHTML`.
- WSGI error handling never leaks internals (generic 500 envelope).

## What is NOT in place (real-deployment requirements)

- No authentication/authorization on the API (demo).
- No rate limiting on conversation starts (demo).
- No telephony or scheduling-provider integration — the adapter is a
  demo; a real deployment needs credential management via environment
  (never code), TLS, and provider-side audit.
- No legal review of data-retention or consent for real caller data;
  get counsel before handling real PII. This document describes the
  demo's controls, not a compliance opinion.
- No secrets exist in this project; none are needed.
