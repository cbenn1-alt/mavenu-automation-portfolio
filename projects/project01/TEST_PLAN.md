# Project 01 — Test Plan

Suite: **51 tests**, run with `pytest tests/ -q` from the repo root
(Python 3.12, pytest 9.1.1 in `.venv`). No network, no external services.

## Coverage map

| Area | File | Tests | What is proven |
|---|---|---|---|
| State machine | `test_workflow.py` | 6 | All 7 lifecycle states; every legal transition allowed; illegal ones (skips, backwards, from terminal) raise `InvalidTransition`; terminal states have no outgoing transitions |
| Validation | `test_validation.py` | 16 | Field cleaning (phone normalization, email lowercase); each invalid field rejected with per-field errors; at-least-one-contact rule; notes cap; service-area membership |
| Classifier | `test_classifier.py` | 5 | Deterministic (same input → same output); strong lead qualifies; thin lead goes to review; confidence bounded 0–1; custom threshold respected |
| Service / acceptance | `test_leads.py` | 10 | Every spec §8 acceptance criterion (see REQUIREMENTS.md mapping): one record per valid submission; invalid rejected with zero records; idempotent replay; possible-duplicate flagging; low-confidence → review; out-of-area override; booking failure preserves lead + records incident; reviewer rescue flow; illegal manual transition raises; stats reconcile with DB |
| HTTP / API | `test_web.py` | 14 | Hub/health/dashboard pages; JSON create (201) and invalid (422 + field errors); idempotency-key replay over HTTP; stats reconcile over HTTP; lead detail with events + allowed transitions; reviewer transition API; illegal transition → 409; HTML form submit → 303 redirect; invalid form re-renders with errors; unknown route → 404 |

## Test doubles (all labeled)

- `FakeBookingAdapter(fail=True)` — simulates an integration outage.
- `DeterministicDemoClassifier` — the real bundled classifier; deterministic
  by construction, pinned by tests.

## What is NOT tested (known gaps)

- Concurrency under parallel writers (single-process demo; WAL mode on).
- Real ML model behavior — none exists; the interface is tested instead.
- Browser rendering — HTML is asserted as response bodies, not rendered.
- Authentication — reviewer actions are actor-labeled, not authenticated
  (demo scope; see SECURITY.md).

## Bug found by the suite during development

`test_api_get_lead_includes_events_and_transitions` caught a missing commit
in `record_event()`: audit rows were lost when no idempotency key triggered
a later commit. Fixed by committing inside `record_event()`; the suite now
guards the audit trail's durability.
