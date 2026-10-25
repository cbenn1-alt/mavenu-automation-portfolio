# S05 — Requirements

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**
> README forbids production use without expert review.

## Problem statement

Developers copy-paste crypto and get it subtly wrong: ECB mode, hardcoded
IVs, home-rolled "encryption," unauthenticated ciphertext, timing-leaky
comparisons, keys that never rotate. S05 demonstrates *correct* use of
*established* primitives (never invented, never "improved"), each paired
with the classic failure mode it prevents.

## Functional requirements

1. **Established primitives only.** Python stdlib (`hashlib`, `hmac`,
   `secrets`). No invented primitives, no "improved" ciphers. The one
   teaching construction (SHA-256 counter-mode stream) exists ONLY inside
   an encrypt-then-MAC construction, is bannered EDUCATIONAL on every
   surface, and ships with a documented pointer to audited libraries
   (AES-GCM via `cryptography`) for real use.
2. **SHA-256 hashing + HMAC.** Correct usage with parameter rationale;
   verification always constant-time (`hmac.compare_digest`).
3. **Password hashing with work factor.** Via an established KDF
   (`hashlib.pbkdf2_hmac`, PBKDF2-HMAC-SHA256): unique random salt per
   password, configurable iteration count stored with the hash, work-factor
   guidance documented (NIST SP 800-63B floor; OWASP 2023 recommendation).
4. **Symmetric encryption as authenticated encryption.** Encrypt-then-MAC:
   the tag covers nonce + associated data + ciphertext; tag verified
   *before* decryption; nonce discipline enforced in code (256-bit random
   nonce via `secrets`; accepted (key, nonce) replays rejected).
5. **Message authentication / "sign" workflow with key lifecycle.**
   HMAC-based, honestly labeled as symmetric MAC (NOT public-key
   signatures); workflow spans sign → verify → rotate → destroy.
6. **Certificate validation concepts.** Documented as a design pattern
   (checklist + classic failures) — design-only, not implemented, because
   stdlib has no X.509/public-key tooling and this project invents none.
7. **Key-management design.** Generation (`secrets`), storage tiers,
   rotation schedule, destruction procedure (wipe + tombstone), compromise
   response — implemented as a versioned SQLite registry + documented
   procedure (see ARCHITECTURE.md).
8. **Pitfalls catalog.** ECB, nonce reuse, hardcoded keys, home-rolled
   crypto, unauthenticated encryption, timing oracles, key reuse across
   purposes, never-rotated keys — each mapped to the demonstration that
   avoids it; each "DON'T" fixture fails closed.

## Non-functional requirements

- **Zero cost:** stdlib only at runtime; no network calls; SQLite.
- **Synthetic data only:** all keys, nonces, salts, messages invented.
- **Honest status labels:** `Implemented` / `Tested` for real primitives;
  `Educational` banner on the teaching construction; `Design` label on
  asymmetric/cert-validation material. Never imply production readiness.
- **Fail-closed misuse:** every misuse fixture (bad key, tampered tag,
  replayed nonce, destroyed key) raises — never returns silent wrong output.
- **Rollback:** migration down-step tested for real.

## Measurable criteria

| ID | Criterion | Target |
|---|---|---|
| M1 | Known-answer vectors pass | 100% (SHA-256 NIST; HMAC RFC 4231; PBKDF2 RFC 6070) |
| M2 | Tamper detection | 100% (flipped bit, modified/truncated tag, wrong key, AAD change, nonce swap) |
| M3 | Pitfall fixtures fail closed | Every one raises; zero silent wrong outputs |
| M4 | Key lifecycle | Rotation keeps old data readable; destruction refuses use; compromise re-encrypts |
| M5 | Rollback | `015_crypto.sql` down-step drops all S05 tables; re-apply is clean |
| M6 | No regressions | Full suite passes (1124 prior + new) |
