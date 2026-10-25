# Q06 — Runbook

## Start the app

```bash
cd mavenu-portfolio
python3 run.py                                   # http://localhost:8080/
python3 run.py --port 8123 --db /tmp/q06.db     # custom port / database
```

Migration 009 applies automatically on startup.

## Run the tests

```bash
.venv/bin/python -m pytest tests/test_entity_resolution.py tests/test_entity_resolution_api.py -q  # expect: 134 passed
.venv/bin/python -m pytest tests/ -q                                                                  # expect: 827 passed
```

## Operate the demo

1. **Ingest:** open `/project_q06` — label a source (`spreadsheet-…`,
   `form-…`, `phone-…`), pick its kind, paste a CSV with columns
   `name,phone,email,address,zip,notes`, submit. Example:
   ```
   name,phone,email,address,zip,notes
   Marcus Bell,(701) 555-0100,marcus.bell@example.com,42 Prairie Lane,58102,
   marcus bell,7015550100,Marcus.Bell@Example.com,42 prairie ln,58102,form signup
   ```
   The result reports inserted / skipped-idempotent / sanitized /
   row-error counts. Re-ingesting the same CSV inserts nothing.
2. **Run the pipeline:** press "Normalize → block → score → propose"
   (or `POST /api/entity-resolution/run`). The snapshot shows blocks,
   candidate pairs vs. all possible pairs (the O(n²) reduction), and band
   counts.
3. **Review pairs:** `/project_q06/pairs` — filter by
   `match` / `review` / `no_match`. Open a pair to see the score breakdown
   (per-component weights and reasons) and both contacts side by side.
4. **Work the merge queue:** `/project_q06/merges` — open a proposal,
   read the field plan (which record each winning value came from and
   why), then **Confirm** or **Reject** as a named human. Confirming
   writes the full before-image audit row. A confirmed merge can be
   **Reversed**, restoring both records exactly; the audit row is kept
   and stamped, never deleted.
5. **Review-band pairs:** open the pair → "Propose a merge" (human
   decision, named actor required) → confirm on the proposal page.
   No-match pairs can never be proposed — the code rejects it.
6. **API:** `POST /api/entity-resolution/sources/upload`
   (`{"label","source_kind","csv","actor"}`),
   `POST /api/entity-resolution/run`,
   `GET /api/entity-resolution/stats`,
   `GET /api/entity-resolution/pairs?band=match`,
   `GET /api/entity-resolution/pairs/<id>`,
   `GET /api/entity-resolution/proposals?state=proposed`,
   `POST /api/entity-resolution/proposals` (`{"pair_id","actor","note"}`),
   `GET /api/entity-resolution/proposals/<id>`,
   `POST /api/entity-resolution/proposals/<id>/confirm|reject`
   (`{"actor","note"}`),
   `POST /api/entity-resolution/proposals/<id>/reverse` (`{"actor"}`),
   `GET /api/entity-resolution/proposals/<id>/audit`.
7. **Logs:** structured JSON lines on stdout (`entity_resolution.*`
   events); every consequential action is also an append-only row in
   `er_events`.

## Re-running the pipeline

Safe and idempotent: re-running `POST /api/entity-resolution/run` with
no new data produces **zero new pairs, zero new scores, zero new
proposals** (tested). Blocks are rebuilt from active contacts; merged-away
records leave the candidate space. Human-touched proposals are never
rebuilt or re-scored.

## Threshold tuning

Thresholds live in `src/mavenu/entity_resolution.py`:
`MATCH_THRESHOLD = 0.85`, `REVIEW_THRESHOLD = 0.60`, weights in `WEIGHTS`,
suffix penalty `SUFFIX_CONFLICT_PENALTY = 0.20`. Changing them changes
banding only — the merge gate (human confirmation) is independent of
thresholds by design. Re-run the pipeline after a change; pairs are
re-scored only if you clear `er_pairs` first (scores are sticky for
idempotency — see "Resetting" below).

## Resetting Q06 data (demo databases only)

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from mavenu.db import get_connection, run_migrations
conn = get_connection("/tmp/q06.db")
conn.execute("DELETE FROM er_merge_audit"); conn.execute("DELETE FROM er_merge_proposals")
conn.execute("DELETE FROM er_pairs"); conn.execute("DELETE FROM er_blocks")
conn.execute("DELETE FROM er_contacts"); conn.execute("DELETE FROM er_sources")
conn.execute("DELETE FROM er_events"); conn.execute("DELETE FROM er_runs")
conn.commit()
print("Q06 data cleared; schema kept")
EOF
```

## Rollback procedure (migration 009)

If the Q06 schema must be removed (bad deploy, schema rework):

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from mavenu.db import get_connection, rollback_migration
conn = get_connection("/path/to/mavenu.db")   # the affected database
print(rollback_migration(conn, "009_entity_resolution.sql"))  # True when rolled back
EOF
```

This drops all eight `er_*` tables and removes the migration record, so
`run_migrations()` can re-apply the up-step later. It does **not** touch
any other project's tables (verified in
`test_migration_009_down_step_rolls_back_for_real`).

**Do not roll back a database whose Q06 proposals/audit rows you still
need** — the rollback is destructive to Q06 data by design. Export what
you need first (`GET /api/entity-resolution/proposals`,
`GET /api/entity-resolution/proposals/<id>/audit`).

## Incident notes

- **A merge was confirmed in error:** open the proposal →
  **Reverse merge** as a named human. Both records are restored to their
  exact pre-merge images; verify with the audit view's before/after
  images. The audit row is stamped, never deleted.
- **A proposal was confirmed for the wrong pair:** reject is only for
  `proposed`; once confirmed, use reverse.
- **Scores look wrong after a threshold change:** scores are sticky per
  pair for idempotency. Clear `er_pairs` (see "Resetting") and re-run.
