# S04 — Test Plan

**Strategy:** unit + workflow + adversarial + API + rollback, all
against synthetic fixtures with an injectable clock. No real data, no
network, no PII.

## Suites

| Suite | File | Focus |
|---|---|---|
| Module tests | `tests/test_custody.py` (47) | intake/tagging/storage; hash-chain invariants; tamper detection; transfers; access audit; dispositions; incidents; synthetic-case walkthrough; adversarial fixtures; real rollback |
| Web + API tests | `tests/test_custody_api.py` (18) | JSON endpoints, page rendering, printable forms, seed button, conflict/validation status codes |

## Coverage map

1. **Intake → tagging → storage** (`TestIntake`): registration fields,
   tag uniqueness, acquisition-hash capture, bad-digest rejection,
   storage moves logged.
2. **Hash chain** (`TestHashChain`): genesis entry commits to
   `GENESIS_HASH`; seq strictly +1; prev_hash linkage entry-to-entry.
3. **Tamper detection** (`TestTamperDetection`): alter payload / actor /
   event type / prev_hash → `hash_mismatch` or `prev_hash_link`;
   delete entry → break; backdated insert → `seq_gap`/`hash_mismatch`/
   `backdated_timestamp`.
4. **Transfers** (`TestTransfers`): clean completion updates location;
   hash-in-before-hash-out refused; hash-out mismatch → rejected +
   open `hash_mismatch` incident + quarantine blocks retry; hash-in
   mismatch → same; location unchanged until completed; no overlapping
   open transfers; `assert_dual_hash_verified` flags an
   adversarially-planted completed row with missing `hash_in`.
5. **Access completeness** (`TestAccessLog`): auto-logged intake,
   transfer_out/transfer_in; audit clean on good data; deleting a
   transfer_in row is flagged by `audit_access_coverage`.
6. **Dispositions** (`TestDispositions`): returned/destroyed/archived
   terminal; transfers + re-disposition rejected after; authorization
   required; blocked with an open transfer.
7. **Incidents** (`TestIncidents`): resolution lifts quarantine;
   `lost_form` incident records (digital tracker as system of record).
8. **Synthetic case walkthrough** (`TestSyntheticCaseWalkthrough`):
   seed → all five forms render from the data model → every item's
   `full_trace` shows intake → transfers → disposition, chain verified →
   seeded statuses match expectations → spot-check ok → drill transfer
   is `rejected` then `completed` with a resolved incident.
9. **Adversarial fixtures** (`TestAdversarialFixtures`): 8 tamper modes
   on a seeded log — 100% detection; trusted-admin boundary documented
   (a total consistent rewrite is structurally indistinguishable).
10. **Rollback for real** (`TestMigrationRollback`): migrate → seed real
    rows → `rollback_migration("017_custody.sql")` → all 7 S04 tables
    gone + `schema_migrations` cleared → re-apply clean.
11. **API** (`test_custody_api.py`): seed (201 / 409 on re-seed); intake
    (201 / 422 bad digest); transfer lifecycle incl. 409 for
    hash-in-before-hash-out and quarantine retry; mismatch → rejected
    + incident; disposition then transfer → 409; verify endpoint;
    item detail trace; 404s; pages render with the synthetic-case banner;
    all five forms printable (`window.print()`, `SYNTHETIC` marker).

## Full-suite regression

Run in chunks, clearing `/tmp/pytest-of-root` between chunks (the
512 MB `/tmp` tmpfs fills during a single full-suite run; no
disk-backed TMPDIR):

```bash
.venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_custody.py --ignore=tests/test_custody_api.py
rm -rf /tmp/pytest-of-root
.venv/bin/python -m pytest tests/test_custody.py tests/test_custody_api.py -q -p no:cacheprovider
rm -rf /tmp/pytest-of-root
```
