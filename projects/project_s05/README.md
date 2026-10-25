# S05 — Applied Cryptography: Hashes, Encryption, Signatures

**Status: Implemented · Tested** — 87 automated tests, all passing.

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**
> SHA-256, HMAC, and PBKDF2 here run on Python's standard library and are
> checked against published vectors. The symmetric "cipher" is a SHA-256
> counter-mode stream construction written **only** to teach nonce
> discipline and the encrypt-then-MAC pattern — it is **not** an audited
> cipher and **must never be used in production**. Real systems must use an
> audited library (e.g. AES-GCM via the `cryptography` package).
> **README forbids production use of anything in this project without
> expert review.** All keys, nonces, salts, and messages are synthetic
> test-only material. No real users, systems, or secrets are involved.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | SHA-256 hashing, HMAC-SHA256 (constant-time `compare_digest` verification), and PBKDF2-HMAC password hashing with a work-factor parameter — all via Python stdlib (`hashlib`, `hmac`, `secrets`), checked against published vectors (`src/mavenu/crypto_demo.py`); an encrypt-then-MAC *construction* (MAC tag verified before decryption, 256-bit random nonces, replays rejected); a versioned SQLite key registry with generation, rotation, destruction, and compromise response; migration `015_crypto.sql` + down-step, rollback tested for real; web pages (`/project_s05*`) and JSON API (`/api/crypto*`) |
| What is EDUCATIONAL-ONLY | **Educational** | The symmetric stream cipher inside the encrypt-then-MAC construction is a SHA-256 counter-mode teaching construction. It exists to demonstrate nonce discipline, key separation, and verify-before-decrypt ordering. Bannered on every surface (module docstring, envelope field, web pages, API responses). **Not reviewed, not audited, never production.** |
| What is DESIGN-ONLY | **Design** | Asymmetric (public-key) signatures and X.509 certificate validation are documented as patterns (`CERT_DESIGN`, ARCHITECTURE.md) — they are **not** implemented in code. The "sign" workflow is HMAC-based message authentication (symmetric MAC), honestly labeled as such. |
| What is SYNTHETIC | **Synthetic** | Every key, nonce, salt, password, message, and registry row is generated test data. Nothing touches real people, systems, accounts, or secrets. |
| What is NOT claimed | — | Not a crypto library. No production deployment. No real users. No side-channel testing on hardware. No endorsement by any employer or platform. No claim that the educational construction is secure for real use. |

## Business problem

Developers copy-paste crypto and get it subtly wrong: ECB mode, hardcoded
IVs, home-rolled "encryption," unauthenticated ciphertext, `==` tag
comparisons, keys that never rotate. This project demonstrates *correct*
use of established primitives — each one standing next to the classic
mistake it prevents — so the next developer inherits understanding, not
just snippets.

## Implemented capabilities

- **Hashing** (`sha256`/`sha256_hex`): NIST FIPS 180-4 vectors pass (`""`,
  `"abc"`).
- **HMAC** (`hmac_sha256` + policy, `hmac_sha256_raw` for KAT): RFC 4231
  test cases 1–4 pass; verification always via `hmac.compare_digest`.
- **Password hashing** (`hash_password`/`verify_password`): PBKDF2-HMAC-SHA256
  with per-password 128-bit salt and a work-factor parameter (demo default
  100,000 iterations; documented guidance to calibrate to ≥600,000 per OWASP
  2023 for real deployments). RFC 6070 vectors pass for the KDF plumbing
  (SHA-1); SHA-256 output cross-checked against an independent RFC 2898
  implementation in the test file (no RFC vector set exists for
  PBKDF2-HMAC-SHA256 — stated honestly).
- **Educational encrypt-then-MAC** (`encrypt`/`decrypt`): tag covers
  nonce + associated data + ciphertext; verification precedes decryption;
  256-bit random nonces from `secrets`; accepted (key, nonce) replays are
  rejected (`NonceReusedError`); 100% tamper detection in tests.
- **Key policy** (`validate_key`): rejects short, blocklisted, all-zero, and
  repeated-byte keys at every entry point — fails closed.
- **Key registry** (SQLite, migration `015_crypto.sql`): versioned keys;
  rotation keeps old data readable; destruction wipes + tombstones and
  refuses use; `compromise_response()` = mark compromised → rotate →
  re-encrypt. Every transition actor-stamped in `crypto_key_events`.
- **Pitfalls catalog** (8 entries, `PITFALLS`): ECB, nonce reuse, hardcoded
  keys, home-rolled crypto, unauthenticated encryption, timing oracles, key
  reuse across purposes, never-rotated keys — each mapped to the
  demonstration that avoids it. Includes an *illustrative* ECB "DON'T"
  fixture that visibly leaks plaintext equality.
- **Web + API**: `/project_s05*` pages (bannered) and `/api/crypto*`
  endpoints (hash, hmac, password, encrypt, decrypt, keys, rotate, destroy,
  pitfalls, cert-design). The API is an **educational demo surface, not a
  crypto service**.

## Layout

- `src/mavenu/crypto_demo.py` — the module (1 file, ~800 lines).
- `src/mavenu/migrations/015_crypto.sql` + `015_crypto.down.sql`.
- `tests/test_crypto.py`, `tests/test_crypto_api.py` — 87 tests.
- `src/mavenu/web.py` — S05 routes/handlers (added, existing tests intact).

## Quick demo

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py   # start the app
# open /project_s05, click "Run guided demo", or:
.venv/bin/python - <<'EOF'
from mavenu import crypto_demo as c
key = c.generate_key()
env = c.encrypt(key, b"synthetic payload")
print(c.decrypt(key, env))          # b'synthetic payload'
EOF
```

## Case-study narrative

"Crypto fails in the details everyone skips: the nonce, the comparison,
the key nobody rotated. We built the correct patterns in plain code — each
one standing next to the classic mistake it prevents — so the next
developer inherits understanding, not just snippets."
