# Mavenu Automation Portfolio

Production-style AI automation projects built by Mavenu Group. Each project is a
**working application with automated tests** — or it is labeled honestly as
planned. Nothing here is a mockup presented as software.

> **All data in this portfolio is synthetic.** Names, phone numbers, emails,
> and addresses are fictional fixtures for demonstration. No real personal
> data exists anywhere in this repository.

## Projects

| # | Project | Status |
|---|---------|--------|
| 01 | [AI Revenue Operations Engine](projects/project01/README.md) — lead intake, validation, qualification, routing, booking, human review | **Implemented + tested (Gate A ✓)** |
| 02 | [Enterprise Request & Approval Automation](projects/project02/README.md) — request intake, role-based multi-step approvals, SLA escalation, audit trail, ops dashboard | **Implemented + tested (Gate B ✓)** |
| 03 | AI Document Intelligence & Exception Management | Planned |
| 04 | SQL Operations Intelligence Platform | Planned |
| 05 | Automation Reliability & Governance Center | Planned |

## Quickstart (reviewer path, ~3 minutes)

```bash
cd mavenu-portfolio
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

# 1. Run the test suite (51 tests, all must pass)
.venv/bin/python -m pytest tests/ -q

# 2. Start the app (stdlib only — no other dependencies)
python3 run.py
# open http://localhost:8080/ → Project 01 → submit a lead → watch it move
# through received → qualified → routed → booked, or into human review.
```

See [projects/project01/DEMO.md](projects/project01/DEMO.md) for a guided
demonstration script, and [docs/evidence-matrix.md](docs/evidence-matrix.md)
for the honesty-graded capability map (Verified / Transferable / Not yet
demonstrated).

## Tech choices

- **Python 3.12 standard library only** for the application (`wsgiref`, `sqlite3`).
  Rationale: zero dependencies, zero cost, runs anywhere, nothing to audit.
- **SQLite** with version-controlled migrations (`src/mavenu/migrations/`).
- **pytest** (dev only, in `.venv`) for automated tests.
- Configuration via environment variables; `.env.example` documents them.
  No secrets exist in this project.

## Repository layout

```
run.py                      # entry point: python3 run.py [--port] [--db]
src/mavenu/
  config.py                 # env-var settings (no secrets in code)
  db.py                     # sqlite connections + migration runner
  migrations/               # versioned schema, applied in order
  events.py                 # structured audit log (DB rows + JSON stdout)
  validation.py             # server-side input validation
  workflow.py               # explicit state machines, transitions in code
  classifier.py             # AI classification interface + deterministic demo
  leads.py                  # Project 01 service layer
  web.py                    # WSGI app: pages + JSON API (stdlib only)
tests/                      # 51 automated tests
projects/project01/         # per-project docs (README … RUNBOOK, DEMO)
docs/evidence-matrix.md      # Verified / Transferable / Not-yet-demonstrated
```

## Truthfulness contract

- Statuses used across this repo: **implemented**, **tested**, **simulated**,
  **blocked**, **planned**. A feature is "tested" only when an automated test
  executes it and passes.
- The bundled classifier is a **deterministic rule-based demonstration** —
  it is not a trained ML model and is never described as one.
- The booking integration is a **labeled fake** (`FakeBookingAdapter`); its
  failure mode is real code and is tested.
- Test results are recorded in `projects/project01/TEST_RESULTS.md` from
  actual runs, never fabricated.
