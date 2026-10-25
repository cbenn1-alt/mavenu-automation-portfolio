# S03 — Runbook

## Prerequisites

- Repo venv: `cd ~/workspace/mavenu-portfolio && .venv/bin/python`
- Python 3.12 stdlib only at runtime; SQLite; $0 spend; no network.

## 1. Run the S03 workflow end-to-end (API)

```bash
.venv/bin/python run.py &          # start the app (default :8080)
# 1. Intake a case
curl -s -X POST localhost:8080/api/forensics/cases \
  -H 'Content-Type: application/json' -d '{
    "title": "Suspicious file on WS-07 (synthetic)",
    "description": "Practice case.",
    "authorizer_name": "Practice Authorizer",
    "authorization_ref": "AUTH-2026-0142",
    "handling_plan": ["Intake", "Acquire read-only", "Examine", "Timeline", "Report"]
  }' | python3 -m json.tool
# 2. Guided demo instead (does 1–5 in one call on a fresh fixture):
curl -s -X POST localhost:8080/api/forensics/demo | python3 -m json.tool
```

## 2. Run the S03 workflow in Python

```python
import json, sys
sys.path.insert(0, "src")
from mavenu.db import get_connection, run_migrations
from mavenu import forensics as f

conn = get_connection("/tmp/demo-forensics.db")   # scratch DB
run_migrations(conn)

fx = f.generate_synthetic_case("/tmp/synth-case") # the "disk image"
case = f.open_case(conn, title="Suspicious installer (synthetic)",
    description="Practice.", authorizer_name="Practice Authorizer",
    authorization_ref="AUTH-2026-0142",
    handling_plan=["Intake", "Acquire", "Examine", "Timeline", "Report"])
acq = f.run_acquisition(conn, case["id"], fx["tree"])

meta = json.load(open(fx["meta_path"]))
f.extract_file_listing(conn, acq["id"], meta)
f.extract_log_events(conn, acq["id"], open(fx["tree"] + "/var/log/app.log").read())
f.carve_deleted(conn, acq["id"], open(fx["blob_path"], "rb").read(),
                json.load(open(fx["freelist_path"])))

timeline = f.record_timeline(conn, case["id"], f.events_from_fixture("/tmp/synth-case"))
truth = json.load(open(fx["ground_truth_path"]))["events"]
print(f.score_timeline(timeline, truth))           # expect 5/5, score 1.0

f.add_hypothesis(conn, case["id"],
    statement="The demo user executed the installer.",
    supporting=["var/log/app.log#L3"],
    contradicting=["none-found-after-review"])
rep = f.draft_report(conn, case["id"], [
    {"kind": "fact", "text": "installer_update.exe was downloaded at 2026-10-20T14:02:11Z.",
     "evidence": ["var/log/app.log#L2"]},
    {"kind": "inference", "text": "The demo user executed the installer.",
     "evidence": ["var/log/app.log#L3"], "confidence": "high"},
])
print(rep["text"][:400])
print(f.verify_chain(conn, case["id"]))            # expect ok: True
```

## 3. Verify integrity of an acquisition

```python
print(f.verify_acquisition(conn, acq["id"], fx["tree"]))  # ok: True
# After any change to the tree, mismatches/missing/extra are listed and ok is False.
```

## 4. Rollback procedure (migration down-step)

Rolling back `016_forensics.sql` **drops all S03 tables and their rows**
(cases, acquisitions, artifacts, timeline events, hypotheses, reports,
hash-chain entries). All rows are synthetic demo data, but the drop is
still destructive to anything stored — export first if you need it:

```python
from mavenu.db import get_connection, run_migrations, rollback_migration
conn = get_connection("data/mavenu.db")
run_migrations(conn)
ok = rollback_migration(conn, "016_forensics.sql")  # True when applied
# verify
tables = {r["name"] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
assert not any(t.startswith("forensics_") for t in tables)
# re-apply when ready
run_migrations(conn)  # 016_forensics.sql applies cleanly again
```

Rollback is exercised for real by
`tests/test_forensics.py::TestMigrationRollback::test_rollback_for_real`
(date + environment in TEST_RESULTS.md).

## 5. Tests

```bash
.venv/bin/python -m pytest tests/test_forensics.py tests/test_forensics_api.py -q
# Full suite (chunked — /tmp is a 512MB tmpfs; clear pytest debris between chunks):
rm -rf /tmp/pytest-of-root && .venv/bin/python -m pytest tests/ -q -x --ignore=tests/test_crypto.py -p no:cacheprovider
```

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ForensicsError: ... stage 'acquired'` on acquire | Case already acquired | Open a new case (re-acquisition is rejected by design) |
| `ForensicsError: ... stage 'intake'` on report | Timeline not built | Run `record_timeline` first (stage must be `analyzed`) |
| `verify_acquisition` ok=False after demo | Fixture tree changed or removed | Regenerate via `POST /api/forensics/demo`; verify only works against the original tree |
| 422 on hypothesis | Missing contradicting evidence | Add contradicting refs or documented `none-found-after-review` |
| 422 on report | Inference without confidence | Add `confidence: low\|medium\|high` to every inference |
