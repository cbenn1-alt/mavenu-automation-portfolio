# S02 — Demo Walkthrough

> **⚠ CONTROLLED LAB ONLY — the techniques documented here must never be
> applied to systems you do not own or do not have explicit, written
> authorization to assess.** This demo evaluates *simulated* states. No
> live system is involved at any step.

## What you will see

The detection → remediation → verification loop, executed against two
simulated training-VM states, in about two minutes.

## Steps

### 1. Start the app

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py
```

### 2. Open the S02 dashboard

Visit `/project_s02`. You will see: the lab banner, the six
vulnerability classes and fifteen baseline items, and the headline
numbers — the vulnerable fixture passes **0/15**, the hardened fixture
passes **15/15**.

### 3. Read the concepts (`/project_s02/concepts`)

Privilege rings (user mode vs kernel mode), process isolation (separate
address spaces, how they break down), and the authentication flow (claim,
proof, audit). These explain *why* each baseline item exists.

### 4. Inspect the lab (`/project_s02/lab`)

The inventory table shows the two simulated states and the snapshot
discipline: Snapshot A (vulnerable) is immutable; Snapshot B (hardened) is
*derived* by the simulator, never hand-written. Read the host-only proof
and the scope boundary checklist.

### 5. Walk a finding (`/project_s02/findings`)

Pick **Weak credentials**. The card shows: what it is, how it is detected
(enumerate active accounts; flag weak password markers), the live
detection result on the vulnerable fixture (**DETECTED**, with evidence
naming the accounts), the remediation, and the verification method
(re-run acct-02 and acct-03; both must pass).

### 6. Watch the proof of fix (`/project_s02/baselines`)

Two pass/fail tables: the vulnerable fixture (all FAIL, each with an
evidence string) and the hardened fixture (all PASS). Below them, the
before/after summary: applying all six finding remediations fixes
**15/15** items.

### 7. Try the API

```bash
# Evaluate the vulnerable fixture (0/15 expected)
curl -s -X POST localhost:8080/api/ossec/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"state": <vulnerable-state-json>}' | python3 -m json.tool

# Full remediation report: before/after evidence per item
curl -s -X POST localhost:8080/api/ossec/remediate \
  -H 'Content-Type: application/json' \
  -d '{"state": <vulnerable-state-json>}' | python3 -m json.tool

# Coverage audit: every baseline item has a verification function
curl -s localhost:8080/api/ossec/coverage
```

(Generate the state JSON with
`.venv/bin/python -c "import sys,json; sys.path.insert(0,'src');
from mavenu import ossec; print(json.dumps(ossec.vulnerable_state()))"`.)

### 8. Seed stored demo data

`POST /project_s02/seed` (or `/api/ossec/seed`) stores one finding row per
vulnerability class plus baseline runs for both fixtures — then revisit
`/project_s02` to see the stored counts.

## Talking points (for the walkthrough)

- "Everyone says least privilege — here is where the lines are drawn, as
  executable checks."
- "The hardened state is not a second fixture I wrote; it is the output
  of the remediation simulator. The fix *is* the proof."
- "Tamper with the hardened state — re-enable a service, reopen password
  auth — and verification catches it. That is the point of re-running."
- "Everything is synthetic. The method transfers; the data does not."
