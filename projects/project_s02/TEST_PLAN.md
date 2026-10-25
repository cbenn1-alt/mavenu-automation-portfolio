# S02 — Test Plan

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**

## 1. Unit tests (`tests/test_ossec.py`, 53 tests)

| Area | Tests | What they prove |
|---|---|---|
| State schema | 3 | `validate_state` accepts the fixture shape; flags missing keys and non-dict input |
| Baseline verification | 17 | **Every one of the 15 items fails on the vulnerable fixture and passes on the hardened fixture** (15 parametrized), with non-empty evidence strings both ways; verification is pure (does not mutate its input) |
| Coverage audit | 4 | `coverage_audit() == []` (every item has a verification function + remediation), unique ids, known categories |
| Findings | 9 | All 6 classes detect on the vulnerable fixture with evidence; none detect on the hardened fixture; **structural assert: 100% of records carry description + detection + remediation + verification** with valid baseline mappings; unknown ids raise |
| Remediation simulator | 9 | Each finding's remediation verifies (all mapped items pass, input untouched); full before/after report: 0/15 → 15/15 with per-item evidence; partial remediation only fixes its category; unknown ids rejected |
| Adversarial | 5 | Tampered hardened state is caught: re-enabled service → svc-01 fails; reopened SSH password auth → auth-01 fails; restored setuid → perm-02 fails; stale updates → pat-01/pat-02 fail |
| Summary math | 1 | Pass/fail counts and pass rate |
| Persistence + rollback | 5 | Finding lifecycle + illegal transitions rejected; baseline run round-trip; seed idempotency; **migration rollback for real**: tables dropped, migration record removed, re-apply clean |

## 2. Web/API tests (`tests/test_ossec_api.py`, 17 tests)

Pages return 200 and carry the authorization warning (`/project_s02`,
`/concepts`, `/lab`, `/findings`, `/baselines`, seed form). API:
baselines catalog (15 items, zero coverage gaps), findings catalog (6,
all detect on the vulnerable fixture), coverage endpoint, `evaluate`
(0/15 vulnerable, 15/15 hardened; 422 on bad schema), `remediate`
(0→15 full report; 422 on unknown finding), `seed` (6 findings + 2 runs).

## 3. Adversarial method

Tampering tests mutate a *copy* of the hardened fixture in exactly one
dimension (one service re-enabled, one SSH flag reopened, one setuid bit
restored, patch counters aged) and assert the corresponding baseline item
fails with evidence naming the cause. This proves verification is
sensitive, not just present.

## 4. Rollback test method

`test_migration_rollback_for_real`: apply migrations → confirm S02 tables
exist → insert a finding and a baseline run → `rollback_migration(conn,
"014_ossec.sql")` → assert all three S02 tables are gone and the
`schema_migrations` record is removed → `run_migrations()` re-applies
`014_ossec.sql` cleanly. Recorded in TEST_RESULTS.md with date and
environment.

## 5. Full-suite regression

The full suite (all projects) is run at the end in chunks, clearing
`/tmp/pytest-of-root` between chunks because the 512 MB `/tmp` tmpfs
fills during a single full run. No disk-backed TMPDIR is used. Target:
1054 prior + 70 new = 1124 passed, 0 failed.
