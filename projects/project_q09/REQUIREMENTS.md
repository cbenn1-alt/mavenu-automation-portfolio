# Q09 — Requirements

**Status: Implemented · Tested** (2026-10-23). All requirements below are
implemented; out-of-scope items are listed explicitly and not built.

## Problem

Dispatch is a whiteboard and a gut feeling. Techs crisscross town, skills
mismatch jobs, and urgent calls bump scheduled work with no record of why.

## Target user

Dispatchers/owners at 3–15-tech home-service operations.

## Functional requirements

1. **Inputs (all synthetic).**
   - Jobs: location zone (A1–D4 synthetic grid), required skill
     (hvac/plumbing/electrical/roofing), duration (15–480 min), priority
     (1–5), hard time window `[window_start, window_end)`.
   - Techs: skill set (≥ 1), home zone, shift `[shift_start, shift_end)`,
     current load (pre-existing commitments that block shift time).
   - Strict server-side validation at every boundary; invalid input is
     rejected with field errors, never coerced silently.
2. **Assignment engine.** Greedy construction + local-improvement
   heuristic behind a replaceable `DispatchPolicy` protocol, with a
   documented objective: minimize `travel_minutes + lateness_weight ×
   Σ(priority × max(0, start − window_start))`. **NOT claimed as
   optimal** — every run executes a nearest-available baseline
   side-by-side and records the honest gap, whichever direction it goes.
3. **Hard constraints** (never violated; re-verified by `verify_solution`
   before any plan is persisted): skill match, window containment, shift
   containment, no overlapping bookings per tech, travel-time consistency
   between consecutive bookings, pin compliance.
4. **Infeasibility handling.** Any job that cannot be placed appears in an
   explicit infeasibility report listing violated-constraint codes
   (`NO_TECH_WITH_SKILL`, `PIN_SKILL_MISMATCH`, `PIN_UNSATISFIABLE`,
   `WINDOW_TOO_SHORT_FOR_DURATION`, `NO_SHIFT_OVERLAP_WITH_WINDOW`,
   `NO_FEASIBLE_SLOT`) plus a human-readable detail. **Jobs are never
   silently dropped.**
5. **Override support.** Dispatcher can pin / reassign / unpin a job.
   Every override requires a written reason (≥ 8 chars) and is append-only
   in the audit trail. Re-solves honor current pins as hard constraints.
6. **Explainability.** Every assignment carries ≥ 1 reason code:
   `SKILL_MATCH`, `ZONE_PROXIMITY`, `LOAD_BALANCE`, `PINNED`,
   `MIN_INCREMENTAL_COST`, `LOCAL_IMPROVEMENT`.
7. **Audit.** Tech/job creation, solver runs, and overrides are recorded
   in `dispatch_events` (queryable) plus JSON stdout log lines.
8. **Idempotency.** Tech/job creation is idempotent on the natural key
   `external_id` (re-seeding a fixture is a no-op).

## Non-functional requirements

- Python 3.12 stdlib only at runtime (`wsgiref`, `sqlite3`, `json`,
  `dataclasses`); $0 spend; no network calls.
- Deterministic: identical input (+ seed for fixtures) → identical plan.
- Solver run on a 6-tech × 24-job demo day completes in well under a
  second (measured: single-digit ms in tests).
- All data synthetic; no real PII anywhere; UTF-8 text only, no binaries.

## Real-deployment requirements (NOT built — required inputs)

A real deployment must model, as constraints, before use:
- **Labor rules**: drive-time pay, overtime thresholds, mandated breaks,
  maximum shift lengths, on-call rules.
- **Real geography**: a routing engine or distance matrix replaces the
  synthetic travel model; zones must map to a real service territory.
- **Skill certification**: skills must reflect real certifications, and
  expired/missing certs must block assignment.
- **Consent/retention**: customer addresses are sensitive; define
  retention and access rules with counsel.

## Out of scope (explicitly not built)

- Real-time GPS / live traffic; dynamic re-routing during the day.
- Customer notifications (SMS/email) — no send path exists in v1.
- Multi-day planning horizons (v1 solves one dispatch day at a time).
- Claimed optimality, ML models, or learned policies.
