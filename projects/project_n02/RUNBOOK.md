# N02 — Runbook

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**

## 1. Start the app

```
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py        # serves the portfolio (stdlib wsgiref)
```

Open `/project_n02` — the workbook hub.

## 2. Seed the workbook

Web: press **Re-seed synthetic workbook** on `/project_n02`, or
`POST /project_n02/seed`.

API: `POST /api/risk/seed` → `{"seeded": {"assets": 14, "threats": 10,
"risks": 17, "remediations": 8, "snapshots": 2}}`.

Seeding is idempotent: re-running clears N02 rows and inserts the
identical deterministic fixture (verified by test).

Programmatic:

```python
from mavenu.db import get_connection, run_migrations
from mavenu import risk
conn = get_connection("path/to/app.db")
run_migrations(conn)          # applies 019_risk.sql once
risk.seed_demo(conn)
```

## 3. Verify the workbook

- `/project_n02/scales` — scales, bands, prioritization rule.
- `/project_n02/register` — 17 risks; band counts 2 critical / 8 high /
  6 medium / 1 low; GAP rows show their accepted-gap reasons.
- `/project_n02/remediation` — plan order RM-05 → … → RM-04 with ratios.
- `/project_n02/residual` — memo: 177 → 79, per-risk deltas.
- `GET /api/risk/register` — `"audit_violations": []` means the
  high/critical control mapping is complete.

## 4. Run the tests

```
cd ~/workspace/mavenu-portfolio
.venv/bin/python -m pytest tests/test_risk.py tests/test_risk_api.py -q
```

Expected: 67 passed.

## 5. Rollback procedure (DB migration)

The N02 schema is migration `019_risk.sql`; the down-step is
`019_risk.down.sql`. To roll back:

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection("path/to/app.db")
rollback_migration(conn, "019_risk.sql")   # drops all 6 N02 tables,
                                           # removes the migration record
```

Then `run_migrations(conn)` re-applies the up-step cleanly. Rollback was
tested for real (see TEST_RESULTS.md): tables dropped, other projects'
tables untouched, re-apply + re-seed verified.

**Code rollback:** the N02 code is additive (`src/mavenu/risk.py`,
migration files, web.py N02 block, two test files, `projects/project_n02/`).
Reverting the N02 commit restores the pre-N02 state; no other project
imports `mavenu.risk`.

## 6. Troubleshooting

- **Pages show "No workbook seeded yet"** → seed first (§2).
- **API 404 on `/api/risk/*`** → same; only `/api/risk/scales` and
  `/api/risk/controls` work unseeded.
- **`RiskError: unknown control reference`** at seed → an S01/S02
  control id changed; update the fixture ref in `risk.py`
  `REGISTER_FIXTURE` (the loud failure is by design).
- **`/tmp` full during full-suite runs** → run in chunks and
  `rm -rf /tmp/pytest-of-root` between chunks; never use a disk-backed
  TMPDIR.
