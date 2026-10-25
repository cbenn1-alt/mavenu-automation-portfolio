# Q09 — Demo Script

**Status: Implemented · Tested** (2026-10-23). All data below is
synthetic; the demo runs against fabricated techs, jobs, and zones.

## Setup (2 minutes)

1. Start the app: `.venv/bin/python run.py` (or per repo README).
2. Open `/project_q09`. The dashboard shows tech/job/run counts.
3. Click **Seed fixtures** (seed 7, 6 techs, 24 jobs) — deterministic
   synthetic day. All names and zones are invented.

## The story (5 minutes)

**"Dispatch was a whiteboard, a phone, and twenty years of gut feel."**

1. **Run the solver.** Click *Solve current techs + jobs*. The run page
   shows:
   - the proposed plan: every job → tech + time slot + travel time;
   - **reason codes** on every assignment (`SKILL_MATCH`,
     `ZONE_PROXIMITY`, `LOAD_BALANCE`, …) — the solver explains itself;
   - the **honest gap** vs. the nearest-available baseline (e.g.
     +24.0% — and on some days it loses; say so, that's the point);
   - the **infeasibility report**: jobs that couldn't be placed, each
     with explicit violated-constraint codes — never silent drops.
2. **Play dispatcher.** Go to *Q09 Overrides*. Pin a job to a specific
   tech with a written reason ("Customer requested Alex specifically").
   Re-run the solver: the assignment moves, labeled `PINNED`. Try pinning
   a job to a tech without the skill — the solver refuses and reports
   `PIN_SKILL_MISMATCH` instead of corrupting the plan.
3. **Show the audit trail.** The overrides page lists every override with
   its reason, actor, and timestamp. Nothing about *why* a decision was
   made lives only in someone's head anymore.

## Talking points (honest)

- "The heuristic is **not optimal** — we measure it against a simple
  baseline every run and publish the gap, good or bad."
- "Every assignment explains itself with reason codes."
- "The dispatcher can always overrule — but the overrule is on the
  record, with a reason."
- "Unplaceable jobs get an explicit report, never a silent drop."
- "Zero skill or time-window violations across 7,500 synthetic test
  dispatches — the constraints are structural, not aspirational."
- "Everything you're seeing is synthetic demo data. A real deployment
  would need labor rules, real routing, and certified skills modeled as
  constraints first."

## API alternative

```bash
curl -X POST localhost:8080/api/dispatch/seed \
  -d '{"seed":7,"n_techs":6,"n_jobs":24}'
curl -X POST localhost:8080/api/dispatch/run -d '{}'
curl localhost:8080/api/dispatch/runs/1
curl -X POST localhost:8080/api/dispatch/overrides \
  -d '{"job_id":"job-7-001","tech_id":"tech-7-01","kind":"pin",
       "reason":"Customer requested this tech specifically"}'
```

(Adjust the port to the app's configured `MAVENU_PORT`.)
