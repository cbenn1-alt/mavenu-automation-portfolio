# S04 — Architecture

```
forms/      five paper templates (printable HTML) — the spec for the digital tracker
tracker/    SQLite evidence register + append-only hash-chained custody log
verify/     chain-verification routine + spot-check procedure + access audit
case/       synthetic case file (CASE-2026-SYN-047) exercising everything end to end
```

All four live in one module, `src/mavenu/custody.py`, behind the web
layer in `src/mavenu/web.py` (`/project_s04*` pages, `/api/custody*`
endpoints) and migration `017_custody.sql`.

## Data model

```
custody_cases        the case file (case_ref UNIQUE, title, description)
custody_items        evidence register (tag UNIQUE, acquisition_sha256 anchor,
                     storage_location, status: in_custody → returned|destroyed|archived)
custody_log          append-only hash-chained journal (seq UNIQUE +1, event_type,
                     payload_json, actor, prev_hash, entry_hash, created_at)
custody_transfers    two-phase handoff (hash_out, hash_in, status:
                     initiated → completed | rejected, incident_id)
custody_access       every handling: actor, action, purpose, created_at
custody_dispositions terminal record (returned|destroyed|archived,
                     authorized_by, authorization_ref)
custody_incidents    quarantine records (kind, detail, status open|resolved)
```

## The hash chain (the core thesis)

Each custody entry commits to the previous entry's hash:

```
entry_hash = SHA-256(prev_hash : seq : item_id : created_at : event_type : payload : actor)
```

- `seq` is a strict +1 sequence across the whole log (UNIQUE index);
  `created_at` must be non-decreasing.
- `verify_custody_chain()` recomputes every hash in id order and checks:
  prev_hash linkage → hash recomputation → seq == prev+1 →
  timestamp ordering. The first failing entry is named with its reason
  (`prev_hash_link` / `hash_mismatch` / `seq_gap` /
  `backdated_timestamp`).
- Because `item_id` is hashed into each entry, reassigning an entry to
  another item is also detected.

Failure modes addressed (spec §3 S04):
- **Backdated entries** → seq + timestamp-order checks catch insertion.
- **Hash mismatch on transfer** → rejection + quarantine incident form.
- **Lost paper forms** → the digital tracker is the system of record;
  paper is backup (forms print the tracker's hashes so a page can be
  reconciled to the database).

## Dual hash verification (transfer protocol)

```
initiate_transfer  (item must be in_custody, not quarantined, no open transfer)
      → record_hash_out   (must equal acquisition SHA-256; mismatch → REJECT + incident)
      → record_hash_in    (refused before hash-out; must equal acquisition SHA-256;
                           mismatch → REJECT + incident)
      → status=completed; storage_location updated ONLY here
```

Structurally, zero transfers complete without both verifications:
location never changes on a rejected/pending transfer, and
`assert_dual_hash_verified()` audits every completed transfer for
missing or mismatched hashes.

## Event vocabulary

`intake, tagging, storage.logged, access.logged, transfer.initiated,
transfer.hash_out, transfer.hash_in, transfer.completed,
transfer.rejected, disposition.recorded, incident.opened,
incident.resolved` — every event actor-stamped and timestamped.

## Trust boundary

The chain detects tampering *after the fact* (a privileged operator with
full DB access could rewrite the entire log consistently — documented in
SECURITY.md). This is the trusted-admin assumption: the system protects
against accidental corruption and makes deliberate tampering provable,
it does not stop an omnipotent insider.
