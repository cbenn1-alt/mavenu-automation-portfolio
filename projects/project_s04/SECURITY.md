# S04 — Security

## Tamper-evidence design

- **Hash-chained custody log.** Every entry: `entry_hash =
  SHA-256(prev_hash : seq : item_id : created_at : event_type : payload :
  actor)`. Altering *any* field of *any* entry (payload, actor,
  timestamp, event type, item reassignment, prev_hash) breaks
  verification; deleting an entry breaks the next row's prev_hash link;
  inserting a backdated entry breaks the seq + timestamp-order checks.
  Tested: 8 adversarial fixtures, 100% detection
  (`TestAdversarialFixtures`).
- **Acquisition hash as the integrity anchor.** Captured once at intake;
  every transfer verifies hash-out AND hash-in against it (dual hash
  verification). A mismatch rejects the transfer and opens a quarantine
  incident — the item cannot move until the incident is resolved.
- **Append-only.** The module never updates or deletes custody-log rows
  (only test fixtures write directly, to prove detection). All writes
  use parameterized SQL; input validation at every boundary (tag
  pattern, 64-hex digests, controlled vocabularies).
- **No secrets in code.** Nothing to leak: there are no credentials,
  keys, or real personal data — every value in tests and the seeded
  case is invented.

## Trusted-admin assumption (documented limitation)

This system **detects** tampering; it does not stop a privileged
operator with full database access. An attacker who can rewrite the
entire log consistently (recomputing every hash in order, keeping seq
and timestamps valid) produces a chain that verifies — the same
limitation as any hash-chained log without external anchoring. What the
design buys: accidental corruption is impossible to miss, and
deliberate single-point tampering announces itself with the exact
entry and check that failed. Real deployments needing stronger
guarantees should anchor chain checkpoints externally (e.g. published
hashes) and enforce access control — out of scope for this
demonstration, stated here deliberately.

## Quarantine procedure

1. A transfer whose hash-out or hash-in differs from the acquisition
   SHA-256 is **rejected** (never completed, location never changes).
2. A quarantine incident (`kind=hash_mismatch`, status `open`) is
   opened against the item, naming the side, the presented digest, and
   the expected digest; chained into the custody log.
3. While the incident is open, `initiate_transfer` and
   `record_disposition` **refuse** the item (quarantine).
4. `resolve_incident` records the resolution with actor + timestamp and
   a chained `incident.resolved` entry; the item becomes movable again.
5. The rejected transfer stays on the record permanently
   (`status=rejected`) — the drill is auditable, not erasable.

Exercised end to end in the seeded synthetic case (EV-047-004 drill)
and in tests (`TestTransfers`, `TestIncidents`, API mismatch test).

## Synthetic-data guarantee

All case files, tags, hashes, actors, locations, authorizations, and
incidents are invented. The "evidence" is placeholder records. No real
people, cases, devices, or PII are involved anywhere — enforced by
fixture construction, not by policy.
