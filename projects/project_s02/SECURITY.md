# S02 — Security (lab-scope discipline)

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**

## 1. Lab-escape prevention

In S01, "escape" meant the design touching a real network. In S02 the bar
is even simpler: the lab cannot escape because it cannot reach anything.

1. **The simulator performs no I/O.** Verification reads a Python dict;
   remediation returns a transformed dict. There is no shell, no SSH
   client, no socket, no subprocess, and no package-manager code anywhere
   in `ossec.py` — verified by inspection (`grep -rn "socket\|subprocess\|
   paramiko\|os.system" src/mavenu/ossec.py` returns nothing).
2. **The "lab VMs" are fixtures, not machines.** `lab-vm-vulnerable` and
   `lab-vm-hardened` are dict literals describing an imaginary training
   image. No hypervisor, guest OS, or network traffic exists in S02.
3. **No credentials anywhere.** Password "strength" is a declared policy
   marker on synthetic data. The project never reads, stores, tests, or
   transmits real credentials, and never attempts authentication.
4. **The "attacker" is a configuration, not an actor.** Findings are
   detected by *reading configuration* (a weak marker, a running service,
   a file mode) — never by exercising the weakness. There is no exploit
   code, no exploitation workflow, and no zero-day material in this
   project, by design.
5. **Caller-supplied states are validated, not trusted.**
   `POST /api/ossec/evaluate` and `/api/ossec/remediate` schema-check the
   incoming state dict and return 422 on violations; evaluation is
   read-only against the submitted dict.

## 2. Scope boundary checklist (before any use)

- [ ] I am working with the simulated states in this project only.
- [ ] No real host, account, credential, or vulnerability is represented.
- [ ] I will not apply these techniques to any system I do not own or
      lack explicit, written authorization to assess.
- [ ] I understand this demonstrates defensive *method* (detect → fix →
      verify), not production hardening experience.
- [ ] No finding in this project transfers to a real system without
      authorization and change control.

## 3. Data handling

All S02 data is synthetic. The SQLite tables (`ossec_findings`,
`ossec_baseline_runs`, `ossec_baseline_results`) store invented finding
records and verification results — safe to seed, drop, and re-seed; the
down-migration exists for exactly that. No PII, no real hostnames, no real
addresses appear anywhere.
