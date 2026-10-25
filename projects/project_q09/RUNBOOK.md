# Q09 — Runbook

**Status: Implemented · Tested** (2026-10-23).

## Normal operation

1. **Load a synthetic day** — `POST /project_q09/seed` (form) or
   `POST /api/dispatch/seed` with `{"seed": 7, "n_techs": 6, "n_jobs": 24}`.
   Deterministic: the same seed always builds the same day. Re-seeding is
   a no-op on existing `external_id`s.
2. **Run the solver** — `POST /project_q09/run` or
   `POST /api/dispatch/run` (optional `{"lateness_weight": 0.5,
   "max_passes": 20}`). Honors current dispatcher pins. Returns the run
   summary including the honest baseline gap.
3. **Review the plan** — `GET /project_q09/runs/<id>`: assignments with
   reason codes, baseline comparison, and the infeasibility report.
4. **Dispatcher overrides** — `POST /project_q09/overrides` (or
   `POST /api/dispatch/overrides`) with `job_id`, `tech_id` (omit for
   unpin), `kind` (pin/reassign/unpin), and a **required reason** (≥ 8
   chars). Re-run the solver to apply.

## Interpreting results

- **Gap positive**: the heuristic beat the nearest-available baseline on
  that day. **Gap negative**: it lost — this is expected on some days
  (worst measured −12.3% over 250 synthetic days); it is not an error.
- **Infeasible jobs**: read the `violated` codes and `detail` text.
  Common causes: no tech holds the skill (hire/train or decline the job),
  window shorter than duration (bad intake data), capacity (add a tech or
  widen windows). Never re-enter the same data expecting a different
  result — fix the underlying cause.
- **Pins not honored**: a pin that cannot be satisfied appears as
  `PIN_SKILL_MISMATCH` / `PIN_UNSATISFIABLE` in the infeasibility report.
  Check the tech's skills, shift, and existing load.

## Rollback procedure

Every schema change ships a down-step. To roll back Q09's migration:

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection("<db path>")
rollback_migration(conn, "012_dispatch.sql")  # drops all dispatch_* tables
```

To re-apply:

```python
from mavenu.db import run_migrations
run_migrations(conn)  # re-applies 012_dispatch.sql
```

The rollback is exercised for real in
`tests/test_dispatch.py::test_migration_012_down_step_rolls_back_for_real`
(2026-10-23): migrate → seed → solve → override → roll back (all seven
`dispatch_*` tables dropped, other projects' tables untouched) →
re-apply cleanly.

**WARNING:** rolling back deletes all Q09 data (techs, jobs, runs,
assignments, overrides, events). All of it is synthetic demo data by
design. Do not run the down-step against a database whose Q09 records you
need to keep.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `422` on tech/job create | Validation failure (bad zone/skill/window/shift) | Read `field_errors` in the response |
| `422` on override | Missing/short reason, bad kind | Supply a reason ≥ 8 chars |
| `404` on run detail | Unknown run id | List runs from `/project_q09` |
| Solve returns 0 assigned | No techs/jobs loaded, or all infeasible | Seed fixtures; read the infeasibility report |
| `DispatchError` from `run_solver` | Internal invariant broken (solver produced a violating plan) | Do not retry blindly — capture the message; it names the violations; file a bug |
| Slow solve on huge inputs | Input beyond demo scale | Stay within tested scale (≤ 50 techs / 500 jobs); the improvement loop is bounded by `max_passes` |

## Real-deployment note

Before any real roster touches this system: model labor rules as
constraints (drive-time pay, overtime, breaks, max shift lengths),
replace the synthetic travel model with real routing, and put
authentication on every endpoint (see SECURITY.md).
