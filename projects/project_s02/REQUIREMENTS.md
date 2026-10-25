# S02 — Requirements

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**

## Problem statement

Most compromises exploit the same basics: excessive privilege, unpatched
services, weak authentication. Understanding *where the boundaries are* is
prerequisite to defending them. Aspiring security practitioners and IT
staff responsible for workstation/server baselines need a practiced,
repeatable detection → remediation → verification loop.

## Functional requirements

1. **Privilege-model coverage.** The project must explain and check
   user/kernel separation: single uid-0 account (acct-01),
   least-privilege sudo (acct-04), and the setuid boundary (perm-02).
2. **Process-isolation coverage.** Concepts must explain separate address
   spaces and how they break down; baselines must check the service
   surface that shares the machine (svc-01, svc-02).
3. **Authentication mechanisms.** SSH policy (password auth off — auth-01,
   no direct root login — auth-02, attempt limit — auth-03) plus account
   hygiene (no weak passwords — acct-02, no stale accounts — acct-03).
4. **Patch-management workflow.** Patch cadence policy (pat-01), zero
   pending security updates (pat-02), running kernel current (pat-03),
   running services at latest version (svc-03).
5. **Vulnerability classes (≥5).** Each class record must carry:
   description → detection method → remediation → verification evidence.
   Implemented: weak credentials, excessive privilege, SSH
   misconfiguration, unnecessary services, unpatched software, unjustified
   setuid binaries (6).
6. **Simulated lab only.** The "lab VM" is a simulated system-state
   snapshot (defined schema, synthetic fixtures). No code in S02 may open
   a shell, SSH session, socket, or subprocess, or read a real system's
   configuration.
7. **Defensive only.** Document detection and fix. No exploit development,
   no exploitation workflow, no zero-day claims.

## Measurable criteria

| # | Criterion | How verified |
|---|---|---|
| M1 | 100% of findings carry detection + remediation + verification evidence | `test_100_percent_carry_detection_remediation_verification` (structural assert over all 6 records) |
| M2 | Every baseline item FAILS on the vulnerable fixture and PASSES on the hardened fixture | 15 parametrized `test_item_fails_vulnerable_passes_hardened` |
| M3 | Remediation simulator: apply fix → re-verify → pass, with before/after evidence recorded | `test_remediate_finding_verifies` (×6) + `test_before_after_report_full` |
| M4 | Checklist coverage audit: every baseline item has a verification function and remediation | `test_full_coverage` (`coverage_audit() == []`); also live at `GET /api/ossec/coverage` |
| M5 | Tampered state is caught by re-verification | 4 adversarial tests (re-enabled service, reopened SSH password auth, restored setuid, stale updates) |
| M6 | Hardening checklist achieves a documented pass rate on lab states | Vulnerable 0/15 (0%), hardened 15/15 (100%) — recorded in TEST_RESULTS.md |
| M7 | Zero lab-scope violations | Design: simulator performs no I/O; no socket/SSH/subprocess code in `ossec.py` (verified by inspection) |
| M8 | Rollback works for real | `test_migration_rollback_for_real` (drop tables → migration record gone → re-apply clean) |

## Non-requirements (explicitly out of scope)

- Building or operating real VMs; assessing real systems.
- Exploit code, proof-of-concept exploits, or bypass techniques.
- Real credential handling of any kind (no password storage, cracking, or
  authentication attempts).
- Production hardening engagements or compliance certifications.
