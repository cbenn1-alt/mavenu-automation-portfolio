# S05 — Runbook

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**

## Operating the demo

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py          # start the app (WSGI, stdlib server)
# open /project_s05 — overview, primitives, pitfalls, key management
# "Run guided demo" executes demo_sign_workflow + demo_encrypt_workflow
# on synthetic data and renders every step.
```

API (educational demo surface, not a crypto service):

```bash
curl -s -X POST localhost:8080/api/crypto/hash \
  -d '{"message_hex":"616263"}'
curl -s -X POST localhost:8080/api/crypto/encrypt \
  -d '{"plaintext_hex":"68656c6c6f"}'   # fresh synthetic key returned
curl -s localhost:8080/api/crypto/pitfalls
curl -s localhost:8080/api/crypto/cert-design   # DESIGN ONLY pattern
```

## Key-lifecycle procedures (demo registry)

| Procedure | How |
|---|---|
| Create key | `crypto_demo.create_key(conn, actor)` → new active version |
| Rotate | `crypto_demo.rotate_key(conn, actor)` → old retired (still decryptable), new active |
| Destroy | `crypto_demo.destroy_key(conn, version, actor)` → wiped + tombstoned; use raises `KeyDestroyedError` |
| Compromise | `crypto_demo.compromise_response(conn, version, actor)` → marks compromised, rotates, re-encrypts all messages under the new key; returns counts incl. `skipped_destroyed` |
| Inspect | `crypto_demo.key_inventory(conn)` → versions, statuses, event history |

## Incident procedure (if a demo key were treated as real — it never is)

1. `compromise_response(conn, version, actor)` — contains the blast radius.
2. Review `crypto_key_events` for the version's history (who created/used it).
3. Messages under a destroyed key are unrecoverable by design — the
   `skipped_destroyed` count tells you how many.

## Rollback procedure

The S05 schema is migration `015_crypto.sql` with down-step
`015_crypto.down.sql`.

```python
from mavenu.db import get_connection, rollback_migration, run_migrations
conn = get_connection(db_path)
rollback_migration(conn, "015_crypto.sql")  # drops crypto_keys,
                                           # crypto_key_events, crypto_messages
run_migrations(conn)                       # re-applies cleanly if needed
```

Rollback is tested for real (`test_migration_rollback_for_real`,
TEST_RESULTS.md M5, 2026-10-23). Effect: all S05 registry/message rows are
removed — they are synthetic demo data, so nothing of value is lost. The
application code (`crypto_demo.py`, web handlers) needs no rollback; it is
inert without the tables.

## Reverting the web additions

S05 routes/handlers in `web.py` are additive (nav links, `/project_s05*`,
`/api/crypto*`). To disable: remove the route block marked
`S05: applied cryptography` and the handler block starting
`# ---- S05 pages`. Prior routes are untouched (verified by the 1124-test
regression run).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `NonceReusedError` on a second decrypt | Replay protection working as designed | Use a fresh envelope; resets between tests via `_reset_nonce_cache_for_tests()` |
| `WeakKeyError` on RFC 4231 vectors | Policy rejects the 4-byte test keys | Use `hmac_sha256_raw()` for KAT (documented) |
| `KeyDestroyedError` on read | Key was destroyed | Expected — destruction is irreversible by design |
| 422 `auth_failed` from `/api/crypto/decrypt` | Tampered envelope or wrong key | Inspect the envelope; the API fails closed by design |
