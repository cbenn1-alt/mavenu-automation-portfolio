# Q09 — Evidence Matrix

Every public claim about this project, mapped to the test or artifact
that backs it. Labels: **Implemented** (code exists), **Tested**
(automated test passes), **Simulated** (stubbed/fixture behavior),
**Demo** (illustrative only). "Labeled estimate" marks numbers that
describe the fixture, not the real world.

| # | Claim | Label | Evidence |
|---|---|---|---|
| 1 | Job/tech CRUD with strict validation | Implemented, Tested | `tests/test_dispatch.py::test_normalize_job_rejects_bad_input` (6 cases), `test_normalize_tech_rejects_bad_input` (6 cases); `tests/test_dispatch_api.py::test_api_tech_crud_and_validation`, `test_api_job_crud_and_validation` (422s) |
| 2 | Idempotent creation on natural key `external_id` | Implemented, Tested | `test_create_tech_and_job_idempotent`; API re-post (`replayed: true`) |
| 3 | Greedy + local-improvement heuristic behind replaceable `DispatchPolicy` protocol | Implemented, Tested | `dispatch.py::GreedyLocalImprovementPolicy`; `test_local_improvement_marks_moved_assignments` (improver never regresses vs greedy-only) |
| 4 | Documented objective: minimize travel + priority-weighted lateness | Implemented, Tested | Module docstring + ARCHITECTURE.md; `policy_params` stored per run (`test_run_solver_stores_policy_params`) |
| 5 | NOT optimal — honest gap vs nearest-available baseline reported | Implemented, Tested | `NearestAvailableBaseline`; `test_baseline_comparison_honest_margin`; TEST_RESULTS.md (mean +34.58%, worst −12.30%, wins 246/250) |
| 6 | Baseline margin numbers (mean +34.58%, min −12.30%, max +81.79%) | Tested (labeled estimate) | `test_baseline_comparison_honest_margin` (250 fixed-seed synthetic days); numbers describe fabricated fixtures only |
| 7 | Zero skill/window violations across synthetic dispatches | Tested | `test_zero_violations_across_large_synthetic_run` — 7,500 dispatches, `verify_solution` empty on all |
| 8 | `verify_solution` independently re-checks constraints | Tested | `test_verify_solution_catches_window_violation`, `test_verify_solution_catches_overlap`; `run_solver` raises `DispatchError` and persists nothing on violation |
| 9 | Skill mismatch can never slip through the solver | Implemented, Tested | Structural (slots only from feasibility check) + `test_pin_to_unskilled_tech_is_reported_not_forced` (`PIN_SKILL_MISMATCH`, never forced) |
| 10 | Infeasible jobs get explicit reports; never silent drops | Implemented, Tested | `test_infeasibility_*` (6 tests); `test_run_solver_persists_run_and_comparison` asserts assigned ∪ infeasible = all jobs, disjoint |
| 11 | Every assignment carries reason codes | Implemented, Tested | `test_every_assignment_carries_valid_reason_codes` (5 seeds); `run_solver` rejects empty/unknown codes |
| 12 | Overrides: pin/reassign/unpin with mandatory reasons; 100% logged | Implemented, Tested | `test_override_requires_reason`, `test_override_audit_completeness_and_pin_honored` (5/5 logged) |
| 13 | Pins honored by re-solve as hard constraints | Implemented, Tested | `test_pin_forces_non_greedy_choice` (pin beats greedy, labeled `PINNED`); improver never moves pinned jobs (code + test) |
| 14 | Deterministic solver and fixtures | Implemented, Tested | `test_solver_is_deterministic`, `test_fixture_generators_are_deterministic` |
| 15 | Migration `012_dispatch.sql` + tested rollback | Implemented, Tested | `test_migration_012_down_step_rolls_back_for_real` (2026-10-23) |
| 16 | Web pages + JSON API | Implemented, Tested | `tests/test_dispatch_api.py` (8 tests): CRUD, seed, run, run-detail, overrides, pages, form flows |
| 17 | Audit trail of tech/job creation, runs, overrides | Implemented, Tested | `test_events_audit_trail`; `dispatch_events` table + JSON stdout lines |
| 18 | Known-good fixture reproduces the obvious assignment | Tested | `test_known_good_fixture_reproduced` (2-tech/4-job hand-built day) |
| 19 | All techs/jobs/zones synthetic; no real people or territory | Demo | Fixture header + migration header + module docstrings + README banner; `BANNER` on every page |
| 20 | Real deployments must model labor rules (drive-time pay, overtime) | Demo (documented requirement) | REQUIREMENTS.md "Real-deployment requirements", README + RUNBOOK.md callouts |

## What is NOT claimed (and where that is enforced)

- No optimal-solver claim — claim #5; README honest-status banner;
  worst-day loss (−12.30%) published in TEST_RESULTS.md.
- No production deployment, no real users, no real dispatch data —
  README banner; `not claimed` row in the matrix.
- No routing engine — the travel model is documented as a synthetic
  stand-in (`dispatch_model.py` docstring; claim #19).
- No ML/AI model — the solver is a documented heuristic; the word
  "optimizer" refers to the heuristic + measurement apparatus, and the
  README says so.
- Override reasons are recorded, not judged — SECURITY.md abuse-case
  notes; a human reviewer owns the judgment.
- Performance numbers are fixture-labeled estimates, never real-world
  measurements — README + TEST_RESULTS.md disclaimers.
