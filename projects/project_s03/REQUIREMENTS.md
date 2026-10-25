# S03 — Requirements

Source: `~/workspace/your_files/portfolio-architecture-2026-10-23.md` §3 (S03).
Status vocabulary: **Implemented**, **Tested**, **Simulated**, **Demo**.

## Problem

When something goes wrong — a suspicious file, a disputed action —
small organizations have no repeatable way to collect and examine
digital evidence without contaminating it.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| F1 | **Synthetic datasets only.** The "disk image" is a documented directory tree + file set with planted artifacts (`generate_synthetic_case`). Never a real device; nothing images or touches real hardware. | Implemented + Tested |
| F2 | **Preparation.** Case intake form: title, description, synthetic authorization record (authorizer name + authorization reference), handling plan (≥3 steps). | Implemented + Tested |
| F3 | **Acquisition.** Documented procedure: sorted read-only walk, per-file SHA-256 (stdlib `hashlib`), hash capture at start (directory-listing snapshot) and end (canonical manifest hash). | Implemented + Tested |
| F4 | **Write-blocking concept documented.** Source opened read-only (`'rb'`), never written; concept documented in module docstring + SECURITY.md. | Implemented (documented) |
| F5 | **Examination — file metadata.** File listing with MAC times from the synthetic metadata layer. | Implemented + Tested |
| F6 | **Examination — log parsing.** Parse synthetic log lines (`<ISO-8601> key=value …`, required `event=`) into events; blank/garbage lines skipped. | Implemented + Tested |
| F7 | **Examination — carving.** Recover planted "deleted" entries from the synthetic unallocated blob; verify each slice against its expected hash. | Implemented + Tested |
| F8 | **Analysis — timeline.** Merged chronological timeline from all artifacts. | Implemented + Tested |
| F9 | **Analysis — hypotheses.** Annotations with supporting AND contradicting evidence tags (both required — confirmation-bias control). | Implemented + Tested |
| F10 | **Reporting.** Findings template with facts vs. inference clearly separated; every inference carries a confidence level (`low`/`medium`/`high`); `unresolved` allowed. | Implemented + Tested |
| F11 | **Logging.** Every step logged; integrity verification at each handoff (hash chain across case.opened → acquisition → examination → timeline → hypothesis → report). | Implemented + Tested |

## Non-functional requirements

| ID | Requirement | Status |
|---|---|---|
| N1 | Python 3.12 stdlib only at runtime (`wsgiref`, `sqlite3`, `hashlib`, `json`, `os`, `datetime`). $0 spend. No network calls. | Implemented |
| N2 | No PII anywhere; all data synthetic. | Implemented + Tested |
| N3 | Existing suite keeps passing (no regressions). | Tested (see TEST_RESULTS.md) |
| N4 | UTF-8 text only, no binaries (fixture files included). | Implemented + Tested |
| N5 | Injectable clock for deterministic tests. | Implemented + Tested |

## Measurable criteria (from the spec)

| ID | Criterion | How it is measured | Status |
|---|---|---|---|
| M1 | 100% of planted artifacts recovered on fixtures | File-listing + carving recovery vs. `_ground_truth.json` (3/3 files, 1/1 deleted) | Tested |
| M2 | Zero hash mismatches across the chain | `verify_acquisition` ok on untampered fixtures; `verify_chain` ok end-to-end | Tested |
| M3 | Timeline matches ground truth within documented tolerance | `score_timeline` ≥ 1.0 at 60 s tolerance on the fixture (5/5) | Tested |
| M4 | Every inference in reports carries a confidence level | `audit_findings` rejects inference without confidence; `draft_report` refuses to store | Tested |

## Out of scope (explicitly NOT built)

- Real device imaging, write-blockers, or any hardware interaction.
- Bypassing encryption or access controls (no such capability exists here).
- Casework on real incidents; legal advice; chain-of-custody paperwork for court.
- Asymmetric/digital-signature evidence sealing (S04's territory).
