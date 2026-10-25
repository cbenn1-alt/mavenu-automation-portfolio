# Q09 — Technician Dispatch Optimizer

**Status: Implemented · Tested** — 36 automated tests, all passing
(full suite 970/970: 934 baseline + 36 Q09; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Heuristic solver: greedy construction + relocate/swap local improvement behind the replaceable `DispatchPolicy` protocol, with a documented objective (minimize travel + priority-weighted lateness); side-by-side nearest-available baseline with an honestly reported gap; hard-constraint enforcement (skill, window, shift, no-overlap, travel consistency, pins) verified by `verify_solution` before any plan is persisted; dispatcher overrides (pin/reassign/unpin) with mandatory written reasons, append-only audit; explicit per-job infeasibility reports (never silent drops); per-assignment reason codes; migration `012_dispatch.sql` + real rollback test |
| What is SIMULATED | **Simulated** | The synthetic dispatch days (deterministic seeded fixtures); the 4×4 zone grid and its travel-time model (a stand-in for routing, never presented as a routing engine) |
| What is SYNTHETIC | **Demo** | **Every tech name, zone, skill, job, window, and commitment is fabricated.** No real people, no real businesses, no real service territory. The UI carries the "SYNTHETIC DEMO DATA" banner |
| What is NOT claimed | — | **Not optimal.** The heuristic is measured against the baseline and the gap is reported whichever way it goes (mean +34.6% over 250 synthetic days; loses on 4 of 250 days — see below). No production deployment. No real users, no real dispatch data, no routing-engine integration. No platform or employer endorsement |

## Business problem

Dispatch is a whiteboard and a gut feeling. Techs crisscross town, skills
mismatch jobs, and urgent calls bump scheduled work with no record of why.

This project is a working optimizer: it takes jobs (zone, skill, duration,
priority, time window) and techs (skills, home zone, shift, current load),
proposes an assignment that minimizes travel + lateness while respecting
every hard constraint, explains each assignment with reason codes, lets the
dispatcher pin or reassign with a written reason (every override audited),
and reports exactly why any job could not be placed.

## Implemented capabilities

- **Model** (`dispatch_model.py`): `Job`/`Tech` dataclasses with strict
  server-side validation (zones A1–D4, skills hvac/plumbing/electrical/
  roofing, priority 1–5, window/shift sanity); deterministic synthetic
  fixture generators (`synthetic_day(seed, n_techs, n_jobs)`);
  documented travel model (5 min intra-zone + 4 min per grid step)
- **Solver** (`dispatch.py::GreedyLocalImprovementPolicy`): greedy
  construction (priority → window order, cheapest feasible incremental
  cost) + relocate/swap local improvement until no strict improvement;
  pins honored as hard constraints and never moved by the improver
- **Documented objective**: `total_cost = travel_minutes +
  lateness_weight × Σ(priority × max(0, start − window_start))`
  (default `lateness_weight = 0.5`, stored per run)
- **Baseline** (`NearestAvailableBaseline`): same constraints, myopic
  choice (closest home zone, first feasible slot) — the honest comparator
- **Infeasibility reports**: every unplaced job gets explicit `INF_*`
  codes (`NO_TECH_WITH_SKILL`, `PIN_SKILL_MISMATCH`,
  `PIN_UNSATISFIABLE`, `WINDOW_TOO_SHORT_FOR_DURATION`,
  `NO_SHIFT_OVERLAP_WITH_WINDOW`, `NO_FEASIBLE_SLOT`) + a human-readable
  detail — jobs are never silently dropped
- **Explainability**: every assignment carries ≥ 1 reason code
  (`SKILL_MATCH`, `ZONE_PROXIMITY`, `LOAD_BALANCE`, `PINNED`,
  `MIN_INCREMENTAL_COST`, `LOCAL_IMPROVEMENT`)
- **Overrides**: pin / reassign / unpin; reason ≥ 8 chars mandatory;
  append-only `dispatch_overrides`; latest-per-job wins; re-solves honor
  pins as hard constraints
- **Audit**: `dispatch_events` rows + JSON stdout lines for tech/job
  creation, runs, and overrides
- **Web + API**: `/project_q09` dashboard, `/project_q09/runs/<id>`
  (assignments + reason codes + baseline comparison + infeasibility
  report), `/project_q09/overrides` (form + audit trail);
  `/api/dispatch/*` endpoints (techs/jobs CRUD, seed, run, run detail,
  overrides)

## Measured solver performance (synthetic, 2026-10-23)

250 deterministic synthetic days (6 techs × 30 jobs each), heuristic vs.
nearest-available baseline, identical constraints, identical pins:

| Metric | Value |
|---|---|
| Mean gap (positive = heuristic wins) | **+34.58%** |
| Median gap | +35.94% |
| Best day | +81.79% |
| Worst day | **−12.30%** (heuristic loses — reported, not hidden) |
| Days heuristic wins | 246 / 250 |

**Zero skill/window/shift/overlap violations** across 7,500 synthetic
dispatches (250 days × 30 jobs), re-verified by `verify_solution` on every
finished plan before persistence.

These numbers describe the heuristic on fabricated fixtures — they are not
a claim about real-world dispatch performance. The README states the gap
plainly because the point of the baseline is honesty, not marketing.

## Real deployments must consider

Labor rules are **required inputs, not afterthoughts**: drive-time pay,
overtime thresholds, mandated breaks, and maximum shift lengths must be
modeled as constraints before this touches a real roster. The synthetic
shift model here has none of that. Documented in REQUIREMENTS.md and
RUNBOOK.md.
