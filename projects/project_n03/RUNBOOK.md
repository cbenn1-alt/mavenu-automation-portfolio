# N03 — Runbook

> **⚠ SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, NOT CASEWORK.**
> This framework refers; it does not pursue. In a real emergency call
> 911. Suspected child sexual exploitation: NCMEC CyberTipline.

## Prerequisites

- Repo venv: `cd ~/workspace/mavenu-portfolio && .venv/bin/python`
- Python 3.12 stdlib only at runtime; SQLite; $0 spend; no network.

## 1. Run the N03 workflow end-to-end (API)

```bash
.venv/bin/python run.py &          # start the app (default :8080)
# 1. Intake a synthetic case (immediate_danger routes to emergency guidance first)
curl -s -X POST localhost:8080/api/safeguard/cases \
  -H 'Content-Type: application/json' -d '{
    "case_ref": "SYN-DEMO-01",
    "category": "cyberharassment",
    "reporter_role": "synthetic practice reporter",
    "summary": "SYNTHETIC SCENARIO. Repeated hostile messages to a public post."
  }' | python3 -m json.tool
# 2. Guided demo instead (does the full preserve → report → refer loop):
curl -s -X POST localhost:8080/api/safeguard/demo | python3 -m json.tool
```

## 2. Run the N03 workflow in Python

```python
import sys
sys.path.insert(0, "src")
from mavenu.db import get_connection, run_migrations
from mavenu import safeguard as sg

conn = get_connection("/tmp/demo-safeguard.db")  # scratch DB
run_migrations(conn)

case = sg.intake_case(conn, case_ref="SYN-RB-01", category="sextortion",
    reporter_role="synthetic practice reporter",
    summary="SYNTHETIC SCENARIO. Threatening messages demanding payment.")
print(case["safety_status"], case["guidance"][0][:60])

for item in sg.get_checklist(conn, case["id"]):
    if item["action"] == "refer":
        continue
    sg.complete_checklist_item(conn, case["id"], item["step_id"],
                               note="synthetic exercise")
ref = sg.generate_referral(conn, case["id"], "fbi_ic3",
                           note="synthetic exercise")
print(ref["org_name"])
sg.add_finding(conn, case["id"], "The sender's real-world identity.",
               claim_type="inference", status="unknown", confidence="low")
print(sg.close_case(conn, case["id"])["stage"])   # expect "closed"
```

## 3. Work a CSAM-category case (refer immediately, do not investigate)

```python
case = sg.intake_case(conn, case_ref="SYN-RB-02",
    category="child_sexual_exploitation",
    reporter_role="synthetic practice reporter",
    summary="SYNTHETIC SCENARIO. Concerning messages to a child observed.",
    involves_minor=True)
# NCMEC referral already exists — created at intake:
print([r["org_key"] for r in sg.list_referrals(conn, case["id"])])
# → ['ncmec_cybertipline']
```

## 4. Rollback procedure (migration down-step)

Rolling back `020_safeguard.sql` **drops all N03 tables and their rows**
(cases, checklist states, referrals, findings). All rows are synthetic
demo data, but the drop is still destructive to anything stored —
export first if you need it:

```python
from mavenu.db import get_connection, run_migrations, rollback_migration
conn = get_connection("data/mavenu.db")
run_migrations(conn)
ok = rollback_migration(conn, "020_safeguard.sql")  # True when applied
# verify
tables = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
assert not any(t.startswith("safeguard_") for t in tables)
# re-apply when ready
run_migrations(conn)  # 020_safeguard.sql applies cleanly again
```

Rollback is exercised for real by
`tests/test_safeguard.py::TestMigrationRollback::test_rollback_for_real`
(date + environment in TEST_RESULTS.md).

## 5. Tests

```bash
.venv/bin/python -m pytest tests/test_safeguard.py tests/test_safeguard_api.py -q -p no:cacheprovider
# Full suite (chunked — /tmp is a 512MB tmpfs; clear pytest debris between chunks):
rm -rf /tmp/pytest-of-root && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider
```

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SafeguardError: Unknown action` | Out-of-vocabulary action attempted | Use only the 6 vocabulary actions; there is no investigate/contact action by design |
| `ValidationError` on intake summary | Graphic term detected | Rewrite the summary non-graphically |
| `SafeguardError: Cannot close case` | Pending checklist items | Complete or skip (with reason) every step |
| `ValidationError: 'verified' findings must cite evidence` | Attribution discipline | Cite `evidence_ref`, or use `lead`/`unknown` |
| 404 on `/project_n03/playbooks/<category>` | Unknown category key | Use one of the 8 keys listed at `/api/safeguard/playbooks` |
