# Project 01 — AI Revenue Operations Engine

**Status: implemented + tested (Gate A ✓)** — 51 automated tests, all passing.

## Business problem

Home-service companies lose revenue to slow or missed lead handling: web
inquiries sit unanswered, unqualified leads waste estimator time, and nobody
can say where any given lead stands. This project is a working lead-processing
engine: a public intake captures inquiries, the server validates them,
rule-based qualification plus a classifier decides whether a lead can be
auto-routed or needs a human, a booking integration creates the appointment,
and every step lands in an audit trail a manager can inspect.

## Implemented capabilities

- Public lead-intake form (HTML) and JSON API (`POST /api/leads`)
- Server-side validation (never trusts the client): name, phone/email,
  service, ZIP, urgency, notes length
- Duplicate-submission protection via client `Idempotency-Key`
  (header or hidden form field); replays return the original response —
  retries never create duplicate business records
- Informational possible-duplicate flagging (same contact + service < 24h)
- Rule-based qualification + classifier routing behind a replaceable
  `LeadClassifier` interface; uncertain output → human review
- Out-of-service-area leads → human review even when the classifier is confident
- Booking integration behind a `BookingAdapter` interface; failures route the
  lead to review with the incident recorded — leads are never silently lost
- Lead lifecycle states in code: `received → qualified → routed → booked`,
  with `needs_review`, `rejected`, `cancelled`; illegal transitions raise
- Reviewer UI + API for manual transitions (actor + timestamp recorded)
- Operations dashboard whose totals are computed from the database
  (test asserts reconciliation)
- Structured audit log: every state change is a DB row and a JSON stdout line

## What is simulated (labeled, not hidden)

- **Classifier**: `DeterministicDemoClassifier` — transparent rules, not a
  trained model. The `LeadClassifier` protocol is the swap-in point.
- **Booking**: `FakeBookingAdapter` — deterministic in-process stand-in.
  Its failure mode (`fail=True`) is exercised by tests.

## Technology stack

Python 3.12 stdlib (`wsgiref`, `sqlite3`), pytest (dev only).
Zero runtime dependencies, zero cost.

## Repository map

- Service logic: `src/mavenu/leads.py`
- Classifier: `src/mavenu/classifier.py`
- Web/API: `src/mavenu/web.py`
- Foundation: `src/mavenu/{config,db,events,validation,workflow}.py`
- Tests: `tests/test_{workflow,validation,classifier,leads,web}.py`

## Docs in this folder

- `REQUIREMENTS.md` — what was required
- `ARCHITECTURE.md` — how it is built
- `TEST_PLAN.md` — what the tests cover
- `TEST_RESULTS.md` — actual results from real runs
- `SECURITY.md` — threat model and controls
- `RUNBOOK.md` — operating the demo
- `DEMO.md` — guided demonstration script for a reviewer

## Known limitations

- Single-process demo server (`wsgiref`); not for production traffic.
- SQLite single-file database; no multi-user concurrency story.
- No authentication on reviewer actions (demo scope; see SECURITY.md).
- Classifier is rules, not ML; booking is a fake adapter.
- No email/SMS notifications; no real calendar integration.
