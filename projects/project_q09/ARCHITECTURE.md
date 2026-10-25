# Q09 — Architecture

**Status: Implemented · Tested** (2026-10-23).

## Layer map

The spec's four layers map onto two service modules (stdlib-only, no
framework):

```
dispatch_model.py   model/     — Job / Tech dataclasses, Commitment,
                                 constraint definitions (HARD_CONSTRAINTS),
                                 reason-code + infeasibility-code vocabularies,
                                 synthetic zone geography + travel model,
                                 deterministic fixture generators
dispatch.py         solve/     — DispatchPolicy protocol,
                                 GreedyLocalImprovementPolicy,
                                 NearestAvailableBaseline,
                                 verify_solution
                    explain/   — reason codes attached in solve(); refreshed
                                 after local improvement
                    audit/     — create_tech/create_job/run_solver/
                                 record_override/current_pins/run_detail/
                                 seed_demo + dispatch_events logging
migrations/012_dispatch.sql (+ .down.sql)
web.py              /project_q09* pages + /api/dispatch* endpoints
```

## Data flow

```
techs/jobs (validated) ─┐
                        ├─► run_solver ─► DispatchPolicy.solve(jobs, techs, pins)
dispatcher pins ────────┘         │                    │
                                  │                    ▼
                                  │              Solution (pure):
                                  │              assignments + infeasible[]
                                  ▼
                        verify_solution (hard-constraint re-check;
                                         non-empty = internal error, raise)
                                  │
                    ┌─────────────┴──────────────┐
                    ▼                            ▼
        GreedyLocalImprovementPolicy   NearestAvailableBaseline
        (persisted as the plan)       (persisted as the comparison)
                    │                            │
                    └─────────────┬──────────────┘
                                  ▼
              dispatch_runs row: solver name + policy_params JSON,
              total_cost / total_travel / total_lateness,
              baseline_cost / baseline_travel, cost_gap_pct,
              assigned_count / infeasible_count, duration_ms
              + dispatch_assignments (reason_codes JSON)
              + dispatch_infeasibility (violated JSON + detail)
```

## The heuristic (documented, not optimal)

**Objective** (minimized):
`total_cost = Σ travel_minutes + lateness_weight × Σ priority × max(0, start − window_start)`

**Phase 1 — greedy construction.** Jobs ordered by (−priority,
window_start, external_id). Each job is inserted into the feasible
tech/slot with the lowest *incremental cost* (added travel, net of
displaced legs, + lateness penalty). A slot is feasible only if skill,
window, shift, no-overlap, travel-allowance, and pin constraints all hold.
Ties break deterministically (lower assigned minutes, then tech id).

**Phase 2 — local improvement.** Relocate moves (job → another tech's best
slot) and swap moves (two jobs exchange techs) are tried in deterministic
order; a move is taken only if it *strictly* reduces total cost. Pinned
jobs are never moved. Bounded by `max_passes` (default 20).

**Why this shape:** honest heuristics with a measured baseline beat a fake
"AI optimizer". The greedy pass is fast and explainable; the improvement
pass fixes its myopia where cheap to do so; the baseline keeps both
honest.

## Baseline (the honest comparator)

`NearestAvailableBaseline`: same job order, same hard constraints, same
pins — but each job goes to the skilled tech whose *home zone* is closest,
at that tech's earliest feasible slot. No load balancing, no lateness
awareness, no improvement pass. The run records
`cost_gap_pct = (baseline − solver) / baseline × 100` — positive means the
heuristic won *that day*. Over 250 synthetic days the mean is +34.6%, but
the heuristic loses 4 days (worst −12.3%): the gap is reported, not
marketed. Assigned *sets* can differ between the two plans; the gap
compares total plan cost, documented here and in TEST_RESULTS.md.

## Constraint enforcement

Constraints are enforced *structurally*: `_best_slot` only ever returns
slots satisfying every hard constraint, so a violating assignment cannot
be constructed by the solver. `verify_solution` then re-checks the
finished plan independently (skill, window, shift, overlap, travel
consistency, pin compliance); `run_solver` raises `DispatchError` and
persists nothing if it is non-empty. Tests assert both the structural
property (7,500 synthetic dispatches, zero violations) and the checker
itself (hand-built violations are all caught).

## Overrides and re-solves

`dispatch_overrides` is append-only: `pin` / `reassign` / `unpin` with a
mandatory reason (≥ 8 chars), actor, and timestamp. `current_pins` folds
the log to latest-per-job (pin/reassign set, unpin clears). Every solve
reads current pins and treats them as hard constraints; the improver never
moves pinned jobs. A re-solve is simply a new `dispatch_runs` row — plans
are versioned, never mutated.

## Infeasibility

`_diagnose` classifies each unplaced job with the most specific applicable
`INF_*` code and a human-readable detail. The report is persisted per run
and rendered on the run page. Silent drops are impossible by construction:
every input job ends up in exactly one of `dispatch_assignments` or
`dispatch_infeasibility` for the run (asserted by tests).

## Explainability

Reason codes are attached at greedy placement (`SKILL_MATCH` always;
`ZONE_PROXIMITY` when travel-in ≤ 10 min; `LOAD_BALANCE` when the tech was
below average load at decision time; `PINNED`; `MIN_INCREMENTAL_COST` for
the chosen candidate) and refreshed after local improvement (`ZONE_PROXIMITY`
recomputed on final travel; `LOCAL_IMPROVEMENT` added when the final
placement differs from the greedy one). `run_solver` rejects any
assignment with zero or unknown codes.

## Replaceability

`DispatchPolicy` is a `Protocol` (same pattern as P01's `LeadClassifier`):
any object with `.name` and `.solve(jobs, techs, pins) -> Solution` can
drive `run_solver`. The baseline already is a second implementation. A
future exact solver (e.g. MILP) or learned policy slots in without
touching persistence, audit, or the web layer.
