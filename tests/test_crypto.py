"""S05 Applied Cryptography — known-answer, tamper, misuse, and key-lifecycle tests.

Vector sources (cited in TEST_RESULTS.md):
  * SHA-256: NIST FIPS 180-4 ("" and "abc" vectors).
  * HMAC-SHA256: RFC 4231, test cases 1-4 (independently confirmed).
  * PBKDF2-HMAC-SHA1: RFC 6070, vectors 1 (c=1), 2 (c=2), 3 (c=4096).
  * PBKDF2-HMAC-SHA256: no RFC vector set exists; verified by an independent
    pure-Python RFC 2898 implementation written in this test file
    (cross-implementation check, honestly labeled).

All keys, nonces, salts, and messages are synthetic test data.
"""
import hashlib
import hmac
import struct

import pytest

from mavenu import crypto_demo as cd
from mavenu.db import get_connection, run_migrations, rollback_migration


# ---------------------------------------------------------------------------
# Independent re-implementations (cross-checks, not the module under test)
# ---------------------------------------------------------------------------
def _rfc2104_hmac_sha256(key: bytes, msg: bytes) -> bytes:
    """HMAC per RFC 2104 written independently of the `hmac` module."""
    block = 64
    if len(key) > block:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (block - len(key))
    o_key_pad = bytes(b ^ 0x5C for b in key)
    i_key_pad = bytes(b ^ 0x36 for b in key)
    return hashlib.sha256(o_key_pad + hashlib.sha256(i_key_pad + msg).digest()).digest()


def _rfc2898_pbkdf2(password: bytes, salt: bytes, iterations: int,
                    dklen: int, hashmod) -> bytes:
    """PBKDF2 per RFC 2898 written independently of hashlib.pbkdf2_hmac."""
    hlen = hashmod().digest_size

    def prf(data: bytes) -> bytes:
        return hmac.new(password, data, hashmod).digest()

    out = b""
    for block_index in range(1, -(-dklen // hlen) + 1):
        u = prf(salt + struct.pack(">I", block_index))
        t = int.from_bytes(u, "big")
        for _ in range(iterations - 1):
            u = prf(u)
            t ^= int.from_bytes(u, "big")
        out += t.to_bytes(hlen, "big")
    return out[:dklen]


# ---------------------------------------------------------------------------
# Known-answer: SHA-256 (NIST FIPS 180-4)
# ---------------------------------------------------------------------------
class TestSha256KnownAnswer:
    def test_empty_string(self):
        assert cd.sha256_hex(b"") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_abc(self):
        assert cd.sha256_hex(b"abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_rejects_non_bytes(self):
        with pytest.raises(TypeError):
            cd.sha256("abc")  # type: ignore[arg-type]

    def test_deterministic_and_32_bytes(self):
        d = cd.sha256(b"mavenu synthetic fixture")
        assert len(d) == 32 and d == cd.sha256(b"mavenu synthetic fixture")


# ---------------------------------------------------------------------------
# Known-answer: HMAC-SHA256 (RFC 4231, test cases 1-4)
# ---------------------------------------------------------------------------
RFC4231_CASES = [
    # (key, data, expected_hex, label)
    (bytes.fromhex("0b" * 20), b"Hi There",
     "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7",
     "TC1 short key"),
    (b"Jefe", b"what do ya want for nothing?",
     "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843",
     "TC2 ascii key"),
    (bytes.fromhex("aa" * 20), bytes.fromhex("dd" * 50),
     "773ea91e36800e46854db8ebd09181a72959098b3ef8c122d9635514ced565fe",
     "TC3 repeated data"),
    (bytes(range(1, 26)), bytes.fromhex("cd" * 50),
     "82558a389a443c0ea4cc819899f2083a85f0faa3e578f8077a2e3ff46729665b",
     "TC4 25-byte key"),
]


@pytest.mark.parametrize("key,data,expected,label",
                         [(k, d, e, l) for k, d, e, l in RFC4231_CASES],
                         ids=[c[3] for c in RFC4231_CASES])
def test_hmac_rfc4231_vectors(key, data, expected, label):
    assert cd.hmac_sha256_raw(key, data).hex() == expected


@pytest.mark.parametrize("key,data", [(c[0], c[1]) for c in RFC4231_CASES[:2]],
                         ids=["TC1", "TC2"])
def test_hmac_cross_check_independent_rfc2104(key, data):
    """Independent RFC 2104 implementation agrees with the module."""
    assert _rfc2104_hmac_sha256(key, data) == cd.hmac_sha256_raw(key, data)


class TestHmacVerify:
    def test_verify_roundtrip(self):
        key = cd.generate_key()
        tag = cd.hmac_sha256(key, b"message")
        assert cd.hmac_verify(key, b"message", tag) is True

    def test_verify_rejects_tampered_message(self):
        key = cd.generate_key()
        tag = cd.hmac_sha256(key, b"message")
        assert cd.hmac_verify(key, b"messagf", tag) is False

    def test_verify_rejects_wrong_tag_length(self):
        key = cd.generate_key()
        assert cd.hmac_verify(key, b"m", b"short") is False

    def test_mac_sign_verify_roundtrip(self):
        key = cd.generate_key()
        tag = cd.mac_sign(key, b"hello")
        assert cd.mac_verify(key, b"hello", tag) is True
        assert cd.mac_verify(key, b"hellp", tag) is False

    def test_mac_verify_rejects_malformed_hex(self):
        key = cd.generate_key()
        assert cd.mac_verify(key, b"hello", "not-hex!") is False

    def test_hmac_rejects_weak_key(self):
        with pytest.raises(cd.WeakKeyError):
            cd.hmac_sha256(b"password", b"message")


# ---------------------------------------------------------------------------
# Known-answer: PBKDF2-HMAC-SHA1 (RFC 6070)
# ---------------------------------------------------------------------------
RFC6070_CASES = [
    (b"password", b"salt", 1, 20,
     "0c60c80f961f0e71f3a9b524af6012062fe037a6"),
    (b"password", b"salt", 2, 20,
     "ea6c014dc72d6f8ccd1ed92ace1d41f0d8de8957"),
    (b"password", b"salt", 4096, 20,
     "4b007901b765489abead49d926f721d065a429c1"),
]


@pytest.mark.parametrize("pw,salt,iters,dklen,expected",
                         RFC6070_CASES,
                         ids=["RFC6070 c=1", "RFC6070 c=2", "RFC6070 c=4096"])
def test_pbkdf2_rfc6070_sha1_vectors(pw, salt, iters, dklen, expected):
    assert cd.pbkdf2_derive(pw, salt, iters, dklen, "sha1").hex() == expected


@pytest.mark.parametrize("pw,salt,iters,dklen", [
    (b"password", b"salt", 1, 32),
    (b"password", b"salt", 100, 32),
    (b"longer password value here", b"NaCl" * 8, 500, 64),  # multi-block dkLen
    (b"", b"salt", 100, 32),                               # empty password
    ("pässwörd-utf8".encode("utf-8"), b"salt", 100, 32),    # non-ASCII
], ids=["c=1", "c=100", "multi-block", "empty-pw", "utf8-pw"])
def test_pbkdf2_sha256_cross_implementation(pw, salt, iters, dklen):
    """No RFC vector set exists for PBKDF2-HMAC-SHA256; the module's output
    must match an independent RFC 2898 implementation written in this file."""
    assert cd.pbkdf2_derive(pw, salt, iters, dklen, "sha256") == \
        _rfc2898_pbkdf2(pw, salt, iters, dklen, hashlib.sha256)


class TestPasswordHashing:
    def test_hash_verify_roundtrip(self):
        stored = cd.hash_password("correct horse", iterations=1000)
        assert cd.verify_password("correct horse", stored) is True

    def test_wrong_password_rejected(self):
        stored = cd.hash_password("correct horse", iterations=1000)
        assert cd.verify_password("correct horsf", stored) is False

    def test_salts_are_random(self):
        a = cd.hash_password("same", iterations=1000)
        b = cd.hash_password("same", iterations=1000)
        assert a != b  # different salts -> different stored strings

    def test_iterations_stored_and_honored(self):
        stored = cd.hash_password("pw", iterations=1500)
        assert stored.startswith("$pbkdf2-sha256$1500$")
        assert cd.verify_password("pw", stored) is True

    def test_malformed_stored_string_fails_closed(self):
        assert cd.verify_password("pw", "not-a-hash") is False
        assert cd.verify_password("pw", "$pbkdf2-sha256$abc$zz$zz") is False

    def test_default_iterations_applied(self):
        stored = cd.hash_password("pw")
        assert stored.startswith("$pbkdf2-sha256$%d$" % cd.DEFAULT_PBKDF2_ITERATIONS)

    def test_explicit_salt_reproducible(self):
        salt = bytes.fromhex("00" * 16)
        a = cd.hash_password("pw", iterations=1000, salt=salt)
        b = cd.hash_password("pw", iterations=1000, salt=salt)
        assert a == b


# ---------------------------------------------------------------------------
# Key policy — DON'T fixtures that must fail closed
# ---------------------------------------------------------------------------
class TestKeyPolicy:
    def test_rejects_short_key(self):
        with pytest.raises(cd.WeakKeyError):
            cd.validate_key(b"short")

    def test_rejects_hardcoded_blocklisted_key(self):
        with pytest.raises(cd.WeakKeyError):
            cd.validate_key(b"password")

    def test_rejects_all_zero_key(self):
        with pytest.raises(cd.WeakKeyError):
            cd.validate_key(b"\x00" * 32)

    def test_rejects_repeated_byte_key(self):
        with pytest.raises(cd.WeakKeyError):
            cd.validate_key(b"\xaa" * 32)

    def test_rejects_non_bytes(self):
        with pytest.raises(cd.WeakKeyError):
            cd.validate_key("a-string-key")  # type: ignore[arg-type]

    def test_accepts_generated_key(self):
        key = cd.generate_key()
        assert len(key) == 32
        assert cd.validate_key(key) == key

    def test_refuses_to_generate_short_key(self):
        with pytest.raises(cd.WeakKeyError):
            cd.generate_key(nbytes=8)


# ---------------------------------------------------------------------------
# Educational encrypt-then-MAC — roundtrips, nonce discipline, tamper tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fresh_nonce_cache():
    cd._reset_nonce_cache_for_tests()
    yield
    cd._reset_nonce_cache_for_tests()


class TestEducationalCipher:
    def test_roundtrip(self):
        key = cd.generate_key()
        env = cd.encrypt(key, b"hello world")
        assert env["educational"] is True
        assert cd.decrypt(key, env) == b"hello world"

    @pytest.mark.parametrize("n", [0, 1, 31, 32, 1000])
    def test_roundtrip_lengths(self, n):
        key = cd.generate_key()
        pt = bytes(range(256)) * (n // 256 + 1)
        pt = pt[:n]
        assert cd.decrypt(key, cd.encrypt(key, pt)) == pt

    def test_nonces_are_random_256_bit(self):
        key = cd.generate_key()
        e1 = cd.encrypt(key, b"same")
        e2 = cd.encrypt(key, b"same")
        assert e1["nonce"] != e2["nonce"]
        assert len(bytes.fromhex(e1["nonce"])) == 32
        assert e1["ciphertext"] != e2["ciphertext"]

    def test_deterministic_with_fixed_nonce(self):
        key = cd.generate_key()
        nonce = bytes.fromhex("11" * 32)
        assert (cd.encrypt(key, b"x", nonce=nonce)["ciphertext"] ==
                cd.encrypt(key, b"x", nonce=nonce)["ciphertext"])

    def test_key_separation(self):
        enc, mac = cd.derive_enc_mac_keys(cd.generate_key())
        assert enc != mac and len(enc) == 32 and len(mac) == 32

    def test_aad_bound_to_envelope(self):
        key = cd.generate_key()
        env = cd.encrypt(key, b"data", associated_data=b"header")
        env2 = dict(env)
        env2["aad"] = b"other".hex()
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(key, env2)


class TestTamperDetection:
    """100% tamper detection: every corruption must raise, never decrypt."""

    def _flip(self, env, field):
        raw = bytearray(bytes.fromhex(env[field]))
        raw[0] ^= 1
        out = dict(env)
        out[field] = bytes(raw).hex()
        return out

    def test_flipped_ciphertext_bit_rejected(self):
        key = cd.generate_key()
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(key, self._flip(cd.encrypt(key, b"secret"), "ciphertext"))

    def test_modified_tag_rejected(self):
        key = cd.generate_key()
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(key, self._flip(cd.encrypt(key, b"secret"), "tag"))

    def test_truncated_tag_rejected(self):
        key = cd.generate_key()
        env = cd.encrypt(key, b"secret")
        env["tag"] = env["tag"][:32]
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(key, env)

    def test_wrong_key_rejected(self):
        env = cd.encrypt(cd.generate_key(), b"secret")
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(cd.generate_key(), env)

    def test_swapped_nonce_rejected(self):
        key = cd.generate_key()
        e1 = cd.encrypt(key, b"one")
        e2 = cd.encrypt(key, b"two")
        e1["nonce"] = e2["nonce"]
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(key, e1)

    def test_malformed_envelope_fails_closed(self):
        key = cd.generate_key()
        with pytest.raises(cd.CryptoError):
            cd.decrypt(key, {"nonce": "zz"})
        with pytest.raises(cd.CryptoError):
            cd.decrypt(key, "not-a-dict")  # type: ignore[arg-type]

    def test_weak_key_refused_at_encrypt_and_decrypt(self):
        env = cd.encrypt(cd.generate_key(), b"x")
        with pytest.raises(cd.WeakKeyError):
            cd.encrypt(b"password", b"x")
        with pytest.raises(cd.WeakKeyError):
            cd.decrypt(b"password", env)


class TestNonceDiscipline:
    def test_replay_of_accepted_envelope_rejected(self):
        key = cd.generate_key()
        env = cd.encrypt(key, b"payload")
        assert cd.decrypt(key, dict(env)) == b"payload"
        with pytest.raises(cd.NonceReusedError):
            cd.decrypt(key, dict(env))  # same (key, nonce) twice -> replay

    def test_same_nonce_different_key_not_replay(self):
        env = cd.encrypt(cd.generate_key(), b"payload")
        other = cd.generate_key()
        with pytest.raises(cd.TamperDetectedError):
            cd.decrypt(other, dict(env))  # wrong key, not a replay false-positive


class TestEcbPitfallFixture:
    def test_ecb_pattern_leaks_equality_illustrative(self):
        key = cd.generate_key()
        pt = b"A" * 32 + b"A" * 32 + b"B" * 32
        demo = cd.ecb_equality_demo(pt, key)
        assert demo["illustrative"] is True
        assert demo["plaintext_blocks_equal"] is True
        assert demo["ciphertext_blocks_equal"] is True  # the leak, shown plainly

    def test_real_construction_does_not_leak(self):
        key = cd.generate_key()
        pt = b"A" * 32 + b"A" * 32
        e = cd.encrypt(key, pt)
        ct = bytes.fromhex(e["ciphertext"])
        assert ct[:32] != ct[32:64]  # random nonce defeats the equality leak


# ---------------------------------------------------------------------------
# Key lifecycle — registry, rotation, destruction, compromise
# ---------------------------------------------------------------------------
@pytest.fixture
def migrated_conn(tmp_path):
    conn = get_connection(str(tmp_path / "crypto.db"))
    run_migrations(conn)
    assert "015_crypto.sql" in {r["name"] for r in
        conn.execute("SELECT name FROM schema_migrations").fetchall()}
    yield conn
    conn.close()


class TestKeyLifecycle:
    def test_create_and_store_read_message(self, migrated_conn):
        v = cd.create_key(migrated_conn, actor="test")
        assert v == 1
        mid = cd.store_message(migrated_conn, "test", b"hello")
        assert cd.read_message(migrated_conn, mid) == b"hello"

    def test_rotation_old_data_still_decrypts(self, migrated_conn):
        cd.create_key(migrated_conn, actor="test")
        mid = cd.store_message(migrated_conn, "test", b"before rotation")
        old_v, new_v = cd.rotate_key(migrated_conn, actor="test")
        assert (old_v, new_v) == (1, 2)
        assert cd.read_message(migrated_conn, mid) == b"before rotation"
        mid2 = cd.store_message(migrated_conn, "test", b"after rotation")
        assert cd.read_message(migrated_conn, mid2) == b"after rotation"
        inv = cd.key_inventory(migrated_conn)
        assert [k["status"] for k in inv] == ["retired", "active"]

    def test_destroyed_key_refuses_use(self, migrated_conn):
        cd.create_key(migrated_conn, actor="test")
        mid = cd.store_message(migrated_conn, "test", b"doomed")
        cd.destroy_key(migrated_conn, 1, actor="test")
        row = migrated_conn.execute(
            "SELECT key_hex, status FROM crypto_keys WHERE key_version=1").fetchone()
        assert row["status"] == "destroyed"
        assert row["key_hex"] == "00" * 32  # wiped
        with pytest.raises(cd.KeyDestroyedError):
            cd.read_message(migrated_conn, mid)

    def test_destroy_idempotent_rejected(self, migrated_conn):
        cd.create_key(migrated_conn, actor="test")
        cd.destroy_key(migrated_conn, 1, actor="test")
        with pytest.raises(cd.CryptoError):
            cd.destroy_key(migrated_conn, 1, actor="test")

    def test_compromise_response_rotates_and_reencrypts(self, migrated_conn):
        cd.create_key(migrated_conn, actor="test")
        mids = [cd.store_message(migrated_conn, "test", b"msg-%d" % i)
                for i in range(3)]
        report = cd.compromise_response(migrated_conn, 1, actor="test")
        assert report["rotated_to"] == 2
        assert report["reencrypted"] == 3
        assert report["skipped_destroyed"] == 0
        for i, mid in enumerate(mids):
            assert cd.read_message(migrated_conn, mid) == b"msg-%d" % i
        inv = cd.key_inventory(migrated_conn)
        assert [k["status"] for k in inv] == ["compromised", "active"]

    def test_reencrypt_skips_destroyed_key_messages(self, migrated_conn):
        cd.create_key(migrated_conn, actor="test")
        mid = cd.store_message(migrated_conn, "test", b"lost")
        cd.rotate_key(migrated_conn, actor="test")
        cd.destroy_key(migrated_conn, 1, actor="test")
        stats = cd.reencrypt_all(migrated_conn, actor="test")
        assert stats["reencrypted"] == 0
        assert stats["skipped_destroyed"] == 1

    def test_no_active_key_fails_closed(self, migrated_conn):
        with pytest.raises(cd.KeyNotFoundError):
            cd.store_message(migrated_conn, "test", b"x")

    def test_events_logged(self, migrated_conn):
        cd.create_key(migrated_conn, actor="tester")
        cd.rotate_key(migrated_conn, actor="tester")
        events = [r["event"] for r in migrated_conn.execute(
            "SELECT event FROM crypto_key_events ORDER BY id").fetchall()]
        assert "created" in events and "rotated" in events

    def test_actor_required(self, migrated_conn):
        with pytest.raises(cd.CryptoError):
            cd.create_key(migrated_conn, actor="")


class TestSignWorkflow:
    def test_full_workflow_steps(self, migrated_conn):
        steps = cd.demo_sign_workflow(migrated_conn, "test", b"contract v3")
        names = [s["step"] for s in steps]
        assert names == ["key-active", "sign", "verify", "tamper-check",
                         "rotate", "verify-retired", "destroy", "destroy-check"]
        assert "True" in steps[2]["detail"]
        assert "False" in steps[3]["detail"]  # tampered message must not verify
        assert "KeyDestroyedError" in steps[7]["detail"]


class TestCertDesignDoc:
    def test_design_is_labeled_not_code(self):
        d = cd.describe_cert_validation_design()
        assert d["status"].startswith("DESIGN ONLY")
        assert len(d["certificate_validation_checklist"]) == 8
        assert len(d["classic_failures"]) == 4


class TestMigrationRollback:
    def test_migration_rollback_for_real(self, tmp_path):
        conn = get_connection(str(tmp_path / "rollback.db"))
        try:
            applied = run_migrations(conn)
            assert "015_crypto.sql" in applied
            cd.create_key(conn, actor="rollback-test")
            cd.store_message(conn, "rollback-test", b"demo")
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"crypto_keys", "crypto_key_events",
                    "crypto_messages"} <= tables
            rollback_migration(conn, "015_crypto.sql")
            tables_after = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert not ({"crypto_keys", "crypto_key_events",
                         "crypto_messages"} & tables_after)
            reapplied = run_migrations(conn)
            assert "015_crypto.sql" in reapplied
            tables_re = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"crypto_keys", "crypto_key_events",
                    "crypto_messages"} <= tables_re
        finally:
            conn.close()
