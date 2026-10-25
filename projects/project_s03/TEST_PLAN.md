# S03 — Test Plan

Methodology (from the spec): planted-artifact fixtures with known ground
truth; timeline accuracy scored against ground truth; hash-chain
integrity verified end-to-end; report review checklist (facts/inference
separation audited). All tests run via the repo venv:
`cd ~/workspace/mavenu-portfolio && .venv/bin/python -m pytest tests/`.

## Fixture

`generate_synthetic_case()` (in the module) builds a deterministic
fixture: 3 text files, synthetic MAC metadata, a 5-line log, one planted
deleted file in synthetic unallocated space, and `_ground_truth.json`
(5 events). Tests read ground truth; the module never does.

## Test classes → spec criteria

| Class | What it proves | Spec criterion |
|---|---|---|
| `TestFixtureGenerator` | Fixture builds correctly; **all files UTF-8 text** (no binaries); ground truth has 5 events | F1, N4 |
| `TestIntake` | Authorization record + handling plan required; `case_ref` format; intake starts the hash chain | F2, F11 |
| `TestAcquisition` | 3 files hashed; start/end hashes differ and are 64-hex; manifest deterministic across runs; re-acquisition rejected; bad source rejected | F3 |
| `TestIntegrity` | Untouched → `ok` with zero mismatches/missing/extra; **modify/delete/add each detected**; chain rewrite and chain reorder each detected | M2, F11 |
| `TestExamination` | **100% planted-file recovery** (3/3); MAC times come from meta layer; log parser handles 5 lines and skips 5 garbage classes; **deleted file carved 1/1 with hash match**; corrupt expectation reported not silent; out-of-bounds rejected; artifacts traceable to acquisition | F5, F6, F7, M1 |
| `TestTimeline` | Chronological merge; incomplete event rejected; **5/5 within 60 s tolerance**; 59 s matches / 61 s doesn't; type must match; persisted + stage → analyzed | F8, M3 |
| `TestHypotheses` | Missing contradicting → rejected; missing supporting → rejected; `none-found-after-review` accepted; `supported/refuted/unresolved` transitions; bad status rejected | F9 |
| `TestReport` | Draft ok; inference w/o confidence → rejected (module + audit unit); bad confidence value → error; fact w/o evidence → error; fact with confidence → warning (not error); `unresolved` accepted; FACTS/INFERENCES sections separated; report before `analyzed` → `ForensicsError`; chain VERIFIED in text | F10, M4 |
| `TestMigrationRollback` | Real rollback: rows created → `rollback_migration("016_forensics.sql")` → all 7 tables gone → `run_migrations()` re-applies cleanly | migration down-step |
| API tests (`test_forensics_api.py`) | Intake/list/detail; acquire from fixture (incl. path-traversal rejection, unknown fixture 404, second acquire → 409); demo runs full workflow (score 1.0, chain ok, stage analyzed); verify/artifacts/timeline/chain endpoints; hypothesis + report endpoints incl. 422/409 paths; pages render; nav links S03 | web/API |

## Negative / adversarial cases (explicit)

- Tamper with fixture *after* acquisition (modify, delete, add) → detected.
- Rewrite a hash-chain row in the DB → `verify_chain` reports the step.
- Splice a chain link (`prev_hash`) → detected.
- Hypothesis with only supporting evidence → rejected (confirmation-bias control).
- Report with confidence-less inference → refused, not stored.
- Carve with a wrong expected hash → `hash_match: False` recorded (corrupt, not silent).
- Log with garbage lines → skipped, never crash.
- API acquire with `../` fixture name → 422.

## Full-suite regression

The whole suite runs in chunks (see TEST_RESULTS.md) because the 512 MB
`/tmp` tmpfs fills during a single full run; `/tmp/pytest-of-root` is
cleared between chunks. No disk-backed TMPDIR is used.
