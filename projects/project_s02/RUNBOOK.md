# S02 — Runbook

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**

## 1. The defensive loop (operator procedure)

For each vulnerability class, in order:

1. **Detect.** Evaluate the simulated state: `verify_baseline(state)` or
   `detect_finding(state, finding_id)`. Record the detection evidence —
   *why* the finding is believed present.
2. **Remediate.** Apply the finding's fix via the simulator:
   `remediate_finding(state, finding_id)` returns a new state plus
   per-step remediation evidence. The original state is never mutated.
3. **Verify.** Re-run verification on the new state; require every mapped
   baseline item to pass. Record the verification evidence.
4. **Record.** Persist the finding lifecycle in SQLite: `record_finding`
   (`open`) → `transition_finding` (`remediated`) → (`verified`) →
   (`closed`). Illegal transitions are rejected in code.

The full loop in one call: `before_after_report(state)` produces the
before/after proof-of-fix record (0/15 → 15/15 on the lab fixtures).

## 2. Patch-management workflow (the lab cadence)

The baselines encode the cadence; the operator's job is the rhythm:

1. **Inventory** — list running services and versions (svc-03 detects
   drift), pending updates (pat-02), and patch age (pat-01).
2. **Maintenance window** — apply updates; reboot so the *running* kernel
   matches the latest installed (pat-03 catches the "patched but not
   rebooted" miss).
3. **Verify** — re-run the patch_cadence items; all must pass before the
   window closes.
4. **Minimize** — while there, confirm no unneeded service crept back in
   (svc-01/svc-02) — reboots re-enable things.

## 3. Rollback procedure

### 3.1 Database rollback (tested for real)

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from mavenu.config import Settings
from mavenu.db import get_connection, rollback_migration

settings = Settings()  # uses the configured db_path
conn = get_connection(settings.db_path)
rollback_migration(conn, "014_ossec.sql")  # drops ossec_* tables, removes
                                           # the schema_migrations record
conn.close()
EOF
```

Re-apply with `run_migrations(conn)` — the up-step is idempotent and was
verified to re-apply cleanly after rollback (see TEST_RESULTS.md M8).

**Blast radius:** drops `ossec_findings`, `ossec_baseline_runs`, and
`ossec_baseline_results` — all synthetic demo data. No other project's
tables are touched.

### 3.2 Config/state revert

Baseline definitions and finding records are versioned in code
(`src/mavenu/ossec.py`), not in the database. Reverting a bad baseline
change = checking out the previous commit of `ossec.py` and re-running
the suite. Baseline runs stored in the DB are historical evidence of what
was evaluated when — they are never mutated in place.

### 3.3 Web/API revert

S02's web surface is additive routes in `web.py` plus the `ossec` module.
Disabling S02 = removing the `/project_s02*` and `/api/ossec*` dispatch
entries; no other project shares those paths.

## 4. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `evaluate` returns 422 | State dict missing a top-level key | Check `validate_state()` output; the schema is in the `ossec.py` docstring |
| Hardened fixture not 15/15 | A `fix()` was edited without re-running | `hardened_state()` derives from the simulator — rerun the suite |
| Coverage endpoint shows gaps | A baseline item lost its `check`/`fix` | Restore the callable; `coverage_audit()` names the item |
| Seed counts are 0 | Already seeded (idempotent) | Expected on re-seed; drop tables via rollback to start over |
