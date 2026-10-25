# S03 — Digital Forensic Applications: Acquisition to Report

**Status: Implemented · Tested** — 87 automated tests, all passing.

> **⚠ SYNTHETIC DATA ONLY — METHOD DEMONSTRATION, NOT CASEWORK.**
> The "disk image" in this project is a *generated directory tree plus a
> manifest* — never a real device. Every case, authorization record,
> artifact, timeline event, hypothesis, and report is invented fixture
> data. Nothing here images, accesses, or examines a real person's
> device, and no encryption or access control is bypassed. This project
> demonstrates forensic *method* (procedure, hashing, facts-vs-inference
> discipline). It is not casework experience, not a forensic tool for
> real incidents, and not legal advice.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Case intake with synthetic authorization record + handling plan; hashed acquisition (SHA-256 per file, start/end hash capture, manifest hash); examination extractors (file listing with MAC times, log parser, deleted-file carving on synthetic data); merged timeline builder scored against ground truth; hypotheses requiring both supporting AND contradicting evidence; findings reports that *reject* inferences without confidence levels; hash-chained custody verified at every handoff (`src/mavenu/forensics.py`); migration `016_forensics.sql` + down-step, rollback tested for real; web pages (`/project_s03*`) and JSON API (`/api/forensics*`) |
| What is SIMULATED | **Simulated** | The "disk image": `generate_synthetic_case()` builds a documented directory tree + file set with planted artifacts, a synthetic filesystem-metadata layer (MAC times), a synthetic unallocated blob with a planted free-list, and a ground-truth file. The acquisition reads it read-only like an image, but it is ordinary fixture files, not a block device |
| What is SYNTHETIC | **Synthetic** | Every case, authorizer name, authorization reference, log line, deleted file, timestamp, and ground-truth record is invented. No real people, systems, or PII anywhere |
| What is NOT claimed | — | No casework experience. No real devices imaged or examined. No production deployment. No real users. No bypassing of encryption or access controls (the module has no such capability). No legal advice; the authorization record is a synthetic procedure artifact, not a legal instrument. No endorsement by any employer or platform |

## Business problem

When something goes wrong — a suspicious file, a disputed action — small
organizations have no repeatable way to collect and examine digital
evidence without contaminating it. People panic, delete folders, and
argue from memory. This project practices the boring discipline that
makes incident handling defensible: write down what you were authorized
to do, hash everything before you touch it, extract artifacts
methodically, build one honest timeline, test your hypothesis against
evidence that disagrees with it, and report facts separately from what
you merely infer.

## Implemented capabilities

- **Preparation** (`open_case`): intake with required synthetic
  authorization record (authorizer + reference) and a ≥3-step handling
  plan; stage machine `intake → acquired → examined → analyzed → reported`.
- **Acquisition** (`run_acquisition`): sorted read-only walk of the
  synthetic tree; per-file SHA-256; `start_hash` (directory-listing
  snapshot) and `manifest_hash` (canonical manifest) captured at
  start/end; repeat acquisition rejected (a re-image would fork the
  chain of custody — open a new case).
- **Integrity** (`verify_acquisition`, `verify_chain`): re-hash and
  compare; any post-acquisition modification/deletion/addition is
  reported; the hash chain (`SHA-256(prev:step:payload)`) links every
  handoff and any rewrite or reorder breaks verification.
- **Examination**: file listing with MAC times from the synthetic
  metadata layer; log parser (`<ISO-ts> key=value …`, requires
  `event=`, skips garbage); simple carving that recovers planted
  "deleted" entries from the synthetic unallocated blob and verifies
  each slice against its expected hash (corrupt slices are *reported*,
  not silently accepted).
- **Timeline** (`build_timeline`, `score_timeline`): merged chronological
  events from all artifacts; scored against ground truth with a
  documented 60-second tolerance.
- **Hypotheses** (`add_hypothesis`): rejected unless BOTH supporting and
  contradicting evidence are named — the confirmation-bias control.
  `unresolved` is a valid terminal status.
- **Reporting** (`draft_report`): findings audited for facts/inference
  separation; an inference without a `low`/`medium`/`high` confidence
  level is rejected; facts must cite evidence; rendered report keeps
  FACTS and INFERENCES in separate sections.
- **Web + API**: `/project_s03` (overview), `/project_s03/cases`,
  `/project_s03/cases/<id>`, guided demo (POST `/project_s03/demo`),
  and `/api/forensics*` endpoints (intake, list, detail, demo, acquire,
  verify, artifacts, timeline, hypotheses, report, chain). Every API
  response carries `synthetic: true` and a method-demo warning.

## Layout

- `src/mavenu/forensics.py` — the module (1 file).
- `src/mavenu/migrations/016_forensics.sql` + `016_forensics.down.sql`.
- `tests/test_forensics.py`, `tests/test_forensics_api.py` — 87 tests.
- `src/mavenu/web.py` — S03 routes/handlers (added, existing tests intact).
- `synthetic_cases/` — demo fixture output dir (generated at demo time;
  override with `MAVENU_SYNTHETIC_CASES`).

## Quick demo

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py   # start the app
# open /project_s03, click "Run guided demo", or via API:
curl -s -X POST localhost:8080/api/forensics/demo | python3 -m json.tool
```

## Case-study narrative

"A 'suspicious file' used to mean panic and a deleted folder. We built a
workflow: intake, hashed acquisition, artifact extraction, an honest
timeline, and a report that separates what we know from what we think —
practiced on synthetic cases until the method is muscle memory."

## Limitations

- Synthetic fixtures only. The method transfers; the "experience" does not.
- The write-blocking concept is *documented*; the fixture generator never
  needed it (ordinary files, read-only opens).
- Timeline tolerance (60 s) is a documented parameter, not a measured
  forensic standard.
- This is legal *information* about procedure, never legal advice.
