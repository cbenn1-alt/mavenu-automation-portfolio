# N02 — Demo Script

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**
> Say this out loud before showing anything: every number on screen is
> synthetic, from a company that does not exist. This is a scoring
> *method* demonstration, not an assessment.

**Status vocabulary:** the workbook engine is Implemented+Tested; the
company, assets, threats, ratings, costs, and efforts are Synthetic
fixtures; the seeded workbook view is a deterministic Demo.

## Script (5 minutes)

1. **Hub** — `/project_n02`. Seed the workbook. Point out the honest
   banner and the band counts: 2 critical, 8 high, 6 medium, 1 low —
   all from a fictional 24-person home-services company.
2. **Scales** — `/project_n02/scales`. Read one likelihood level and one
   impact level aloud: every level has a written rationale. Show the
   band thresholds and the scoring rule `score = likelihood × max(C,I,A)`.
3. **Register** — `/project_n02/register`. Open R-01 (phishing → customer
   PII, 4×4=16, critical): likelihood rationale cites L4, impact
   rationale cites the C4/I3/A1 max. Open R-08 (lost tablet, 16,
   critical): the control column shows an explicit **accepted gap** with
   its reason — gaps are recorded, not hidden.
4. **Control mapping** — `GET /api/risk/controls`: 37 live references
   built from the S01/S02 modules. Rename a firewall rule in `firewall.py`
   and re-seed: it fails loudly instead of mapping to a stale copy
   (don't do this in the demo DB — describe it).
5. **Remediation plan** — `/project_n02/remediation`. The order is
   computed, not hand-sorted: RM-05 first (ratio 19/12), RM-04 last
   (9/20). Every cost/effort is labeled "synthetic estimate".
6. **Residual memo** — `/project_n02/residual`. After the full plan:
   177 → 79, zero critical/high remain, and R-13/R-17 keep their
   inherent scores because nothing covers them — residual risk is never
   zero. Close by re-reading the banner: illustrative scores, never an
   audit opinion.

## API walkthrough (curl against the local app)

```
POST /api/risk/seed
GET  /api/risk/scales        # documented scales + bands + rule
GET  /api/risk/register      # 17 risks, audit_violations: []
GET  /api/risk/remediations  # prioritized plan, synthetic bases
GET  /api/risk/residual      # memo + deltas + reconciled totals
```

## What NOT to say in the demo

- Never "we assessed…", "our audit found…", or "this company scored…".
- Never imply the method is a certification or that the fixture numbers
  apply to any real business.
- Correct phrasing: "the *engine* computes…", "the *fixture* shows…",
  "in this synthetic example…".
