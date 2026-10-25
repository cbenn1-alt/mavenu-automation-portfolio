# S03 — Demo

> Everything below runs on synthetic fixtures. No real device, person,
> or system is involved.

## 1. Guided web demo (click-through)

1. Start the app: `cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py`
2. Open `/project_s03` — the banner states the synthetic-only terms.
3. Click **"Run guided demo (synthetic case, end to end)"**.
4. The demo generates a fresh fixture (`synthetic_cases/demo-<id>/`),
   intakes a case with a synthetic authorization record, acquires it
   (SHA-256 per file, start/end hash capture), extracts the file listing
   (MAC times), parses the log (5 events), carves the deleted notes file,
   builds the 12-event timeline, and scores it against ground truth:
   **5/5 within 60 s → score 1.0**, hash chain verified, stage `analyzed`.
5. Click **"Open the demo case →"** to see the case page: handling plan,
   acquisition manifest hash, artifacts, timeline, chain-of-custody
   verdict, and (after you POST a report) the rendered findings report.

## 2. API demo (scripted)

```bash
# Full workflow in one call; returns timeline score + chain verdict
curl -s -X POST localhost:8080/api/forensics/demo | python3 -m json.tool
# {
#   "demo": {
#     "case_ref": "FOR-000001",
#     "file_count": 3,
#     "artifacts": {"files": 3, "log_events": 5, "carved": 1},
#     "timeline_events": 12,
#     "timeline_score": 1.0,
#     "timeline_matched": "5/5",
#     "chain_ok": true,
#     "stage": "analyzed"
#   }, ...
# }

CID=1
ACQ=$(curl -s localhost:8080/api/forensics/cases/$CID | python3 -c "import json,sys; print(json.load(sys.stdin)['acquisitions'][0]['id'])")

# Integrity check: tamper with the fixture tree, then re-verify to see it fail
curl -s localhost:8080/api/forensics/cases/$CID/acquisitions/$ACQ/verify | python3 -m json.tool

# Hypothesis with the confirmation-bias control
curl -s -X POST localhost:8080/api/forensics/cases/$CID/hypotheses \
  -H 'Content-Type: application/json' -d '{
    "statement": "The demo user executed the installer.",
    "supporting": ["var/log/app.log#L3"],
    "contradicting": ["none-found-after-review"]
  }' | python3 -m json.tool

# Report: facts and inferences separated; inference needs a confidence level
curl -s -X POST localhost:8080/api/forensics/cases/$CID/report \
  -H 'Content-Type: application/json' -d '{
    "findings": [
      {"kind": "fact",
       "text": "installer_update.exe was downloaded at 2026-10-20T14:02:11Z.",
       "evidence": ["var/log/app.log#L2"]},
      {"kind": "inference",
       "text": "The demo user executed the installer.",
       "evidence": ["var/log/app.log#L3"], "confidence": "high"},
      {"kind": "inference",
       "text": "Attribution beyond the demo user is unresolved.",
       "evidence": ["var/log/app.log#L1"], "confidence": "low"}
    ]}' | python3 -m json.tool
```

## 3. What to point at when showing this to someone

- **The hash chain** (`GET /api/forensics/cases/<id>/chain`): every
  handoff from intake to report is linked; the demo page shows VERIFIED.
- **The tamper test**: modify one fixture byte after acquisition and
  `verify` names the file — contamination is detectable, not theoretical.
- **The rejected hypothesis/report**: POST a hypothesis without
  contradicting evidence (422) or a report with a confidence-less
  inference (422) — the discipline is enforced by code, not suggested
  by docs.
- **The ground-truth score**: 5/5 events within the documented 60 s
  tolerance — the timeline is *measured*, not asserted.
