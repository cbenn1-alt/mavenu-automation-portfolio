# Q09 — Security Notes

**Status: Implemented · Tested** (2026-10-23).

## Threat model

This is a local demo web app (stdlib `wsgiref`, SQLite). It holds no real
data: every tech, job, zone, and name is synthetic. The realistic threats
are input abuse, injection, and audit-trail integrity — all addressed
below. There is no authentication in the demo; a real deployment must add
it (see "not in v1").

## Controls in place

- **Parameterized SQL only.** Every query uses `?` placeholders; no
  string-interpolated SQL anywhere in `dispatch.py` / `dispatch_model.py`.
- **Input validation at every boundary.** `normalize_job` /
  `normalize_tech` reject unknown zones/skills, inverted windows/shifts,
  out-of-range durations/priorities, overlapping or out-of-shift
  commitments. Web forms and JSON bodies go through the same validators;
  failures return 422 with field errors, never partial writes.
- **No secrets in code.** There are no credentials, API keys, or tokens
  anywhere in Q09. Settings come from environment variables (existing
  `config.py` pattern).
- **Override reasons are mandatory and length-checked** (≥ 8 chars),
  which also bounds log-injection noise; reasons are HTML-escaped on
  render (`html.escape` in web.py).
- **Audit trail integrity.** `dispatch_overrides` is append-only (no
  UPDATE/DELETE path exists); `dispatch_events` is insert-only.
  `current_pins` is a fold over the log, so history is never rewritten.
- **No silent state changes.** A solver run that fails `verify_solution`
  raises and persists nothing; infeasible jobs are reported, not dropped.
- **Deterministic, bounded compute.** The solver has no recursion and a
  bounded improvement loop (`max_passes`); worst-case work per run is
  polynomial in jobs × techs. Form inputs for seed/run sizes are
  range-checked (1–50 techs, 1–500 jobs) to bound demo-day compute.
- **Synthetic-data labeling.** The UI banner, migration header, module
  docstrings, and README all state the data is fabricated — no one can
  mistake a demo plan for a real roster.

## Abuse cases considered

- **Override abuse** (a dispatcher pinning everything to a favorite
  tech): mitigated by mandatory written reasons + the append-only,
  reviewable audit trail. The system does not judge the reason — a human
  reviewer does. Pins that cannot be satisfied produce
  `PIN_UNSATISFIABLE` / `PIN_SKILL_MISMATCH` reports instead of corrupt
  plans.
- **Constraint smuggling** (crafting a job that violates a window):
  impossible — slots are constructed only by the feasibility check, and
  `verify_solution` re-checks before persistence. Tests plant violations
  directly and assert they are caught.
- **Re-seed / duplicate injection:** tech/job creation is idempotent on
  `external_id`; re-posting a fixture cannot duplicate rows.

## Not in v1 (required for real deployment)

- Authentication/authorization on the web UI and API (anyone with the URL
  can currently seed, solve, and record overrides).
- Rate limiting on solve endpoints.
- Retention policy for dispatch history containing real customer
  addresses (v1 stores synthetic zones only).
- Counsel review for labor-law compliance of any schedule the system
  emits (see REQUIREMENTS.md).
