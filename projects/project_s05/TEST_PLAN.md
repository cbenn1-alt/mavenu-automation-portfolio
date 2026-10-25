# S05 — Test Plan

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**

## Strategy

Three layers: **known-answer** (the primitives are correct),
**tamper/misuse** (misuse fails closed, never silently wrong), and
**lifecycle** (keys rotate, die, and recover properly). Plus API tests and
a real migration rollback test. All fixtures synthetic.

## Suites

### 1. Known-answer tests (`tests/test_crypto.py`)

| Area | Vectors | Source |
|---|---|---|
| SHA-256 `""`, `"abc"` | `e3b0c44…855`, `ba7816b…15ad` | NIST FIPS 180-4 |
| HMAC-SHA256 TC1–TC4 | 4 expected digests | RFC 4231 (independently confirmed against a second published constant set; TC1/TC2 also cross-checked with an independent RFC 2104 implementation in the test file) |
| PBKDF2-HMAC-SHA1 c=1,2,4096 | RFC vectors | RFC 6070 |
| PBKDF2-HMAC-SHA256 | cross-implementation | Independent pure-Python RFC 2898 implementation in the test file (c=1, c=100, multi-block dkLen, empty password, UTF-8 password). No RFC vector set exists — stated honestly. |

Acceptance: 100% pass (M1).

### 2. Tamper tests (M2 — 100% detection required)

Flipped ciphertext bit; modified tag; truncated tag; wrong key; swapped
nonce; AAD mismatch; malformed envelope (missing fields, non-dict). Each
must raise (`TamperDetectedError` / `CryptoError`) — decrypting tampered
input is the failure.

### 3. Misuse "DON'T" fixtures (M3 — all fail closed)

- Nonce reuse: decrypt the same accepted envelope twice → `NonceReusedError`
  (replay rejected).
- Hardcoded/weak keys: `b"password"`, 8-byte, all-zero, repeated-byte keys
  → `WeakKeyError` at every entry point (`hmac_sha256`, `encrypt`,
  `decrypt`, API).
- ECB pattern: `ecb_equality_demo()` (labeled illustrative) shows equal
  plaintext blocks → equal ciphertext blocks; the real `encrypt()` with a
  random nonce does not leak equality (asserted).
- Home-rolled temptation: documented in PITFALLS P-HOMEROLL + README ban;
  the "safe failure" is that the only custom construction is bannered
  EDUCATIONAL with a pointer to audited libraries.

### 4. Key lifecycle (M4)

Create → store/read message; rotation (old message still decrypts, new
messages use new key, inventory shows retired+active); destruction (stored
bytes zeroed, tombstoned, `read_message` raises `KeyDestroyedError`,
double-destroy rejected); compromise response (compromised → rotated →
3 messages re-encrypted and readable, statuses correct);
`reencrypt_all` skips destroyed-key messages and counts them; no active key
→ `KeyNotFoundError`; empty actor rejected. Sign workflow end-to-end:
sign → verify → tamper-check (False) → rotate → retired verifies →
destroy → destroyed refuses.

### 5. API tests (`tests/test_crypto_api.py`)

Page 200s with banners; guided demo POST; pitfalls catalog; hash/hmac
endpoints incl. 422 on bad hex and weak key; password endpoint (work-factor
floor 10,000 enforced); encrypt→decrypt roundtrip; tampered decrypt → 422
`auth_failed`; rotate→keys→destroy flow; cert-design endpoint labeled
DESIGN ONLY.

### 6. Rollback (M5)

`test_migration_rollback_for_real`: apply `015_crypto.sql` → tables exist
→ insert key + message → `rollback_migration("015_crypto.sql")` → all
three tables gone, migration record removed → `run_migrations()` re-applies
cleanly.

### 7. Regression (M6)

Full suite in 3 chunks (512 MB `/tmp` tmpfs fills on a single run; clear
`/tmp/pytest-of-root` between chunks; no disk-backed TMPDIR). All 1124
prior tests must pass unchanged.
