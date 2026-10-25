# S05 — Architecture

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**

## Module map

All logic lives in `src/mavenu/crypto_demo.py` (single module, ~800
lines — deliberately one file so the whole trust surface is reviewable in
one sitting). Persistence is three SQLite tables (migration
`015_crypto.sql`); the web layer is thin handlers in `web.py`.

```
src/mavenu/crypto_demo.py
├── §1 hashing            sha256 / sha256_hex
├── §2 message auth       hmac_sha256 (+policy) / hmac_sha256_raw (KAT only)
│                         hmac_verify — always hmac.compare_digest
├── §3 key policy         validate_key, generate_key (secrets only)
├── §4 password hashing   hash_password / verify_password (PBKDF2-HMAC-SHA256)
│                         pbkdf2_derive (validated wrapper, KAT surface)
├── §5 educational cipher _xor_keystream (SHA-256 counter mode) — EDUCATIONAL
│                         derive_enc_mac_keys (domain-separated subkeys)
│                         encrypt / decrypt (encrypt-then-MAC, replay cache)
├── §6 MAC "sign"         mac_sign / mac_verify (labeled symmetric MAC)
├── §7 pitfalls           PITFALLS catalog (8 entries) + ecb_equality_demo
├── §8 asymmetric design  CERT_DESIGN — DESIGN ONLY, not code
├── §9 key lifecycle      create/rotate/destroy/compromise/reencrypt_all,
│                         store/read_message, key_inventory (SQLite)
└── §10 guided demos      demo_sign_workflow, demo_encrypt_workflow
```

## Design decisions and rationale

**Why stdlib only.** The requirement is established primitives. Python's
`hashlib`/`hmac`/`secrets` are the established, reviewed implementations
available at zero cost; wrapping them thinly keeps the audit surface tiny.

**Why the educational cipher exists at all.** Stdlib has no block cipher
and no AEAD. Teaching nonce discipline and encrypt-then-MAC without *any*
encryption construction would leave the two most-misunderstood ideas
abstract. So the construction exists, but: (a) it is used ONLY inside
encrypt-then-MAC, (b) it is bannered EDUCATIONAL on the module, the
envelope, every web page, and every API response, (c) the pointer to
audited libraries (AES-GCM via `cryptography`) is part of the banner, and
(d) no doc, test, or page ever presents it as production-safe.

**Why encrypt-then-MAC, verify-before-decrypt.** The tag covers
length-prefixed nonce + AAD + ciphertext (prefixing prevents concatenation
collisions). Decryption order is: structural validation → replay check →
tag verification (constant-time) → keystream XOR. Tampered input never
produces partial plaintext.

**Why key separation.** `derive_enc_mac_keys()` derives distinct
`enc`/`mac` subkeys from each master key via HMAC with domain-separation
labels. One key, two jobs is pitfall P-KEYREUSE.

**Why the replay cache is session-scoped.** `decrypt()` rejects any
(key, nonce) pair it has already accepted — demonstrating nonce-misuse
resistance as a *behavior*, not just a comment. It is module-level and
documented as demo-grade; a real system would persist this with the key
registry. Tests reset it via `_reset_nonce_cache_for_tests()`.

**Why two HMAC entry points.** `hmac_sha256_raw` (no policy) exists solely
so RFC 4231 vectors — which use 4-byte keys the policy rightly rejects —
can test the primitive. Application code uses `hmac_sha256`
(policy-enforced). The raw path is documented as KAT-only.

**Why the key registry is versioned.** Rotation must not strand old data:
`crypto_keys` keeps retired versions decryptable; `crypto_messages`
records the writing version; `destroy_key` wipes (zeros) + tombstones so
destruction is both real and auditable; `crypto_key_events` is the
append-only actor-stamped log. `compromise_response()` executes the
documented incident procedure: mark compromised → rotate → re-encrypt.

## Asymmetric sign/verify + certificate validation — design pattern (NOT code)

Stdlib has no public-key signatures, and this project invents none. The
design documentation (`CERT_DESIGN`, returned by
`describe_cert_validation_design()` and `GET /api/crypto/cert-design`)
specifies the pattern a real implementation must follow:

- **Sign/verify:** keypair from an audited library (e.g. Ed25519 via
  `cryptography`); private key in HSM/KMS; verification needs only the
  public key — the property that gives non-repudiation, which symmetric
  MACs cannot provide. Always verify before use; fail closed.
- **Certificate validation checklist** (8 steps): chain to a trusted root;
  verify every signature; validity window (UTC); revocation (OCSP/CRL,
  explicit fail-open vs fail-closed policy); name binding (SAN/CN hostname
  check); key-usage extensions; issuer pinning where the peer set is known;
  log failures, never retry with validation disabled.
- **Classic failures documented:** shipping the dev validation-skip to
  prod; ignoring expiry/revocation; disabling the hostname check to make a
  test pass.

## Key-management design document

| Concern | Design (implemented where noted) |
|---|---|
| Generation | `secrets.token_bytes(32)`; `random` never used for key material |
| Storage tiers | Demo: SQLite registry (synthetic keys). Documented tiers for real use: HSM/KMS > OS keychain/secret manager > encrypted-at-rest config > never in source control |
| Rotation schedule | `rotate_key()`: new active version, old retired but decryptable. Documented cadence guidance: rotate on schedule (e.g. 90 days for data keys), on personnel change, and immediately on suspected compromise |
| Destruction | `destroy_key()`: overwrite stored bytes with zeros + status tombstone; `_load_live_key` refuses destroyed versions (`KeyDestroyedError`) |
| Compromise response | `compromise_response()`: mark compromised → rotate → `reencrypt_all()` (messages under destroyed keys are counted as unrecoverable, not silently dropped) |
| Audit | Every transition logged to `crypto_key_events` with actor + timestamp |

## Web surface

`/project_s05` (overview) · `/project_s05/primitives` · `/project_s05/pitfalls`
· `/project_s05/keymgmt` · `POST /project_s05/demo` (guided synthetic demo).
`/api/crypto/*`: `hash`, `hmac`, `password`, `encrypt`, `decrypt`, `keys`,
`rotate`, `destroy`, `pitfalls`, `cert-design`. Every response carries
`educational_only: true`, the banner, and `synthetic: true`. The API is a
demo surface, **not a crypto service** — it exists so the behaviors are
exercisable and testable over HTTP.
