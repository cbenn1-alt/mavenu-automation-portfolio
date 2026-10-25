# S02 — Architecture

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.**

## 1. Design: defense-documented-as-code

Like S01, S02 encodes a defensive workflow as executable code rather than
as prose checklists. The architecture has four layers:

```
 concepts/        Why the boundaries exist (explainer text, /project_s02/concepts)
     │  privilege rings · process isolation · authentication flows
     ▼
 baselines/       What "good" looks like, as code (15 items × check + fix)
     │  account_policy · authentication · service_minimization ·
     │  patch_cadence · file_permissions
     ▼
 lab/             Simulated states the baselines are evaluated against
     │  lab-vm-vulnerable (all fail) → remediation simulator →
     │  lab-vm-hardened (all pass)
     ▼
 findings/        Per-vulnerability-class record:
                  description → detection → remediation → verification
```

Verification reads a state dict. Remediation returns a *transformed copy*
of a state dict. Nothing performs I/O, so the lab cannot escape the
process — host-only by construction (see SECURITY.md).

## 2. Privilege-boundary explainers

### 2.1 Privilege rings: user mode vs kernel mode

Modern CPUs run code at numbered privilege levels ("rings"). In the
common two-ring model that matters to defenders:

- **Ring 0 (kernel mode).** The kernel owns memory management, device
  drivers, and scheduling. Code here can do anything — which is why almost
  nothing should run here.
- **Ring 3 (user mode).** Every normal process lives here. A user-mode
  process cannot touch hardware or another process's memory directly; it
  must ask the kernel through a **system call** — a narrow, checked gate
  between the rings.

The boundary is hardware-enforced, but *configuration* decides who gets to
stand on which side of it. A second uid-0 account (baseline acct-01) and
an unjustified setuid-root binary (perm-02) are configuration holes
punched through this boundary: ordinary-looking entries that grant
kernel-level-equivalent privilege.

### 2.2 Process isolation: separate address spaces, one shared kernel

Each process receives its own virtual address space — process A cannot read
process B's memory by default, enforced by hardware memory protection
under kernel management. Isolation degrades when:

1. **A process holds more privilege than its job needs.** Then a bug in
   that process becomes a bug in everything (least-privilege sudo —
   acct-04; minimized services — svc-01/svc-02).
2. **File permissions leak across the boundary.** A world-readable
   credential store hands secrets to any local account (perm-01).
3. **Binaries cross the boundary standing up.** A setuid-root binary
   executes with root's privilege no matter who invokes it — a permanent,
   standing crossing that must be individually justified (perm-02).

### 2.3 Authentication: claim, proof, and audit

A login is a *claim* ("I am trainee") plus *proof*. The lab policy the
baselines enforce:

1. **Proof by key, not password, over SSH** (auth-01). Password
   authentication over the network invites credential guessing at scale.
2. **No direct root login** (auth-02). Operators authenticate as
   themselves and elevate deliberately, so the audit trail names the
   operator who acted.
3. **Bounded guessing** (auth-03). Few attempts per connection, then
   disconnect — automated guessing gets expensive.
4. **Passwords that meet policy** (acct-02); **dormant accounts disabled**
   (acct-03). Forgotten accounts are forgotten attack surface.

## 3. The simulated state schema

A lab VM state is a plain dict (see `ossec.py` module docstring for the
full schema): OS/kernel versions, patch age and pending-update count,
accounts (uid, password-strength *marker*, locked, sudo, last login), SSH
settings, services (running, boot-enabled, version vs latest, needed
flag), and tracked files (mode vs expected mode, setuid bit,
justification flag).

Two fixtures derive everything:

- **lab-vm-vulnerable** — hand-built to fail all 15 baseline items and
  trigger all 6 findings.
- **lab-vm-hardened** — *derived, not hand-written*: the remediation
  simulator deep-copies the vulnerable state and applies every fix, so the
  hardened state is itself proof the fixes work and cannot drift from
  them.

## 4. Detection → remediation → verification

Each vulnerability class maps to the baseline items that detect it. A
finding is *detected* when any mapped item fails (configuration read, not
exploited). Remediation applies the mapped items' fixes to a state copy.
Verification re-runs the mapped items and requires all to pass. The
`before_after_report()` records per-finding detection/remediation
evidence and per-item before/after results — the "receipts" of the loop.

## 5. Persistence and web layer

- `014_ossec.sql`: `ossec_findings` (lifecycle
  `open→remediated→verified→closed`, transitions enforced in code),
  `ossec_baseline_runs` + `ossec_baseline_results` (per-item pass/fail with
  evidence strings).
- `web.py`: five `/project_s02*` pages (dashboard, concepts, lab, findings,
  baselines) and six `/api/ossec*` endpoints (baselines, findings,
  evaluate, remediate, coverage, seed). Caller-supplied states are
  schema-validated; violations return 422.

## 6. Rationale

Detection→remediation→verification is the employable loop this portfolio
demonstrates. Snapshots (immutable fixture in, derived fixture out) make
every experiment repeatable, and the coverage audit makes the checklist
self-policing: a baseline item without a verification function is a
structural failure, caught by test.
