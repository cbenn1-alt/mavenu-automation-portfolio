# S04 — Requirements

**Status: Implemented.** Each requirement below is covered by an
automated test in `tests/test_custody.py` / `tests/test_custody_api.py`
(or is an honest limitation documented in README.md / SECURITY.md).

## Functional requirements

| # | Requirement | Implementation |
|---|---|---|
| R1 | Evidence intake with SHA-256 captured at acquisition, unique evidence tag, and storage location logged | `intake_item` — 64-hex digest validation, tag uniqueness, emits `intake` + `storage.logged` chained entries |
| R2 | Tagging: every item carries a stable, unique evidence tag used by all downstream records | `tag` column, UNIQUE; every log payload references tags |
| R3 | Storage log: current location recorded at intake; moves/inventory checks logged | `log_storage`; `storage.logged` entries |
| R4 | Access log: every view/handling actor-stamped with timestamp and purpose | `log_access`; ACCESS_ACTIONS vocabulary; transfers/dispositions auto-log |
| R5 | Transfer log with dual hash verification: sender records hash-out, receiver records hash-in; BOTH must equal the acquisition hash | `initiate_transfer` → `record_hash_out` → `record_hash_in`; hash-in before hash-out is refused (409) |
| R6 | Hash mismatch at either side rejects the transfer and opens a quarantine incident; the item is frozen until resolved | `_reject_transfer` → `open_incident(kind='hash_mismatch')`; `_quarantined` blocks transfers/dispositions |
| R7 | Disposition records: returned / destroyed / archived with named authorizer + authorization reference (synthetic) | `record_disposition`; terminal status enforced |
| R8 | The five paper forms as printable templates AND as a SQLite-backed tracker | `render_form` (HTML, print CSS) generated from the same rows the tracker stores |
| R9 | Audit trail: every record actor-stamped and timestamped | custody_log + custody_access + custody_dispositions + custody_incidents all carry actor + UTC ISO-8601 timestamps |
| R10 | Tamper-evident design: append-only log, hash-chained entries, each entry commits to the previous | `entry_hash = SHA-256(prev_hash : seq : item_id : created_at : event_type : payload : actor)`; seq strictly +1; timestamps non-decreasing; `verify_custody_chain` recomputes everything |
| R11 | Chain-verification routine + spot-check procedure | `verify_custody_chain`, `verify_item_chain`, `spot_check`, `full_trace`; `GET /api/custody/verify` |
| R12 | One synthetic case file exercising every form and every transfer end to end | `seed_synthetic_case` — CASE-2026-SYN-047: 4 items, 3 completed transfers, 1 rejected drill + resolved incident, 3 dispositions |

## Measurable criteria

| # | Criterion | Status |
|---|---|---|
| M1 | 100% tamper detection on adversarial fixtures | **Tested** — 8 adversarial fixtures (alter payload/actor/timestamp/seq/item_id/event, delete middle entry, backdated insert, hash-recompute-after-tamper): all detected; `TestAdversarialFixtures` |
| M2 | Zero transfers without dual hash verification | **Tested** — `assert_dual_hash_verified` scans every completed transfer: both hashes present and equal to the acquisition hash; an adversarially-planted completed row with missing hash_in is flagged; hash-in-before-hash-out is refused by API |
| M3 | Every synthetic-case artifact traceable through the custody chain (intake → transfers → disposition) | **Tested** — `full_trace` per item in `TestSyntheticCaseWalkthrough`; intake entry present, transfer lifecycle complete, disposition entry for terminal items |
| M4 | Access-log completeness audit passes on the seeded case and detects planted gaps | **Tested** — `audit_access_coverage` clean on seed; deleting a transfer_in row is flagged |
| M5 | Migration rollback tested for real | **Tested** — `test_rollback_for_real`: 017 applied → 4 items seeded → rollback drops all 7 S04 tables + clears `schema_migrations` → re-apply clean |
| M6 | No regressions | **Tested** — full suite run in chunks (see TEST_RESULTS.md) |

## Non-goals (documented limitations)

- Not legal advice; not a legal instrument; no claim of courtroom admissibility.
- Access controls assume a trusted-admin model (SECURITY.md): detects tampering, does not stop a privileged operator with full DB access.
- No real evidence, devices, people, or PII. All data synthetic.
- Python 3.12 stdlib only at runtime; SQLite; $0 spend; no network calls.
