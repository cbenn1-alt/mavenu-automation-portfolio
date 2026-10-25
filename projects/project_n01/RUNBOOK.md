# N01 — Runbook

> ⚠ **LAWFUL LAB ONLY.** Every command below operates on synthetic,
> in-process-generated packets. There is no tap to start and no NIC to
> configure — if you are looking for capture hardware, you are in the
> wrong project.

## Operating the demo

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py          # start the app (WSGI, stdlib server)
# open /project_n01 — capture plan, "Run a capture" form (scenario + seed),
# then Sessions → Timeline → Anomalies → Scoping → Report
```

API (synthetic data only, bannered):

```bash
curl -s -X POST localhost:8080/api/netforensics/capture \
  -d '{"scenario":"port_scan","seed":20261023}'
# → {"capture_id":1,"anomalies":["port_scan"],"ground_truth_match":true,...}
curl -s "localhost:8080/api/netforensics/anomalies?capture_id=1"
curl -s "localhost:8080/api/netforensics/report?capture_id=1"
curl -s localhost:8080/api/netforensics/captures
```

Programmatic (tests, scripts):

```python
from mavenu import netforensics as nf
result = nf.run_full_pipeline("c2_beaconing", seed=20261023)
result["report"]["ground_truth_match"]   # True
[a["type"] for a in result["anomalies"]]  # ["beaconing"]
```

## Interpreting output

- **Sessions page:** bidirectional 5-tuple groups; `handshake=yes`
  means SYN→SYN-ACK→ACK in order. One-sided rows (probes) are normal —
  they are denied probes, not missing data.
- **Anomalies page:** shows the documented baseline table next to
  detections. `baseline_clean` correctly shows "No anomalies."
- **Report page:** facts first (observed), inferences second (each
  with confidence). `ground_truth_match: true` means the detected
  anomaly types exactly equal the scenario's scripted expectation.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `netforensics tables missing` on save | Migration not applied | `run_migrations(conn)` — the app applies all migrations at startup |
| `capture_ref … already exists` | Re-ran same scenario+seed via API | Expected: API auto-suffixes (`port_scan-20261023-2`); the form does the same |
| 404 on sub-pages/API | No captures saved yet | Run a scenario from `/project_n01` first |
| Beaconing not flagged | Custom seed with extreme jitter | Detection tolerates ±0.2 s; CV ≤ 0.15 is the documented limit |

## Rollback procedure (tested for real)

The N01 schema change is migration `018_netforensics.sql` with
down-step `018_netforensics.down.sql`.

**Rollback (code):**

```python
from mavenu.db import get_connection, rollback_migration
conn = get_connection(settings.db_path)
rollback_migration(conn, "018_netforensics.sql", MIGRATIONS_DIR)
conn.close()
```

This drops the five `netforensics_*` tables and removes the
`schema_migrations` record, so `run_migrations()` can re-apply the
up-step later. Rollback is destructive to N01 demo data by design (all
rows are synthetic) — see the down-step header comment.

**Rollback (web demo data):** there is no separate data rollback; N01
rows are synthetic demo data. To reset, roll back the migration (above)
and re-run a scenario.

**Config revert:** N01 has no config flags; removing the nav links and
route block in `web.py` disables the surface (module + tests remain).

**Verification after rollback:** `test_migration_rollback_for_real`
covers apply → use → roll back → tables absent → re-apply. Re-run it:

```bash
.venv/bin/pytest tests/test_netforensics.py::TestPersistence::test_migration_rollback_for_real -q
```
