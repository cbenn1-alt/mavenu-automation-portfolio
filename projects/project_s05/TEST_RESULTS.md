# S05 — Test Results

**Run date:** 2026-10-23 (22:35 UTC)
**Environment:** Python 3.12.3 · pytest 9.1.1 · Linux · stdlib only at
runtime · SQLite
**Command:** `cd ~/workspace/mavenu-portfolio && .venv/bin/pytest tests/`
(run in 3 chunks with `/tmp/pytest-of-root` cleared between chunks — the
512 MB `/tmp` tmpfs fills during a single full-suite run; no disk-backed
TMPDIR used)

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**
> README forbids production use without expert review.

## Result

**1211 passed, 0 failed** — zero regressions.

| Suite | Tests | Result |
|---|---|---|
| S05 new (`tests/test_crypto.py`) | 73 | 73 passed |
| S05 new (`tests/test_crypto_api.py`) | 14 | 14 passed |
| P01 + P02 + Q01–Q10 + S01 + S02 prior (1124) | 1124 | 1124 passed, unchanged |

Chunk breakdown: 466 + 445 + 300 = 1211.

## Measurable criteria — verified

| Criterion (REQUIREMENTS.md) | Result |
|---|---|
| M1 — 100% known-answer pass | SHA-256 NIST vectors 2/2; HMAC RFC 4231 TC1–TC4 4/4 (+2 independent RFC 2104 cross-checks); PBKDF2 RFC 6070 3/3; PBKDF2-HMAC-SHA256 cross-implementation 5/5 — **Tested** |
| M2 — 100% tamper detection | Flipped bit, modified tag, truncated tag, wrong key, swapped nonce, AAD change, malformed envelope: 7/7 raise, 0 decrypt — **Tested** |
| M3 — every pitfall fixture fails closed | Nonce replay → `NonceReusedError`; weak keys → `WeakKeyError` (5 fixtures); ECB demo labeled illustrative and leaks visibly while real `encrypt()` does not; home-rolled temptation answered by banner + pointer — **Tested** |
| M4 — key lifecycle | Rotation: old data decrypts, inventory retired+active; destruction: bytes zeroed, tombstoned, use raises `KeyDestroyedError`; compromise: 3/3 messages re-encrypted under new key, statuses compromised+active; sign workflow 8/8 steps — **Tested** |
| M5 — rollback tested for real | `test_migration_rollback_for_real`: `015_crypto.sql` applied → 3 tables present → key + message inserted → `rollback_migration("015_crypto.sql")` → all three tables dropped and the `schema_migrations` record removed → `run_migrations()` re-applies `015_crypto.sql` cleanly — **Tested**, 2026-10-23, Python 3.12.3 / pytest 9.1.1 / Linux |
| M6 — no regressions | 1124/1124 prior tests pass unchanged — **Tested** |

## Vector sources (cited, verified before use)

- SHA-256 `""` / `"abc"`: NIST FIPS 180-4.
- HMAC-SHA256 test cases 1–4: RFC 4231 (M. Nystrom, Dec 2005). My first
  recalled constants were wrong for 3 of 4 cases — caught by the pre-flight
  check, corrected against two independent published constant sets, and
  TC1/TC2 additionally cross-checked with an independent RFC 2104
  implementation in the test file. Recorded here so the process is auditable.
- PBKDF2-HMAC-SHA1 c=1/2/4096: RFC 6070 (S. Josefsson, Jan 2011).
- PBKDF2-HMAC-SHA256: no RFC vector set exists (confirmed via published
  analysis); verified against an independent pure-Python RFC 2898
  implementation written in the test file — labeled cross-implementation,
  not external known-answer.

## Notes

- The key policy (16-byte minimum, blocklist) rightly rejects the 4-byte
  RFC 4231 keys, so known-answer tests use the documented KAT-only
  `hmac_sha256_raw()`; all application paths use the policy-enforced
  `hmac_sha256()`.
- The nonce replay cache is reset between tests (`_reset_nonce_cache_for_tests`);
  the tamper-demo path resets it before the tag-verification step so that
  step exercises the tag, not the replay check.
- One pre-existing behavior noted, not changed: `store_message()` logs a
  `created` event against the writing key version — acceptable for the demo
  audit trail.
