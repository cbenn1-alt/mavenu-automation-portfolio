# S04 — Forensic Evidence Management: Chain of Custody System

**Status: Implemented · Tested** — 65 automated tests, all passing.

> **⚠ SYNTHETIC CASE ONLY — SYSTEM DEMONSTRATION, NOT LEGAL AUTHORITY.**
> Every case, evidence tag, hash, actor name, storage location, transfer,
> disposition, and incident in this project is invented fixture data. This
> project demonstrates a chain-of-custody *system* (who had an item, when,
> why, and proof it didn't change). It is **not legal advice**, not
> casework experience, not a legal instrument, and not a production
> deployment. Real admissibility depends on jurisdiction and counsel.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Evidence register (intake with SHA-256 capture, tagging, storage log); append-only custody log where each entry's hash commits to the previous (prev_hash + seq + item_id + timestamp + event + payload + actor); two-phase transfers requiring **dual hash verification** (sender hash-out AND receiver hash-in must each equal the acquisition hash — mismatch rejects the transfer and opens a quarantine incident); access log (every handling actor-stamped); terminal dispositions (returned/destroyed/archived, authorized); five printable paper forms generated from the same data model as the SQLite tracker; chain-verification routine + spot-check procedure + access-coverage audit; migration `017_custody.sql` + down-step, rollback tested for real; web pages (`/project_s04*`) and JSON API (`/api/custody*`) |
| What is SIMULATED | **Simulated** | The "evidence": synthetic placeholder records whose acquisition hashes are SHA-256 of invented bytes. Nothing is imaged, no real device or scene is represented |
| What is SYNTHETIC | **Synthetic** | The entire case file (CASE-2026-SYN-047): 4 items, all actors, all timestamps, all hashes, all transfers, the hash-mismatch drill, all dispositions and authorizations. No real people, cases, or PII anywhere |
| What is NOT claimed | — | No legal authority; not legal advice; no production deployment; no real users; no casework experience; no endorsement by any employer or platform. Access controls assume a **trusted-admin model** — documented in SECURITY.md, meaning this protects against *accidental* tampering and shows *deliberate* tampering detectably, but does not stop a privileged operator with full DB access |

## Business problem

Evidence handling fails on paperwork, not technology: who had it, when,
why, and proof it didn't change. Without that, analysis is inadmissible
and untrustworthy. This project practices the boring discipline that
makes handling defensible: write down the intake hash, chain every entry
to the last one, verify both sides of every handoff, quarantine on any
mismatch, and keep every handling on an actor-stamped access log.

## Implemented capabilities

- **Register** (`intake_item`): evidence tag (unique), description,
  media type, acquisition SHA-256, acquirer, acquisition reference
  (synthetic), storage location; emits chained `intake` +
  `storage.logged` entries and an intake access record.
- **Custody log** (`_chain_entry`): append-only, `entry_hash =
  SHA-256(prev_hash : seq : item_id : created_at : event_type :
  payload : actor)`, seq strictly +1, timestamps non-decreasing.
  `verify_custody_chain()` recomputes every hash and checks linkage,
  seq (+1), and timestamp order — alteration of *any* field of *any*
  entry, deletion, or backdated insertion is detected.
- **Transfers** (`initiate_transfer` → `record_hash_out` →
  `record_hash_in`): dual hash verification — both hashes must equal the
  acquisition SHA-256. Mismatch rejects the transfer and opens a
  quarantine incident; the item is frozen until the incident is
  resolved. The storage location changes *only* on a completed transfer,
  so zero transfers can complete without dual verification
  (structurally, asserted by `assert_dual_hash_verified`).
- **Access log** (`log_access`, `audit_access_coverage`): every
  view/handling actor-stamped with purpose; transfers and dispositions
  auto-log both sides; the audit proves no handling went unrecorded.
- **Dispositions** (`record_disposition`): returned / destroyed /
  archived with named authorizer + authorization reference (synthetic
  record). Terminal: further transfers and dispositions are rejected.
- **Forms** (`render_form`): the five paper forms (evidence intake,
  chain-of-custody log, access log, transfer receipt, disposition
  record) as printable HTML generated from the tracker — the digital
  tracker is the system of record, paper is backup.
- **Verification** (`verify_item_chain`, `spot_check`, `full_trace`):
  per-item entry-hash recomputation + lifecycle completeness; the
  runnable spot-check procedure; full traceability report.

## Synthetic case

`seed_synthetic_case()` builds CASE-2026-SYN-047 (44 chained entries):
4 items in → storage check + access entries → 2 clean transfers →
1 deliberate hash-mismatch drill (rejected + quarantine incident, then
resolved, then clean re-transfer) → 3 dispositions (archived, returned,
destroyed) with the 4th item remaining in custody. Every form and every
transfer exercised end to end.

## Map

- Code: `src/mavenu/custody.py`, migration `017_custody.sql` + down-step
- Tests: `tests/test_custody.py` (47), `tests/test_custody_api.py` (18)
- Web: `/project_s04*` pages · `/api/custody*` JSON endpoints
