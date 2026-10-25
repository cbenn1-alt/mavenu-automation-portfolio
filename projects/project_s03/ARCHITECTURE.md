# S03 — Architecture

## Module map (one module: `src/mavenu/forensics.py`)

```
forensics.py
├── helpers            now_iso (injectable clock), sha256_file, _canonical JSON
├── chain_step / verify_chain        SHA-256 hash chain across handoffs
├── open_case / get_case / list_cases  preparation + synthetic authorization
├── run_acquisition / verify_acquisition  hashed acquisition of the tree
├── extract_file_listing             MAC times from synthetic metadata layer
├── parse_log_line / parse_log / extract_log_events
├── carve_deleted                    synthetic unallocated-space carving
├── build_timeline / record_timeline / score_timeline / get_timeline
├── add_hypothesis / set_hypothesis_status / list_hypotheses
├── audit_findings / render_report / draft_report / get_report
└── generate_synthetic_case / events_from_fixture   fixture generator
```

Rationale for one module: the workflow is a single pipeline with shared
conventions (clock, canonical JSON, chain). Splitting it would add seams
with no benefit at this scale.

## Data model (`016_forensics.sql`)

- `forensics_cases` — intake: `case_ref` (`FOR-000001…`), title,
  description, `authorizer_name` + `authorization_ref` (the synthetic
  authorization record), `handling_plan_json`, `status` in
  `intake → acquired → examined → analyzed → reported`.
- `forensics_acquisitions` — `method`, `source_label`, `started_at`,
  `finished_at`, `start_hash` (directory-listing snapshot), `manifest_json`
  (canonical per-file `{rel: {sha256, size}}`), `manifest_hash`,
  `file_count`, `total_bytes`.
- `forensics_artifacts` — `acquisition_id`, `kind` in
  `file | log_event | carved`, `ref_path`, `detail_json`, `sha256`.
  Every artifact traces to the acquisition whose manifest hashes it.
- `forensics_timeline_events` — `case_id`, `ts` (ISO-8601 UTC), `source`,
  `event_type`, `summary`, `ref`.
- `forensics_hypotheses` — `statement`, `supporting_json`,
  `contradicting_json` (both non-empty, enforced in code), `status` in
  `open | supported | refuted | unresolved`.
- `forensics_reports` — `findings_json`, `audit_json`, `report_text`.
- `forensics_hashchain` — `case_id`, `step`, `payload`, `payload_hash`,
  `prev_hash`, `created_at`. `payload_hash = SHA-256(prev_hash:step:payload)`.

Migration down-step (`016_forensics.down.sql`) drops indexes + tables;
`rollback_migration()` removes the `schema_migrations` record so the
up-step can re-apply (rollback tested for real — TEST_RESULTS.md).

## The synthetic "disk image" (Simulated)

`generate_synthetic_case(target_dir)` produces four layers:

1. `tree/` — the "image": 3 UTF-8 text files
   (`home/alvarez/docs/report_final.docx`,
   `home/alvarez/downloads/installer_update.exe`,
   `var/log/app.log`).
2. `_meta.json` — the synthetic *filesystem-metadata layer* (the analogue
   of inode/MFT records): MAC times, owner, mode per file. This is
   **evidence**, not answers.
3. `_unallocated.bin` + `_freelist.json` — synthetic unallocated space
   with one planted "deleted" file (`secret_notes.txt`), offset/size/
   expected-SHA-256/`deleted_at`.
4. `_ground_truth.json` — the **answers**: planted files, deleted files,
   5 key events with timestamps. Read by tests only; the module never
   opens it (`events_from_fixture` reads only layers 1–3).

Scenario (all invented): on synthetic host `WS-07`, user `demo-user`
downloads an installer (14:02:11Z), runs it (14:03:47Z), deletes a notes
file (16:20:05Z); a report is created (09:12:00Z) and modified
(17:45:30Z). Log lines mirror the download/execute/delete.

## Workflow and stage machine

```
intake --run_acquisition--> acquired --extract_*--> examined
       --record_timeline--> analyzed --draft_report--> reported
```

- Acquisition is allowed only from `intake`. A second acquisition on the
  same case raises `ForensicsError`: re-imaging would fork the chain of
  custody, so the procedure requires a new case.
- `verify_acquisition` re-walks the source tree and compares per-file
  hashes + manifest hash: reports `mismatches`, `missing`, `extra`.
- `verify_chain` recomputes every link; a rewritten `payload_hash` or a
  spliced `prev_hash` is reported with the breaking step.

## Timeline scoring

`score_timeline(built, ground_truth, tolerance_seconds=60)`: each
ground-truth event (`ts` + `event_type`) greedily matches an unused built
event of the same type within ±60 s. Score = matched/total. The 60 s
tolerance is a documented parameter of the fixture (clock skew between
the synthetic filesystem layer and the synthetic log), not a forensic
standard — ARCHITECTURE states this so it is never mistaken for one.

## Report validation

`audit_findings` returns `{severity, index, message}` issues:

- **error**: inference without `low`/`medium`/`high` confidence; fact or
  inference without evidence; unknown kind; missing text.
- **warning**: fact carrying a confidence level (facts shouldn't need one).

`draft_report` refuses to store when any error exists. The rendered
report prints FACTS and INFERENCES under separate headings; hypotheses
and the chain-of-custody verdict appear in their own sections.

## Web layer (`web.py` additions)

- Pages: `/project_s03` (banner + overview + demo form),
  `/project_s03/cases`, `/project_s03/cases/<id>` (case detail: plan,
  acquisitions, artifacts, timeline, hypotheses, chain verdict, report).
- API: `POST /api/forensics/cases` (intake) · `GET /api/forensics/cases`
  · `GET /api/forensics/cases/<id>` · `POST /api/forensics/demo` (full
  synthetic workflow) · `POST /api/forensics/cases/<id>/acquire`
  (`{"fixture": name}` — plain dirname under `SYNTHETIC_CASES_DIR` only;
  path traversal rejected) · `GET …/acquisitions/<id>/verify`
  · `GET …/artifacts` · `GET …/timeline`
  · `POST …/hypotheses` · `GET|POST …/report` · `GET …/chain`.
- Every API response includes `synthetic: true`, `method_demo_only:
  true`, and a warning string. `ForensicsError` (state errors) → 409;
  `ValidationError` → 422 via the existing global handler.

## Why this design

The discipline is the product. Procedure (intake → hashed acquisition →
examination → timeline → report), hashing at every handoff, and the
facts/inference separation are what make forensics defensible — so the
code enforces them (rejected re-acquisitions, required contradicting
evidence, rejected confidence-less inferences) rather than merely
documenting them.
