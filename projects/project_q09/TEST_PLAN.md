# Q09 — Test Plan

**Status: Tested** — 36 tests, all passing (2026-10-23).

## Strategy

Unit tests for validation and the pure solver; integration tests for
persistence (runs, overrides, audit); API/page tests for the web layer;
property-style tests for determinism and large-scale constraint
compliance; an honest-measurement test for the baseline margin; a real
rollback test for the migration down-step.

All fixtures are synthetic (deterministic seeded generators + hand-built
cases). Nothing is pre-filled: TEST_RESULTS.md records real runs.

## Coverage map

| Area | Tests | What is asserted |
|---|---|---|
| Model validation | `test_travel_matrix_documented_and_symmetric`, `test_normalize_job_rejects_bad_input` (6 cases), `test_normalize_tech_rejects_bad_input` (6 cases), `test_window_shorter_than_duration_is_creation_legal_but_reported` | Travel model exact + symmetric; bad zone/skill/duration/window/priority/shift/commitments rejected; short-window jobs are creation-legal so the infeasibility path is exercisable |
| Known-good fixture | `test_known_good_fixture_reproduced` | Hand-built 2-tech/4-job day reproduces the obvious assignment exactly; zero violations; `SKILL_MATCH` on every assignment |
| Determinism | `test_solver_is_deterministic`, `test_fixture_generators_are_deterministic` | Same input → identical plan; same seed → identical fixtures; different seed → different fixtures |
| Infeasibility | `test_infeasibility_no_skilled_tech`, `test_infeasibility_window_too_short`, `test_infeasibility_no_shift_overlap`, `test_infeasibility_no_feasible_slot_capacity`, `test_pin_to_unskilled_tech_is_reported_not_forced`, `test_pin_unsatisfiable_reported` | Each `INF_*` code fires on its fixture; priority wins capacity contention; pinned-to-unskilled-tech is reported (`PIN_SKILL_MISMATCH`), never forced |
| Constraint checker | `test_verify_solution_catches_window_violation`, `test_verify_solution_catches_overlap` | The independent checker catches hand-built window and overlap violations (so "zero violations" is a checked claim, not an assumption) |
| Reason codes | `test_every_assignment_carries_valid_reason_codes`, `test_local_improvement_marks_moved_assignments` | ≥ 1 valid code on every assignment across 5 seeds; improver never breaks constraints; improver never regresses vs greedy-only; moved assignments labeled `LOCAL_IMPROVEMENT` |
| Baseline margin (honest) | `test_baseline_comparison_honest_margin` | 250 synthetic days (6×30): both plans verified violation-free; gap computed per day; mean > 0 (regression tripwire); worst day > −20 (catastrophe tripwire, not a claim). Prints the honest mean/min/max |
| Scale compliance | `test_zero_violations_across_large_synthetic_run` | 250 days × 30 jobs = **7,500 dispatches**, `verify_solution` empty on every one |
| Persistence | `test_create_tech_and_job_idempotent`, `test_create_rejects_invalid`, `test_run_solver_persists_run_and_comparison`, `test_run_solver_stores_policy_params` | Natural-key idempotency; invalid input rejected with nothing stored; run row stores solver + params + both costs + gap; assigned ∪ infeasible = all jobs, disjoint |
| Overrides | `test_override_requires_reason`, `test_override_audit_completeness_and_pin_honored`, `test_pin_forces_non_greedy_choice`, `test_events_audit_trail` | Reason mandatory (empty/short/bad-kind/unknown-job rejected; nothing logged on failure); 5/5 overrides logged with reasons; latest-per-job semantics (reassign supersedes pin; unpin clears); re-solve honors pins (assigned-to-pin with `PINNED` label, or infeasible — never assigned elsewhere); pin beats greedy; audit event types present |
| Rollback | `test_migration_012_down_step_rolls_back_for_real` | Real DB: migrate → seed → solve → override → `rollback_migration("012_dispatch.sql")` → all `dispatch_*` tables gone, migration record removed, other projects' tables intact → `run_migrations` re-applies cleanly |
| API | `tests/test_dispatch_api.py` (8 tests) | Tech/job CRUD + 422s; idempotent re-post; seed/run/run-detail (404 on unknown run); override 422/404/201; custom policy params round-trip; pages render (dashboard, run detail with "Honest gap" + infeasibility report, overrides); form seed/run/override flows (303s) |

## What is NOT tested (and why)

- Real-world dispatch quality: fixtures are synthetic; the baseline gap is
  a labeled estimate, never presented as real-world performance.
- Labor-rule constraints: not modeled in v1 (documented as required
  inputs in REQUIREMENTS.md).
- Concurrency: the demo uses one connection per operation; no
  concurrent-solver test exists.
