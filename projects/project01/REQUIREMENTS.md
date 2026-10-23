# Project 01 — Requirements

Source: portfolio execution specification, Section 8. Each requirement maps to
acceptance criteria verified by the automated test suite.

## Functional requirements

1. **Public lead intake** — an HTML form and a JSON API accept lead
   submissions (name, phone and/or email, service, ZIP, urgency, notes).
2. **Server-side validation** — every field is validated on the server;
   invalid submissions are rejected with per-field errors (HTTP 422).
3. **Duplicate-submission protection** — a client-supplied idempotency key
   makes retries safe: the original response is replayed, no second record.
4. **Rule-based qualification** — service must be supported, contact channel
   present, ZIP well-formed; out-of-area ZIPS route to human review.
5. **AI-assisted classification behind a replaceable interface** — a
   `LeadClassifier` protocol; the bundled implementation is a deterministic
   demonstration, clearly labeled. Confidence below threshold → human review.
6. **Human-review routing** — `needs_review` state with reviewer UI and API
   to approve (`qualified`/`routed`) or `rejected`, all actor-stamped.
7. **Lead lifecycle & status history** — states
   `received, qualified, routed, booked, needs_review, rejected, cancelled`;
   permitted transitions defined once, in code; every change audited.
8. **Appointment tracking** — booking integration creates a booking reference
   on the lead; failures are recorded as incidents, lead preserved in review.
9. **Persistent SQL storage** — SQLite with versioned migrations; schema in
   `src/mavenu/migrations/001_core.sql`.
10. **Operational dashboard** — counts by state plus recent leads; totals
    computed from the DB.
11. **Structured logs & exception handling** — JSON log lines; safe error
    envelopes; no stack traces to clients.

## Acceptance criteria (spec §8) → test evidence

| Criterion | Verified by |
|---|---|
| Valid submissions create one lead record | `test_valid_submission_creates_one_booked_lead`, `test_api_create_lead_201` |
| Invalid submissions are rejected / flagged | `test_invalid_submission_rejected_with_no_record`, `test_api_invalid_payload_422_with_field_errors`, `test_form_invalid_rerenders_with_errors` |
| Duplicates do not create duplicate records | `test_idempotent_retry_returns_original_without_duplicate`, `test_api_idempotency_key_replays` |
| Uncertain AI outputs enter review | `test_low_confidence_lead_goes_to_needs_review` (+ classifier unit tests) |
| Failed integrations do not silently lose leads | `test_booking_failure_preserves_lead_in_review` |
| Retries do not duplicate business effect | idempotency tests above |
| Dashboard totals reconcile with DB records | `test_stats_reconcile_with_database`, `test_api_stats_reconcile_with_database` |

## Non-functional requirements

- Zero runtime dependencies beyond Python 3.12 stdlib; zero operating cost.
- All demo data synthetic; no PII anywhere.
- Reviewer can run the suite and the app with two commands (see DEMO.md).
