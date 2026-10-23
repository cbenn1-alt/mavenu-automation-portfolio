# Project 01 — Evidence-Backed Business Case
**AI Revenue Operations Engine** · Prepared 2026-10-22 · Status: working software, Gate A verified

> Every number below is labeled **MEASURED** (taken from the running system) or **ESTIMATE** (modeled, assumptions stated). Nothing is presented as a customer result — there is no production deployment yet.

## What it does
A home-services business's inbound leads enter through a form or API. The engine validates, dedupes, qualifies, and routes each lead — booking strong leads automatically, sending uncertain ones to human review — with every state change written to an audit trail and every dashboard total reconciled to the database.

## MEASURED results (this system, 2026-10-22)

| Metric | Value | How measured |
|---|---|---|
| Lead intake → routed/booked, p50 | **0.23 ms** | 300 timed `submit_lead` calls, in-process SQLite |
| Lead intake → routed/booked, p95 | **0.38 ms** | same run |
| Duplicate-submission replay | **0.01 ms**, zero new records | 300 replays of one idempotency key |
| Single-process throughput | **~4,400 leads/sec** | derived from p50 |
| Automated tests | **51 passed, 0 failed** | `.venv/bin/python -m pytest tests/ -q` (0.14s) |
| Acceptance criteria (spec §8) | **7/7 PASS** | mapped 1:1 to tests; see TEST_RESULTS.md |
| Invalid-input rejection | 16/16 validation tests pass | malformed phone, bad service type, missing fields all rejected before storage |
| Uncertain-output handling | 5/5 classifier tests pass | below-threshold scores → `needs_review`, never auto-booked |
| Dashboard reconciliation | PASS | `/api/stats` totals match DB row counts in live smoke test |

## ESTIMATES — business value model (assumptions stated)
Modeled for a **typical home-services business receiving ~40 inbound leads/week**:

| Item | Before (manual) | After (engine) | Basis |
|---|---|---|---|
| Intake + qualification labor per lead | ~8 min (call-back, questions, data entry) | ~0 min auto-booked; ~2 min for flagged review | ESTIMATE — industry-typical handling time |
| Exception/review rate | n/a (all manual) | ~25–35% routed to `needs_review` | ESTIMATE — from classifier threshold design; to be calibrated on real lead mix |
| Duplicate lead records | common (re-entry, repeat callers) | **0** (idempotency keys + possible-duplicate flagging) | MEASURED mechanism; rate ESTIMATE |
| Missed-lead loss | after-hours/weekend calls lost | captured 24/7 | ESTIMATE |

**Annualized (40 leads/wk × 50 wks = 2,000 leads/yr):**
- Labor saved: 2,000 × 8 min ≈ **267 hrs/yr** gross, minus review time (~30% × 2 min × 2,000 ≈ 20 hrs) → **≈ 245 net hours/yr**. ESTIMATE.
- Operating cost: **$0/yr** — stdlib Python + SQLite, no licenses, no per-seat fees, runs on existing hardware. MEASURED (dependency list: zero).
- Payback period: **immediate** — $0 operating cost means the first hour of labor saved is net positive. ESTIMATE on the labor side, MEASURED on the cost side.
- Error-rate reduction: validation rejects malformed input before storage (MEASURED: 16/16); duplicate business records eliminated by design (MEASURED mechanism). Baseline customer error rates are **not yet measured** — first pilot will establish them.

## Architecture
Modular monolith, Python stdlib only (`wsgiref`-compatible WSGI app), one SQLite file for business records + audit trail + idempotency keys. Service layer (`leads.py`) is HTTP-agnostic and fully unit-tested; `workflow.py` owns the 7-state machine (`received → qualified → routed → booked`, plus `needs_review` / `rejected` / `cancelled`); classifier and booking sit behind replaceable interfaces (`LeadClassifier` protocol, `BookingAdapter` protocol). Full diagram: `ARCHITECTURE.md`.

## Demo
Scripted walkthrough: `DEMO.md` — submit a strong lead (→ `booked` with booking ref), a thin lead (→ `needs_review`), replay a duplicate (no new record), watch the dashboard reconcile. **Video:** not yet recorded — script is `DEMO.md`; recording happens against the next stable release.

## Test results
51/51 passing across workflow (6), validation (16), classifier (5), service/acceptance (10), HTTP/API (14). Full report: `TEST_RESULTS.md`. The suite caught one real bug during development (uncommitted audit rows on the no-idempotency-key path) — fixed and regression-guarded.

## Decision memo — why these tools, how risk was controlled
- **Python stdlib + SQLite, zero dependencies:** no license cost, no supply-chain surface, no version drift, fully auditable by any reviewer. A framework would add nothing the service layer needs; it can be adopted later without changing business rules.
- **State machine in one module:** illegal transitions are impossible by construction, not by convention — the highest-value risk control in a workflow system.
- **Idempotency keys:** retries and double-submits replay the original response instead of duplicating business records — the classic source of phantom revenue/leads.
- **Deterministic demo classifier, honestly labeled:** the `LeadClassifier` protocol accepts a real model later; the shipped implementation is rule-based and says so. No model-inference claims are made.
- **Audit trail as a first-class table:** every state change is a committed row with actor + timestamp — the same shape an enterprise change-control process requires.
- **Remaining risks:** no production deployment yet (pilot will establish real baselines); single-process server is not a high-availability story (documented in RUNBOOK.md as a known limitation); SQLite fits the current scale and migrates cleanly if volume demands it.
