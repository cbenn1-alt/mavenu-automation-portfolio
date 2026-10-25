# Q08 — Runbook

**Status:** Implemented · Tested (2026-10-23).

## Start the app

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py        # serves the WSGI app (default port 8080)
```

Open http://localhost:8080/project_q08 — the dashboard shows queue
counts, SLA status, and a CSV ingest form. Lexicons seed automatically
on startup (`ensure_lexicons`).

## Demo ingest

Paste into the dashboard's CSV box (columns
`external_id,stars,title,body,reviewed_at,author`):

```
external_id,stars,title,body,reviewed_at,author
demo-1,1,No-show,"They never showed up. Terrible.",2026-10-23T09:00:00Z,Sam Rivera
demo-2,5,Great job,"Excellent work, friendly crew.",2026-10-23T10:00:00Z,Alex Chen
```

Or via API:

```bash
curl -s -X POST localhost:8080/api/reviews/ingest \
  -H 'Content-Type: application/json' \
  -d '{"events":[{"source":"demo","external_id":"demo-1","stars":1,
        "title":"No-show","body":"They never showed up. Terrible.",
        "reviewed_at":"2026-10-23T09:00:00Z","author":"Sam Rivera"}]}'
```

## Operator workflow

1. **Triage** — `/project_q08/queues`: critical owner_alerts first
   (SLA 4h), then high (12h), then normal (24h). `human_review` entries
   need a person to read the review (uncertain tag).
2. **Draft a reply** — from `/project_q08/reviews`, pick a tone and click
   "Draft reply" on a queued review.
3. **Approve / reject** — `/project_q08/drafts`. Approval clears the
   draft for a human to copy and send manually. **Nothing is posted by
   this system.**
4. **SLA sweep** — overdue entries are marked `breached` by
   `check_sla()`; currently invoked programmatically (tests) — wire it to
   a scheduler/operator action in a real deployment.
5. **Resolve** — mark a queue entry resolved with your name once the
   review has been handled.

## Rollback procedure (tested)

If migration `011_reviews.sql` must be rolled back:

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection("<db path>")
rollback_migration(conn, "011_reviews.sql")  # True when applied
conn.close()
```

This drops all seven `review_*` tables and removes the migration record,
so `run_migrations()` can re-apply the up-step later. Verified by
`test_migration_011_down_step_rolls_back_for_real` (2026-10-23): data
ingested, tables dropped, other projects' tables intact, re-apply clean.

**Warning:** rollback deletes Q08 data (reviews, tags, queues, drafts,
escalations, events, lexicons). In this demo all of it is synthetic; in
any real deployment, export what you need first.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `database or disk is full` during tests | /tmp (512 MB tmpfs) filled with per-test DBs — `rm -rf /tmp/pytest-of-root` (recurring; see AGENTS.md). For the full suite, run in chunks clearing /tmp between, or set `TMPDIR` to a disk-backed dir |
| Re-ingest reports duplicates | Expected: `(source, external_id)` is the idempotency key |
| Review has no queue entry | Positive/confident-neutral reviews intentionally get none (`no_action` event) |
| Draft cannot be approved twice | By design — decided drafts are final; generate a new draft instead |
| 404 on `/api/reviews/lexicons/<v>` | Only seeded versions exist (v1.0); check `review_lexicons` |
