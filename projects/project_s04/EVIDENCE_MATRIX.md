# S04 — Evidence Matrix

Every public claim → the test or artifact that backs it, or its honest label.

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | Evidence intake captures a SHA-256 hash at acquisition, a unique tag, and a storage location | **Tested** | `TestIntake` — digest validation (bad digest → `ValidationError`), tag uniqueness, location stored; API 201 / 422 |
| 2 | Custody entries are hash-chained: each commits to the previous (prev_hash : seq : item_id : timestamp : event : payload : actor) | **Tested** | `TestHashChain` — genesis commits to `GENESIS_HASH`; seq strictly +1; prev_hash linkage entry-to-entry |
| 3 | Altering ANY field of ANY custody entry is detected | **Tested** | `TestTamperDetection` + 8 adversarial fixtures: alter payload/actor/timestamp/seq/item_id/event type, delete, backdated insert, hash-recompute-after-tamper — 100% detected with the breaking entry and reason named |
| 4 | Backdated entry insertion is detected | **Tested** | `test_backdated_insertion_detected`, `test_backdated_insert` — seq/timestamp-order checks |
| 5 | Transfers require dual hash verification: hash-out AND hash-in must each equal the acquisition hash | **Tested** | `TestTransfers` — clean completion; hash-in before hash-out refused; `assert_dual_hash_verified` |
| 6 | Zero transfers complete without dual hash verification (structural) | **Tested** | Location changes only on `completed`; audit scans every completed row for missing/mismatched hashes; adversarial planted row flagged |
| 7 | A hash mismatch rejects the transfer and opens a quarantine incident; the item is frozen until resolved | **Tested** | `test_hash_out_mismatch_rejects_and_opens_incident`, `test_hash_in_mismatch_rejects_and_opens_incident`; API 200-with-rejected + 409 on retry; incident `open` → `resolved` lifts quarantine |
| 8 | Every handling is actor-stamped in the access log; coverage is auditable | **Tested** | `TestAccessLog` — intake/transfer_out/transfer_in auto-logged; `audit_access_coverage` clean on seed, flags a planted gap |
| 9 | Dispositions (returned/destroyed/archived) are terminal and require authorization | **Tested** | `TestDispositions` — all three, terminal; transfers and re-disposition rejected; authorization required |
| 10 | The five paper forms are printable templates generated from the same data model as the tracker | **Tested** | `TestSyntheticCaseWalkthrough` + `TestPages::test_form_pages_printable` — all five render, carry the SYNTHETIC banner and print CSS |
| 11 | Chain-verification routine + spot-check procedure exist and run | **Tested** | `verify_custody_chain`, `verify_item_chain`, `spot_check`, `full_trace`; `GET /api/custody/verify`; seeded spot-check ok |
| 12 | A synthetic case file exercises every form and every transfer end to end | **Tested** | `seed_synthetic_case` (CASE-2026-SYN-047): 4 items, 3 completed transfers, 1 rejected drill + resolved incident, 3 dispositions; 44 chained entries |
| 13 | Every synthetic-case artifact is traceable through the full custody chain | **Tested** | `TestSyntheticCaseWalkthrough::test_seed_exercises_everything` — per-item trace: intake → transfers → disposition, all verified |
| 14 | Migration rollback tested for real | **Tested** | `test_rollback_for_real` (2026-10-23, Python 3.12.3/pytest 9.1.1/Linux) — 7 tables dropped, `schema_migrations` cleared, re-apply clean |
| 15 | No regressions | **Tested** | 1298/1298 prior tests pass; total 1363 (TEST_RESULTS.md) |
| 16 | All data synthetic; no PII | **Tested** | Fixture construction; invented tags/actors/hashes throughout; bannered on every page + API response |
| 17 | The "evidence" is simulated (synthetic placeholder records) | **Simulated** | `_synthetic_hash()` of invented bytes; stated in README banner, module docstring, ARCHITECTURE.md — no real device, person, or scene |
| 18 | Not legal advice; not legal authority | **Documented** | README banner, module docstring, SECURITY.md, every form footer — real admissibility depends on jurisdiction and counsel |
| 19 | Access controls assume a trusted-admin model | **Documented** | README banner + SECURITY.md — detects tampering, does not stop a privileged operator with full DB access |
