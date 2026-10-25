# Q06 — Demo script (~5 minutes)

All data below is synthetic. The guided path uses the test fixture's
shape with a small hand-typed dataset so every number is reproducible by
hand.

## Setup

```bash
cd mavenu-portfolio
python3 run.py --port 8123 --db /tmp/q06-demo.db
# open http://localhost:8123/project_q06
```

## Act 1 — Three lists, one customer (2 min)

Ingest source 1 (`spreadsheet-customers`, kind `spreadsheet`):

```
name,phone,email,address,zip,notes
Marcus Bell,(701) 555-0100,marcus.bell@example.com,42 Prairie Lane,58102,
Jonathan Smith,(701) 555-0101,jonathan.smith@example.com,15 Oak Street,58103,
Emma Carter,(701) 555-0200,emma.carter@example.com,14 Rose Street,58102,
```

Ingest source 2 (`form-tool-signups`, kind `form`):

```
name,phone,email,address,zip,notes
  MARCUS  bell ,7015550100,Marcus.Bell@Example.com,42 prairie ln,58102,web form
Jonathon Smith,701-555-0101,jonathan.smith@example.com,15 Oak St,58103,web form
Emily Carter,(701) 555-0200,emily.carter@example.com,14 Rose Street,58102,web form
```

Press **"Normalize → block → score → propose"**.

Point at the snapshot: 6 contacts → 15 possible pairs, but only 3
candidate pairs were generated (blocking did its job). Bands: **2 match,
1 review, 0 no-match**.

## Act 2 — Read a score like an auditor (1 min)

Open `/project_q06/pairs` → the Marcus Bell pair (score 1.00, match).
Show the breakdown: name 0.45 (case/whitespace variants normalize away),
phone 0.25 (format variants → same digits), email 0.15, address 0.10
(`ln` → `Lane`), ZIP 0.05. Every component has a human-readable reason.

Then open the Emma/Emily Carter pair (score 0.75, **review**). Same phone,
same address — but the names differ, so it stays out of auto-merge
territory. *"The system is unsure, and it says so."*

## Act 3 — The human gate (2 min)

Open `/project_q06/merges`: two proposals, both `proposed`.

1. Open the Marcus Bell proposal. Read the field plan: per field, the
   winning value, which record it came from, and why.
2. Confirm it as `reviewer` with a note. Show the audit: merged by,
   timestamp, field provenance, and the full pre-merge images.
3. Now **reverse** it. Both records come back exactly; the audit row is
   stamped `reversed` — history kept, data restored.
4. Try confirming with actor `system` (via the API) — rejected:
   `confirming a merge requires a named human actor`. The pipeline cannot
   merge by itself, even above the threshold.

## Talking points

- **Blocking, not brute force:** 3 pairs from 15 possible — the reduction
  ratio is on the snapshot, not a claim.
- **Explainable scoring:** weights and thresholds are documented constants;
  the Jr/Sr-style suffix penalty (−0.20) is the adversarial guard — a
  father/son pair with otherwise identical records lands in review.
- **The merge is the dangerous operation, so it's the gated one:**
  proposals only, human confirmation, full pre-images, exact reversal.
- **Honest numbers:** recall 1.000 / precision 1.000 are measured on the
  54-contact fixture (TEST_RESULTS.md) — they describe the fixture, not
  production.

## Cleanup

```bash
rm /tmp/q06-demo.db*   # demo database only; nothing else is touched
```
