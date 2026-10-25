# S04 — Demo

A 5-minute guided tour of the chain-of-custody system. Everything below
is synthetic; all names, tags, hashes, and locations are invented.

## Setup (30 seconds)

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py &
# open http://localhost:8080/project_s04 and click "Seed synthetic case"
```

## Tour

1. **The register** (`/project_s04/register`) — 4 evidence items
   (EV-047-001 … EV-047-004), each with its acquisition SHA-256,
   storage location, and status. The header shows the chain verdict.
2. **An item's full chain** (`/project_s04/items/2`) — EV-047-002:
   intake → storage → transfers with both hashes verified →
   disposition (returned). Every entry shows its seq, actor, timestamp,
   and entry hash. Chain: VERIFIED.
3. **The five forms** — from any item page: Intake, Chain-of-custody
   log, Access log, Disposition record — and Transfer receipts from the
   register (`/project_s04/forms/transfer_receipt?transfer_id=1`).
   Each prints cleanly (print button included); each carries the
   tracker's hashes so a printed page reconciles to the database.
4. **The drill** (`/project_s04/incidents`) — EV-047-004's transfer was
   attempted with a wrong hash-out: rejected, incident #1 opened
   (`hash_mismatch`, now resolved), then a clean re-transfer completed.
   The rejected attempt stays on the record.
5. **Tamper-evidence, live** — in a Python shell against the app DB:

   ```python
   import sys; sys.path.insert(0, "src")
   from mavenu.db import get_connection
   from mavenu import custody as c
   conn = get_connection("<app-db-path>")
   print(c.verify_custody_chain(conn))          # ok: True
   # tamper: change one actor's name in custody_log, then re-verify:
   conn.execute("UPDATE custody_log SET actor='Impostor' WHERE id=10")
   conn.commit()
   print(c.verify_custody_chain(conn))          # ok: False, broken_at: 10
   ```

## Talking points (for interviews / case studies)

- "Evidence handling fails on paperwork, not technology. We built the
  paperwork as a system: every handoff hashed on both sides, every
  entry chained to the last."
- "A hash mismatch doesn't get argued about — the transfer is rejected
  and the item is quarantined automatically."
- "Try to alter a record and the chain tells on you — the demo proves
  it in one SQL UPDATE."
- Honest boundary: "This demonstrates a custody *system*, not legal
  authority. Real admissibility depends on jurisdiction and counsel —
  and the access model here assumes a trusted admin."
