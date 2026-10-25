# S02 — OS Architecture & Vulnerabilities: Privilege Boundaries & Hardening

**Status: Implemented · Tested** — 70 automated tests, all passing.

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.** Everything in this project evaluates
> *simulated* system-state snapshots (Python dicts). No live VM, no real
> host, no real account was assessed.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Hardening baselines as structured data: 15 items across 5 categories (account policy, authentication, service minimization, patch cadence, file permissions), each with a verification function and a simulated remediation (`src/mavenu/ossec.py`); 6 vulnerability-class records (weak credentials, excessive privilege, SSH misconfiguration, unnecessary services, unpatched software, unjustified setuid) as description → detection → remediation → verification; a remediation simulator that deep-copies a vulnerable state, applies fixes, and re-verifies (before/after evidence recorded); SQLite persistence (`ossec_findings`, `ossec_baseline_runs`, `ossec_baseline_results`); migration `014_ossec.sql` + down-step, rollback tested for real; web pages (`/project_s02*`) and JSON API (`/api/ossec*`) |
| What is SIMULATED | **Simulated** | The "lab VM" is a simulated system-state snapshot — a Python dict fixture describing a training image's configuration. Verification reads the dict; remediation returns a transformed dict. No hypervisor, no guest OS, no SSH, no package manager, no shell access anywhere in S02 |
| What is SYNTHETIC | **Synthetic** | Every account, service, file mode, kernel version, password-strength marker, finding, and baseline run is invented. No real people, hosts, credentials, or vulnerabilities |
| What is NOT claimed | — | No production systems assessed. No real VMs built or hardened. No exploit development — detection and fix only. No zero-day material. Findings do **not** transfer to real systems without authorization and change control |

## Business problem

Most compromises exploit the basics: excessive privilege, unpatched
services, weak authentication. IT staff responsible for workstation and
server baselines need a repeatable loop — *detect the weakness, apply the
fix, prove the fix* — and they need to understand *where the boundaries
are* (user/kernel separation, process isolation, authentication) before
they can defend them. This project makes that loop executable on
simulated training states, so the method is practiced before it ever
touches a real machine.

## Implemented capabilities

- **Baselines as code** (`src/mavenu/ossec.py`): 15 baseline items, each a
  record with `id`, `category`, `title`, `description`, `expected`,
  `remediation`, a verification function `check(state) -> (passed,
  evidence)`, and a simulated fix `fix(state) -> [evidence]`.
- **Vulnerability-class records**: 6 classes, each with description,
  detection method, remediation, verification method, and mapped baseline
  items. 100% carry all three (asserted structurally by test).
- **Remediation simulator**: `before_after_report(state, finding_ids)` —
  verify before, apply each finding's fixes to a deep copy, verify after;
  per-finding detection/remediation evidence plus per-item before/after
  pass-fail and evidence strings.
- **Coverage audit**: `coverage_audit()` returns gaps; empty means every
  baseline item has a verification function and a remediation (asserted in
  tests and exposed at `GET /api/ossec/coverage`).
- **Persistence + rollback**: migration `014_ossec.sql` with findings
  lifecycle (`open→remediated→verified→closed`, illegal transitions
  rejected) and baseline-run history; `014_ossec.down.sql` drops all S02
  tables — rollback tested for real (drop → re-apply clean).
- **Web UI + API**: `/project_s02` dashboard, `/concepts` (privilege
  rings, process isolation, auth flows), `/lab` (inventory, snapshot
  discipline, host-only proof), `/findings`, `/baselines` (pass/fail
  tables for both fixtures); `POST /api/ossec/evaluate` and
  `POST /api/ossec/remediate` accept a caller-supplied state dict
  (schema-validated, 422 on violations).

## Key results (measured, 2026-10-23)

- Vulnerable fixture: **0/15** baseline items pass; all 6 findings detect.
- Hardened fixture (simulator output): **15/15** pass; 0 findings detect.
- Full remediation run fixes **15/15** items with before/after evidence.
- Adversarial tampering (re-enabled service, re-opened SSH password auth,
  restored setuid bit, stale updates) is caught by re-verification.
- Full suite: see TEST_RESULTS.md — zero regressions.

## Repository map

- `src/mavenu/ossec.py` — baselines, findings, simulator, fixtures, DB
- `src/mavenu/migrations/014_ossec.sql` / `.down.sql` — schema + rollback
- `tests/test_ossec.py` (53) · `tests/test_ossec_api.py` (17)
- `projects/project_s02/` — this documentation set
- Web: `src/mavenu/web.py` (`/project_s02*`, `/api/ossec*`)

## Limitations

- Simulated states only — the simulator proves the *baseline logic*, not a
  physical hardening engagement.
- Password "strength" is a declared policy marker on synthetic data; the
  project never reads, stores, or tests real credentials.
- No exploit code exists and none is planned; this is a defensive
  portfolio by design.
