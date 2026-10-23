# Q01 — Test Plan

**Scope:** 89 tests across three files, all run with the project venv
pytest. P01's 51 and P02's 101 tests must keep passing (regression gate).

## Coverage map

| Area | File | Tests | What is asserted |
|---|---|---|---|
| Scorer weights | `test_urgency_scorer.py` | 15 | Base 0.20; after-hours +0.15 (evening, weekend, boundaries 08:00/18:00); emergency keyword +0.20 (case-insensitive); soft keyword +0.05 only; emergency precedence over soft (no stacking); repeat caller +0.25; long rings ≥8 +0.10 (7 rings none); voicemail +0.10 (blank transcript none); clamp at 1.0; 3-decimal rounding; reasons explain every applied rule |
| Scorer determinism | `test_urgency_scorer.py` | 3 | 10,000 replays of identical input → identical `UrgencyScore`; value-object equality; protocol shape (`name`, `score`) |
| Scorer fuzz | `test_urgency_scorer.py` | 2 | Score stays in [0, 1] across a 500-combination product of transcripts × times × rings × repeat counts |
| Caller-ID privacy | `test_missed_calls.py` | 4 | Mask hides all but last 4; short-number masking; hash deterministic/format/normalization-insensitive/distinct; **raw digits absent from every text column** of `missed_calls` + `call_events` |
| Event validation | `test_missed_calls.py` | 6 | Clean normalization (incl. string→int coercion); bad timestamp / short caller ID / bad ring count / bad duration / non-string transcript rejected with field errors; transcript capped at 2000 chars |
| Ingestion | `test_missed_calls.py` | 8 | Event ingest creates MC-000001 with masked/hash/score/events; dedup key returns original + `call.duplicate_received` event (no new row); out-of-order timestamps accepted; repeat caller gets +0.25; 3rd call in 24h flags `repeat-id-anomaly`; CSV batch with row-level errors (accepted/rejected/duplicates counts + row numbers); CSV duplicates counted; headerless CSV degrades gracefully (0 accepted, 0 rejected) |
| Idempotency | `test_missed_calls.py` | 1 | Repeated key replays original body without a new row |
| Claim/assign | `test_missed_calls.py` | 4 | Sets assignee, state unchanged, `call.claimed` event; blank assignee rejected; unknown call → KeyError; non-pending claim → InvalidTransition |
| Outcome state machine | `test_missed_calls.py` | 6 | Full legal path pending→attempted→connected→booked; `attempted_at` / `outcome_at` stamps; `pending→lost` admin close; 10 illegal transitions raise and leave state unchanged (parametrized); terminal states have no outgoing moves; unknown call → KeyError |
| Migration rollback | `test_missed_calls.py` | 2 | Down-step rolls back 003 for real (tables dropped, migration record removed, P01/P02 tables untouched, re-apply works); rollback of unapplied migration is a no-op |
| Priority queue | `test_recovery_queue.py` | 4 | Ordering by score × age decay; decay formula exact (halves at 24h); non-pending excluded; limit honored |
| SLA escalation | `test_recovery_queue.py` | 3 | Aging high-urgency call escalated: `escalated=1`, one `queued-stub` notification row with honest stub text, `call.escalated` event; sweep idempotent (no second notification); attempted calls skipped |
| Ingestion-lag alert | `test_recovery_queue.py` | 3 | Current feed → no alert with gap_hours; stale feed (10h) → alert with "stale" message; empty DB → no alert, `newest_missed_at` None |
| Dashboard reconciliation | `test_recovery_queue.py` | 3 | Seeded 3-call fixture: totals, by-state, booked count, recovery/contact rates, median TTCB all match an **independent raw-SQL re-computation** (hand-computed 30/60/120 min → median 60); empty DB zeros; full pipeline CSV→queue→claim→outcome→dashboard with totals reconciling |
| Performance | `test_recovery_queue.py` | 1 | 2,000 synthetic events ingested individually; p95 < 5 ms/event (measured 0.279 ms) |
| Web + API | `test_recovery_queue.py` | 14 | Hub lists Q01; form page renders; HTML single-event import → 303 to queue; queue + dashboard pages 200; `POST /api/missed-calls` 201; invalid payload → 422 envelope; idempotent replay → 200 `replayed`; CSV import endpoint; claim + full outcome flow via API; illegal outcome → 409; detail GET (masked caller, allowed transitions, events); unknown call → 404; dashboard + SLA sweep endpoints |

## Test doubles and determinism

- **Clock:** `T0 = 2026-10-23T12:00:00Z`; every service call passes `now=`.
  Outcome events accept an injectable `created` timestamp so
  time-to-callback assertions are exact.
- **No network, no randomness in assertions:** public IDs are sequential
  (`MC-000001`…); the scorer is a pure function.
- **Fixtures are synthetic:** invented 555 caller IDs, invented names
  (`Rosa`), invented transcripts.

## What is not tested (documented gaps)

- Real telephony ingestion (none exists by design; see README).
- Actual notification delivery (stubs only, by design).
- Concurrency (single-process demo; SQLite WAL only).
- Authentication (none exists by design; see SECURITY.md).
- Scheduled sweep execution (endpoint tested; cron wiring is an ops step).

## Regression gate

Full suite: `.venv/bin/python -m pytest tests/ -q` → **241 passed**
(51 P01 + 101 P02 + 89 Q01), recorded in TEST_RESULTS.md with date and
environment.
