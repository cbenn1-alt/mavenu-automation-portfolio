# Project 01 — Guided Demo (5 minutes)

For a hiring manager or reviewer. Everything below runs locally; nothing
leaves the machine.

## 0. Setup (1 min)

```bash
cd mavenu-portfolio
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q     # expect: 51 passed
python3 run.py                            # open http://localhost:8080/
```

## 1. The happy path (1 min)

1. Open **Project 01** (`/project01`).
2. Submit: name `Dana Rivera`, phone `7015550142`, email
   `dana@example.com`, service `hvac`, ZIP `58102`, urgency `priority`,
   notes `Furnace stopped blowing hot air.`
3. You land on the lead page: state **booked**, with a booking reference.
4. Scroll to **Audit timeline**: `received → qualified → routed → booked`,
   each with actor and timestamp.

## 2. The review path (1 min)

1. Submit a thin lead: name `Sam Chen`, email only
   `sam@example.com`, service `landscaping`, ZIP `58103`, no notes.
2. State: **needs_review** — the classifier's confidence was below
   threshold, so it asked a human instead of guessing.
3. As the reviewer, transition it to `qualified` with your name.
   The timeline records your action.

## 3. The failure path (1 min)

1. Submit a duplicate of the first lead (same phone/email/service).
   Note the `possible_duplicate_of` link — flagged, not blocked, not duplicated.
2. Run the outage drill:
   `.venv/bin/python -m pytest tests/test_leads.py::test_booking_failure_preserves_lead_in_review -q`
   The booking integration "fails"; the lead is preserved in review with
   the incident in its audit trail. Nothing is silently lost.

## 4. The dashboard (30 sec)

Open `/project01/dashboard`: counts by state are computed live from the
database — the suite asserts they always reconcile.

## 5. What to say about it

- "Working lead-processing engine: intake, server-side validation,
  idempotent submission, rule-based qualification, classifier routing with
  human review on uncertainty, booking integration with failure handling,
  full audit trail, reconciled dashboard."
- "51 automated tests, all passing. Python stdlib + SQLite, zero cost."
- Honest limits: "The classifier is deterministic rules behind a
  model-ready interface — not a trained model. The booking system is a
  labeled fake adapter. Reviewer actions aren't authenticated in the demo."
