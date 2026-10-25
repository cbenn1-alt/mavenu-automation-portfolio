# S05 — Evidence Matrix

Every public claim → the test or artifact that backs it, or its honest label.

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | SHA-256 implemented via stdlib and correct | **Tested** | `tests/test_crypto.py::TestSha256KnownAnswer` — NIST FIPS 180-4 vectors `""`/`"abc"` pass |
| 2 | HMAC-SHA256 correct | **Tested** | RFC 4231 TC1–TC4 pass; TC1/TC2 cross-checked with an independent RFC 2104 implementation in the test file |
| 3 | PBKDF2 password hashing with work factor | **Tested** | RFC 6070 c=1/2/4096 pass (KDF plumbing); PBKDF2-HMAC-SHA256 cross-checked against independent RFC 2898 implementation; work-factor parameter stored + honored; salts random per password |
| 4 | 100% tamper detection | **Tested** | `TestTamperDetection` — 7/7 corruptions raise, 0 decrypt (TEST_RESULTS.md M2) |
| 5 | Encrypt-then-MAC with verify-before-decrypt ordering | **Implemented + Tested** | `decrypt()` order asserted by tamper suite; AAD binding test |
| 6 | Nonce discipline enforced in code | **Tested** | 256-bit `secrets` nonces; random per message; replay → `NonceReusedError` (`TestNonceDiscipline`) |
| 7 | Key separation (enc vs MAC subkeys) | **Tested** | `derive_enc_mac_keys` domain separation test |
| 8 | Key policy rejects weak/hardcoded keys | **Tested** | 5 policy fixtures → `WeakKeyError` at every entry point (`TestKeyPolicy`) |
| 9 | Rotation keeps old data readable | **Tested** | `test_rotation_old_data_still_decrypts` |
| 10 | Destruction wipes + tombstones, refuses use | **Tested** | `test_destroyed_key_refuses_use` — stored bytes zeroed, `KeyDestroyedError` |
| 11 | Compromise response rotates + re-encrypts | **Tested** | `test_compromise_response_rotates_and_reencrypts` — 3/3 messages re-encrypted |
| 12 | Pitfalls catalog maps mistakes to demos | **Implemented** | `PITFALLS` (8 entries) in `crypto_demo.py`; `/project_s05/pitfalls`; `/api/crypto/pitfalls` |
| 13 | ECB "DON'T" fixture visibly leaks, real construction doesn't | **Tested** | `TestEcbPitfallFixture` (labeled illustrative) |
| 14 | Constant-time comparisons used | **Implemented** | `hmac.compare_digest` in `hmac_verify`, `decrypt`, `mac_verify`, `verify_password` — SECURITY.md; no `==` on secrets |
| 15 | Asymmetric signatures + cert validation documented | **Design** (labeled, not code) | `CERT_DESIGN`, `describe_cert_validation_design()`, `/api/crypto/cert-design`, ARCHITECTURE.md |
| 16 | Educational cipher bannered, never production | **Implemented** | Banner in module docstring, envelope `warning` field, every web page, every API response; README forbids production use without expert review |
| 17 | Migration rollback tested for real | **Tested** | `test_migration_rollback_for_real` (2026-10-23, Python 3.12.3/pytest 9.1.1/Linux) |
| 18 | No regressions | **Tested** | 1124/1124 prior tests pass; total 1211 |
| 19 | All data synthetic | **Synthetic** | Tests, fixtures, registry rows, web demo — invented data only; no PII |
| 20 | Work-factor guidance (OWASP/NIST) | **Documented estimate/guidance** | Module §4 docstring + ARCHITECTURE.md; demo default 100,000; API floor 10,000 — labeled as guidance to calibrate, not a measured recommendation |
| 21 | Side-channel resistance on hardware | **NOT claimed** | SECURITY.md residual risk #4 — conceptual only, no hardware testing |
| 22 | Production readiness | **NOT claimed** | README "NOT claimed" row; SECURITY.md out-of-scope list |
