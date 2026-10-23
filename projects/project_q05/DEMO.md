# Q05 — Demo Script

Audience: a hiring manager or bank stakeholder. Everything is synthetic.
Talking points are honest — say what the system *does*, not what it
pretends to be.

## Setup (2 min)

```bash
cd mavenu-portfolio
python3 run.py --port 8123 --db /tmp/q05-demo.db
# open http://localhost:8123/project_q05
```

## Act 1 — Ingest (2 min)

Paste the invoice CSV, then the payment CSV from `TEST_PLAN.md` §1
(the 8-invoice / 11-payment hand-built fixture — keep it handy in a
scratch file).

Talking points:
- "Row-level validation: a bad row gets a row number and a reason; it
  never kills the batch."
- "Formula cells are neutralized on ingest — `=cmd|...` arrives as
  literal text. That's CSV injection, and the demo defends against it."
- "Re-ingest the same file: zero new rows. Natural keys are the
  idempotency story."

## Act 2 — Match (3 min)

Press **Run match**, then open `/project_q05/exceptions`.

Talking points:
- "Exact pass first: payment references that normalize to an invoice ID.
  Structural — it can't false-match by construction."
- "Fuzzy pass: amount, date window, ID overlap — each with a documented
  weight. Every match stores *why* it matched. That's the thesis:
  reconciliation you can audit."
- "Below the 0.75 threshold, the matcher refuses to guess — it routes to
  a human with the candidate score breakdown. Zero silent auto-matches."
- "One payment was a within-batch duplicate: it raised a visible
  exception and was NOT double-counted."

## Act 3 — Work an exception (2 min)

Open the `partial_payment` on INV-0003.

Talking points:
- "The queue proposes a next action: 'follow up on the $1,500.00
  balance' — it never posts anything itself."
- Move it `open → investigating → resolved`. Show the actor-stamped
  history.
- "Write-off is terminal and human-only. The system proposes; a person
  authorizes."

## Act 4 — Reports (2 min)

Open `/project_q05/reports`.

Talking points:
- "The reconciliation identity at the top: outstanding minus overpaid
  equals invoiced minus matched-paid. It's checked in tests against
  independent SQL — every total traces to source rows."
- "Aging buckets sum to the outstanding total. Exception aging shows
  what's sitting."

## Close (30 sec)

"Month-end was a spreadsheet and a prayer. This is a matcher that
explains every pairing, queues every exception with a next step, and
produces a reconciliation summary you can defend line by line. All
synthetic data — it's an engineering artifact, not accounting software."
