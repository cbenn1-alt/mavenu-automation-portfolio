"""S05 Applied Cryptography — correct-use demonstrations of established primitives.

================================================================================
 HONEST-STATUS BANNER (read before using anything in this module)
================================================================================
 REAL (implemented + tested): SHA-256 hashing, HMAC-SHA256 message
     authentication, and PBKDF2 password hashing — all via Python's standard
     library (hashlib, hmac, secrets). No primitives were invented.
 EDUCATIONAL-ONLY: the symmetric "cipher" in this module is a SHA-256
     counter-mode stream construction written ONLY to teach nonce discipline
     and the encrypt-then-MAC pattern. It is NOT an audited cipher, has NOT
     been reviewed by a cryptographer, and MUST NEVER be used in production.
     Real systems must use an audited library (e.g. AES-GCM via the
     `cryptography` package). Every encrypt/decrypt entry point re-states
     this. See docs: projects/project_s05/SECURITY.md.
 DESIGN-ONLY: asymmetric (public-key) signatures and X.509 certificate
     validation are documented as design patterns in the S05 docs — they are
     NOT implemented in code. The "sign" workflow here is HMAC-based message
     authentication (symmetric MAC), honestly labeled as such.
 SYNTHETIC: every key, nonce, salt, and message in tests, fixtures, and the
     web demo is generated test data. Nothing here touches real users,
     real systems, or real secrets.
 NOT CLAIMED: this is not a crypto library, not production deployment, not
     side-channel tested on hardware, and not endorsed by any employer or
     platform.
================================================================================

Each demonstration is paired with the classic failure mode it prevents;
see PITFALLS and projects/project_s05/pitfalls documentation.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

EDUCATIONAL_BANNER = (
    "EDUCATIONAL ONLY — NOT PRODUCTION CRYPTO. "
    "The symmetric construction in this module is a teaching aid for nonce "
    "discipline and encrypt-then-MAC. Real systems must use an audited "
    "library (e.g. AES-GCM via the `cryptography` package). "
    "README forbids production use without expert review."
)

KEY_BYTES = 32          # 256-bit keys for the educational construction
NONCE_BYTES = 32        # 256-bit random nonce per encryption
TAG_BYTES = 32          # HMAC-SHA256 tag
SALT_BYTES = 16         # 128-bit password salt
DKLEN_PASSWORD = 32     # 256-bit password hash output
DEFAULT_PBKDF2_ITERATIONS = 100_000  # demo default; calibrate up for real use
MIN_PBKDF2_ITERATIONS = 1            # hard floor for the API; see docs for guidance


# --------------------------------------------------------------------------
# Errors — every misuse fails closed (exceptions, never silent wrong output)
# --------------------------------------------------------------------------
class CryptoError(Exception):
    """Base class: any cryptographic failure raises, never returns garbage."""


class TamperDetectedError(CryptoError):
    """Authentication tag did not verify — ciphertext rejected."""


class NonceReusedError(CryptoError):
    """A (key, nonce) pair was seen before — replay rejected."""


class WeakKeyError(CryptoError):
    """Key policy rejected the key material."""


class KeyNotFoundError(CryptoError):
    """No live key exists for the requested version."""


class KeyDestroyedError(CryptoError):
    """The key was destroyed (wiped + tombstoned) — use is refused."""


# --------------------------------------------------------------------------
# 1. Hashing — SHA-256 (stdlib hashlib)
# Failure mode it prevents: silent corruption / integrity loss.
# Hashing is NOT encryption: it is one-way, deterministic, and unkeyed.
# --------------------------------------------------------------------------
def sha256(data: bytes) -> bytes:
    """SHA-256 digest of bytes. Raises TypeError on non-bytes (fail closed)."""
    if not isinstance(data, bytes):
        raise TypeError("sha256() requires bytes, got %s" % type(data).__name__)
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return sha256(data).hex()


# --------------------------------------------------------------------------
# 2. Message authentication — HMAC-SHA256 (stdlib hmac)
# Failure mode it prevents: undetected tampering; naive hash(key||msg)
# constructions (length-extension). Verification ALWAYS uses
# hmac.compare_digest (constant-time); plain == is never used here.
# --------------------------------------------------------------------------
def hmac_sha256_raw(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA256 WITHOUT the key policy — for known-answer testing of the
    primitive itself (RFC vectors use 4-byte keys the policy rejects).
    Application code must use hmac_sha256() (policy-enforced), never this."""
    if not isinstance(key, bytes) or not isinstance(message, bytes):
        raise TypeError("hmac_sha256_raw() requires bytes")
    return hmac.new(key, message, hashlib.sha256).digest()


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA256 tag. Key must pass the key policy."""
    validate_key(key, purpose="hmac")
    if not isinstance(message, bytes):
        raise TypeError("hmac_sha256() requires bytes message")
    return hmac_sha256_raw(key, message)


def hmac_sha256_hex(key: bytes, message: bytes) -> str:
    return hmac_sha256(key, message).hex()


def hmac_verify(key: bytes, message: bytes, expected_tag: bytes) -> bool:
    """Constant-time tag verification. False on mismatch — never raises for
    a wrong tag, so callers cannot learn tag bytes from timing."""
    validate_key(key, purpose="hmac")
    if not isinstance(expected_tag, (bytes, bytearray)) or len(expected_tag) != TAG_BYTES:
        return False
    actual = hmac.new(key, message, hashlib.sha256).digest()
    return hmac.compare_digest(actual, bytes(expected_tag))


# --------------------------------------------------------------------------
# 3. Key policy — reject hardcoded / weak keys at the boundary
# Failure mode it prevents: keys like b"password" or 8-byte keys shipping
# to production. The policy is enforced in code, not in comments.
# --------------------------------------------------------------------------
WEAK_KEY_BLOCKLIST = frozenset({
    b"password", b"secret", b"12345678", b"changeme", b"letmein", b"qwerty",
    b"key", b"test", b"demo", b"abcdefgh", b"testkey", b"0123456789abcdef",
    b"supersecret", b"admin", b"hunter2",
})
MIN_KEY_BYTES = 16


def validate_key(key: Any, purpose: str = "general") -> bytes:
    """Fail-closed key policy. Returns the key bytes on success."""
    if not isinstance(key, (bytes, bytearray)):
        raise WeakKeyError("key for %s must be bytes, got %s"
                           % (purpose, type(key).__name__))
    key = bytes(key)
    if len(key) < MIN_KEY_BYTES:
        raise WeakKeyError("key for %s too short: %d bytes (minimum %d)"
                           % (purpose, len(key), MIN_KEY_BYTES))
    if key in WEAK_KEY_BLOCKLIST or key.lower() in WEAK_KEY_BLOCKLIST:
        raise WeakKeyError("key for %s matches a known-weak hardcoded value" % purpose)
    if key == b"\x00" * len(key):
        raise WeakKeyError("key for %s is all zeros" % purpose)
    if key == key[:1] * len(key):
        raise WeakKeyError("key for %s is a single repeated byte" % purpose)
    return key


def generate_key(nbytes: int = KEY_BYTES, purpose: str = "general") -> bytes:
    """Generate a key with the OS CSPRNG (secrets). Never use random()."""
    if nbytes < MIN_KEY_BYTES:
        raise WeakKeyError("refusing to generate a %d-byte key" % nbytes)
    return validate_key(secrets.token_bytes(nbytes), purpose=purpose)


# --------------------------------------------------------------------------
# 4. Password hashing — PBKDF2-HMAC (stdlib hashlib.pbkdf2_hmac)
# Failure mode it prevents: fast unsalted hashes (MD5/SHA-256 of the raw
# password) that fall to rainbow tables / GPU brute force. PBKDF2 applies a
# unique random salt per password and a configurable work factor.
#
# Work-factor guidance (documented, not enforced as law — calibrate to your
# hardware): OWASP 2023 recommends ~600,000 iterations for PBKDF2-HMAC-SHA256;
# NIST SP 800-63B sets a 10,000-iteration floor. The demo default is 100,000
# so the test suite stays fast; production deployments must calibrate to
# their latency budget and store the iteration count with the hash so it can
# be raised later without breaking existing verifications.
# --------------------------------------------------------------------------
def pbkdf2_derive(password: bytes, salt: bytes, iterations: int,
                  dklen: int, hash_name: str = "sha256") -> bytes:
    """Thin validated wrapper over hashlib.pbkdf2_hmac (for known-answer tests)."""
    if hash_name not in ("sha1", "sha256"):
        raise CryptoError("unsupported PRF: %s" % hash_name)
    if not isinstance(password, bytes) or not isinstance(salt, bytes):
        raise TypeError("password and salt must be bytes")
    if iterations < MIN_PBKDF2_ITERATIONS:
        raise CryptoError("iterations below minimum (%d)" % MIN_PBKDF2_ITERATIONS)
    if not (16 <= dklen <= 64):
        raise CryptoError("dklen out of range [16, 64]")
    return hashlib.pbkdf2_hmac(hash_name, password, salt, iterations, dklen)


def hash_password(password: str, *,
                  iterations: int = DEFAULT_PBKDF2_ITERATIONS,
                  salt: Optional[bytes] = None) -> str:
    """Hash a password for storage. Returns a versioned, self-describing string."""
    if not isinstance(password, str) or not password:
        raise CryptoError("password must be a non-empty string")
    if iterations < MIN_PBKDF2_ITERATIONS:
        raise CryptoError("iterations below minimum")
    salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
    if len(salt) < 8:
        raise CryptoError("salt too short")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                             iterations, DKLEN_PASSWORD)
    return "$pbkdf2-sha256$%d$%s$%s" % (iterations, salt.hex(), dk.hex())


def verify_password(password: str, stored: str) -> bool:
    """Constant-time password verification. False on any mismatch or
    malformed stored string (fail closed, no exception leakage)."""
    try:
        parts = stored.split("$")
        if len(parts) != 5 or parts[1] != "pbkdf2-sha256":
            return False
        iterations = int(parts[2])
        salt = bytes.fromhex(parts[3])
        expected = bytes.fromhex(parts[4])
    except (ValueError, AttributeError):
        return False
    if not isinstance(password, str):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                    iterations, len(expected))
    return hmac.compare_digest(candidate, expected)


# --------------------------------------------------------------------------
# 5. Educational symmetric construction — SHA-256 counter-mode stream +
#    encrypt-then-MAC. EDUCATIONAL ONLY (see module banner). Demonstrates:
#    nonce discipline (256-bit random nonce, reuse rejected), key separation
#    (distinct enc/MAC keys derived from one master), and verify-before-
#    decrypt ordering. Real use: AES-GCM via an audited library.
# --------------------------------------------------------------------------
_EDU_DOMAIN = b"MAVENU-S05-EDU-CTR-v1"


def _keystream_block(key: bytes, nonce: bytes, counter: int) -> bytes:
    return hashlib.sha256(
        _EDU_DOMAIN + key + nonce + counter.to_bytes(8, "big")).digest()


def _xor_keystream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 32):
        block = _keystream_block(key, nonce, i // 32)
        chunk = data[i:i + 32]
        out.extend(b ^ k for b, k in zip(chunk, block))
    return bytes(out)


def derive_enc_mac_keys(master_key: bytes) -> Tuple[bytes, bytes]:
    """Key separation: one master key -> distinct encryption and MAC keys.
    Failure mode it prevents: using the same key for two purposes, which can
    break the security arguments of both constructions."""
    validate_key(master_key, purpose="master")
    enc_key = hmac.new(master_key, b"mavenu-s05-edu-enc", hashlib.sha256).digest()
    mac_key = hmac.new(master_key, b"mavenu-s05-edu-mac", hashlib.sha256).digest()
    return enc_key, mac_key


def _mac_input(nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    # Length-prefix each field so concatenations cannot collide.
    def lp(b: bytes) -> bytes:
        return len(b).to_bytes(8, "big") + b
    return lp(nonce) + lp(aad) + lp(ciphertext)


# Module-level replay cache: (sha256(master_key), nonce) pairs already
# accepted by decrypt(). Replays of a previously accepted envelope raise
# NonceReusedError instead of decrypting again. (Session-scoped, demo-grade;
# a real system would persist this with the key registry.)
_SEEN_NONCES: set = set()


def _reset_nonce_cache_for_tests() -> None:
    _SEEN_NONCES.clear()


def encrypt(master_key: bytes, plaintext: bytes, *,
            nonce: Optional[bytes] = None,
            associated_data: bytes = b"") -> Dict[str, str]:
    """EDUCATIONAL encrypt-then-MAC. Returns a JSON-friendly envelope.

    Failure modes prevented: (a) unauthenticated encryption — the tag covers
    nonce + associated data + ciphertext, and decrypt() verifies it BEFORE
    touching the plaintext; (b) IV/nonce reuse — the nonce is 256-bit random
    from secrets unless the caller supplies one explicitly (tests only).
    """
    validate_key(master_key, purpose="encryption-master")
    if not isinstance(plaintext, bytes):
        raise TypeError("plaintext must be bytes")
    if not isinstance(associated_data, bytes):
        raise TypeError("associated_data must be bytes")
    if nonce is None:
        nonce = secrets.token_bytes(NONCE_BYTES)
    if not isinstance(nonce, bytes) or len(nonce) != NONCE_BYTES:
        raise CryptoError("nonce must be %d random bytes" % NONCE_BYTES)
    enc_key, mac_key = derive_enc_mac_keys(master_key)
    ciphertext = _xor_keystream(enc_key, nonce, plaintext)
    tag = hmac.new(mac_key, _mac_input(nonce, associated_data, ciphertext),
                   hashlib.sha256).digest()
    return {
        "construction": "EDU-SHA256-CTR-HMAC",
        "educational": True,
        "warning": EDUCATIONAL_BANNER,
        "nonce": nonce.hex(),
        "aad": associated_data.hex(),
        "ciphertext": ciphertext.hex(),
        "tag": tag.hex(),
    }


def decrypt(master_key: bytes, envelope: Dict[str, str]) -> bytes:
    """EDUCATIONAL decrypt. Verify-then-decrypt; any failure raises.

    Order matters: (1) structural validation, (2) replay check, (3) tag
    verification with compare_digest, (4) only then keystream XOR. A tampered
    envelope never yields partially-decrypted output."""
    validate_key(master_key, purpose="encryption-master")
    if not isinstance(envelope, dict):
        raise CryptoError("envelope must be a dict")
    try:
        nonce = bytes.fromhex(envelope["nonce"])
        aad = bytes.fromhex(envelope.get("aad", ""))
        ciphertext = bytes.fromhex(envelope["ciphertext"])
        tag = bytes.fromhex(envelope["tag"])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise CryptoError("malformed envelope: %s" % exc) from exc
    if len(tag) != TAG_BYTES:
        raise TamperDetectedError("tag length wrong")
    key_id = sha256(master_key).hex()
    if (key_id, nonce.hex()) in _SEEN_NONCES:
        raise NonceReusedError("this (key, nonce) pair was already accepted — "
                               "replay rejected")
    enc_key, mac_key = derive_enc_mac_keys(master_key)
    expected = hmac.new(mac_key, _mac_input(nonce, aad, ciphertext),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise TamperDetectedError("authentication tag mismatch — envelope rejected")
    _SEEN_NONCES.add((key_id, nonce.hex()))
    return _xor_keystream(enc_key, nonce, ciphertext)


# --------------------------------------------------------------------------
# 6. Symmetric message authentication ("sign" workflow for the demo)
# HONEST LABEL: this is a symmetric MAC, NOT a public-key digital signature.
# Anyone holding the key can both sign and verify — unlike asymmetric
# signatures, it provides no non-repudiation. The asymmetric sign/verify +
# certificate-validation pattern is documented as DESIGN ONLY in the S05
# docs (see ARCHITECTURE.md "asymmetric design pattern" and CERT_DESIGN).
# --------------------------------------------------------------------------
def mac_sign(key: bytes, message: bytes) -> str:
    """Create an authentication tag (symmetric MAC — not a public-key signature)."""
    return hmac_sha256(key, message).hex()


def mac_verify(key: bytes, message: bytes, tag_hex: str) -> bool:
    """Verify an authentication tag in constant time."""
    try:
        tag = bytes.fromhex(tag_hex)
    except (ValueError, TypeError):
        return False
    return hmac_verify(key, message, tag)


# --------------------------------------------------------------------------
# 7. Pitfalls catalog — each classic mistake mapped to the demo that avoids it
# --------------------------------------------------------------------------
PITFALLS: List[Dict[str, str]] = [
    {
        "id": "P-ECB",
        "title": "ECB mode / block-independent encryption leaks equality",
        "the_mistake": "Encrypting each block independently (the ECB pattern) so "
                       "identical plaintext blocks produce identical ciphertext blocks.",
        "how_it_fails": "An attacker sees which blocks repeat — structure, "
                        "headers, and repeated fields leak without breaking any key.",
        "avoided_by": "The S05 construction encrypts a single stream with a "
                      "per-message random nonce; ecb_equality_demo() below shows "
                      "the ECB pattern's leak side-by-side (labeled illustrative).",
    },
    {
        "id": "P-NONCE",
        "title": "Nonce / IV reuse destroys a stream cipher",
        "the_mistake": "Reusing a nonce with the same key (hardcoded IV, counter "
                       "reset) lets an attacker XOR two ciphertexts and cancel the "
                       "keystream, recovering plaintext.",
        "how_it_fails": "c1 XOR c2 = p1 XOR p2 — classic two-time-pad break.",
        "avoided_by": "encrypt() draws a 256-bit nonce from secrets per message; "
                      "decrypt() rejects any (key, nonce) replay with NonceReusedError.",
    },
    {
        "id": "P-HARDCODE",
        "title": "Hardcoded / weak keys",
        "the_mistake": "Keys like b\"password\" or 8-byte keys committed to source "
                       "control — found by grep, not by cryptanalysis.",
        "how_it_fails": "Total, silent compromise of everything 'protected'.",
        "avoided_by": "validate_key() blocklists known-weak values and enforces a "
                      "16-byte minimum; every entry point calls it (fail closed).",
    },
    {
        "id": "P-HOMEROLL",
        "title": "Home-rolled / 'improved' ciphers",
        "the_mistake": "Inventing a cipher, 'improving' AES, or stacking hashes "
                       "and calling it encryption.",
        "how_it_fails": "Unreviewed constructions fail in ways their authors "
                        "cannot see; there is no security argument to check.",
        "avoided_by": "This module invents nothing: SHA-256, HMAC, PBKDF2 from "
                      "stdlib. The one teaching construction is bannered "
                      "EDUCATIONAL on every surface with a pointer to audited "
                      "libraries — never presented as safe for production.",
    },
    {
        "id": "P-UNAUTH",
        "title": "Encryption without authentication",
        "the_mistake": "Decrypting ciphertext that was never authenticated — "
                       "bit-flipping attacks silently alter the plaintext.",
        "how_it_fails": "Attacker flips ciphertext bits to flip predictable "
                        "plaintext bits (e.g. amounts, flags).",
        "avoided_by": "encrypt-then-MAC: the tag covers nonce + AAD + "
                      "ciphertext; decrypt() verifies BEFORE decrypting.",
    },
    {
        "id": "P-TIMING",
        "title": "Non-constant-time comparison leaks the tag/key",
        "the_mistake": "Comparing MACs or password hashes with == lets an "
                       "attacker measure response time and recover bytes one at a time.",
        "how_it_fails": "Timing oracle: each correct byte measurably shortens "
                        "the comparison.",
        "avoided_by": "hmac.compare_digest() in hmac_verify(), decrypt(), "
                      "mac_verify(), and verify_password().",
    },
    {
        "id": "P-KEYREUSE",
        "title": "One key, two jobs",
        "the_mistake": "Using the same key for encryption and authentication (or "
                       "across protocols) — interactions can void both guarantees.",
        "how_it_fails": "Cross-protocol and composition attacks.",
        "avoided_by": "derive_enc_mac_keys() derives domain-separated enc/MAC "
                      "subkeys from each master key.",
    },
    {
        "id": "P-NOROTATE",
        "title": "Keys that never rotate / cannot be destroyed",
        "the_mistake": "A single eternal key: compromise is total and "
                       "irreversible, and there is no procedure for either.",
        "how_it_fails": "Breach scope is 'everything, forever'.",
        "avoided_by": "Versioned key registry (crypto_keys): rotation keeps old "
                      "data readable, destruction wipes + tombstones, compromise "
                      "triggers rotate + re-encrypt. See keymgmt demo below.",
    },
]


def ecb_equality_demo(plaintext: bytes, key: bytes) -> Dict[str, Any]:
    """ILLUSTRATIVE — demonstrates WHY the ECB pattern is broken.

    Encrypts each 32-byte block 'independently' (fixed zero nonce per block)
    to show that equal plaintext blocks yield equal ciphertext blocks.
    Labeled illustrative: this is the DON'T fixture. Real code must never do
    this; use the nonce-carrying encrypt() above (educational) or AES-GCM.
    """
    validate_key(key, purpose="ecb-demo")
    if len(plaintext) % 32 != 0 or not plaintext:
        raise CryptoError("demo needs non-empty input, multiple of 32 bytes")
    enc_key, _ = derive_enc_mac_keys(key)
    zero_nonce = b"\x00" * NONCE_BYTES
    blocks = [plaintext[i:i + 32] for i in range(0, len(plaintext), 32)]
    ct_blocks = [_xor_keystream(enc_key, zero_nonce, b) for b in blocks]
    leak = any(ct_blocks[i] == ct_blocks[j]
               for i in range(len(blocks)) for j in range(i + 1, len(blocks)))
    return {
        "illustrative": True,
        "warning": "DON'T fixture: the ECB pattern leaks plaintext equality. "
                   "Never encrypt blocks independently.",
        "plaintext_blocks_equal": any(blocks[i] == blocks[j]
                                      for i in range(len(blocks))
                                      for j in range(i + 1, len(blocks))),
        "ciphertext_blocks_equal": leak,
        "ciphertext_hex": [b.hex() for b in ct_blocks],
    }


# --------------------------------------------------------------------------
# 8. Asymmetric signatures + certificate validation — DESIGN ONLY
# Implemented as documentation because stdlib has no public-key signatures.
# A real implementation would use an audited library; the pattern below is
# what correct usage looks like. Labeled design-not-code everywhere.
# --------------------------------------------------------------------------
CERT_DESIGN: Dict[str, Any] = {
    "status": "DESIGN ONLY — not implemented in code",
    "asymmetric_sign_verify_pattern": [
        "Generate keypair with an audited library (e.g. Ed25519 via the "
        "`cryptography` package); private key in an HSM/KMS, never in code.",
        "Sign: signature = sign(private_key, message); ship (message, signature).",
        "Verify: verify(public_key, message, signature) -> accept/reject. "
        "Verification needs ONLY the public key — unlike HMAC, the verifier "
        "cannot forge signatures (non-repudiation).",
        "Always verify before use; fail closed on any verification error.",
    ],
    "certificate_validation_checklist": [
        "1. Build the chain: leaf -> intermediate(s) -> trusted root in the "
        "local trust store. Reject chains that do not terminate at a trusted root.",
        "2. Verify every signature in the chain with the issuer's public key.",
        "3. Check validity window: not-before <= now <= not-after (UTC, "
        "with clock-skew tolerance documented, not silently widened).",
        "4. Check revocation: OCSP preferred, CRL fallback; define the "
        "fail-open vs fail-closed policy explicitly (fail closed for sensitive use).",
        "5. Check name binding: the certificate's SAN/CN must match the "
        "entity you think you are talking to (hostname verification).",
        "6. Check key usage / extended key usage extensions match the operation.",
        "7. Pin or whitelist expected issuers where the peer set is known "
        "(reduces CA-compromise blast radius).",
        "8. Log validation failures with the chain presented; never retry "
        "with validation disabled ('just this once' is the classic failure).",
    ],
    "classic_failures": [
        "Skipping validation in dev and shipping the skip to prod.",
        "Accepting any certificate signed by any trusted CA for a pinned peer.",
        "Ignoring expiry/revocation because 'it worked yesterday'.",
        "Hostname check disabled to make a test pass.",
    ],
}


def describe_cert_validation_design() -> Dict[str, Any]:
    """Return the design-only certificate-validation pattern (not code)."""
    return dict(CERT_DESIGN)


# --------------------------------------------------------------------------
# 9. Key lifecycle — versioned registry in SQLite
# Generation (secrets) -> active use -> rotation (old data still readable) ->
# compromise response (rotate + re-encrypt) -> destruction (wipe + tombstone).
# Tables live in migration 015_crypto.sql. All demo keys are synthetic.
# --------------------------------------------------------------------------
def create_key(conn: sqlite3.Connection, actor: str, note: str = "") -> int:
    """Generate a new key version and make it the active one."""
    if not actor:
        raise CryptoError("actor is required")
    row = conn.execute(
        "SELECT COALESCE(MAX(key_version), 0) AS m FROM crypto_keys").fetchone()
    version = int(row["m"]) + 1
    key_hex = generate_key(KEY_BYTES, purpose="registry").hex()
    conn.execute(
        "INSERT INTO crypto_keys (key_version, key_hex, status, created_at, note)"
        " VALUES (?, ?, 'active', ?, ?)",
        (version, key_hex, _now(), note))
    conn.execute(
        "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
        " VALUES (?, 'created', ?, ?, ?)",
        (version, actor, "synthetic demo key (test-only)", _now()))
    # Only one active key at a time: any previous 'active' becomes retired.
    conn.execute(
        "UPDATE crypto_keys SET status='retired', rotated_at=? "
        "WHERE status='active' AND key_version < ?", (_now(), version))
    conn.commit()
    return version


def get_active_key(conn: sqlite3.Connection) -> Tuple[int, bytes]:
    row = conn.execute(
        "SELECT key_version, key_hex FROM crypto_keys WHERE status='active' "
        "ORDER BY key_version DESC LIMIT 1").fetchone()
    if row is None:
        raise KeyNotFoundError("no active key in registry")
    return int(row["key_version"]), bytes.fromhex(row["key_hex"])


def _load_live_key(conn: sqlite3.Connection, version: int) -> bytes:
    row = conn.execute(
        "SELECT key_hex, status FROM crypto_keys WHERE key_version=?",
        (version,)).fetchone()
    if row is None:
        raise KeyNotFoundError("key version %d not found" % version)
    if row["status"] == "destroyed":
        raise KeyDestroyedError("key version %d was destroyed — use refused" % version)
    return bytes.fromhex(row["key_hex"])


def rotate_key(conn: sqlite3.Connection, actor: str) -> Tuple[int, int]:
    """Rotate: retire the current active key, create a new active version.
    Old data remains decryptable (retired keys are live for decryption)."""
    if not actor:
        raise CryptoError("actor is required")
    old = conn.execute(
        "SELECT key_version FROM crypto_keys WHERE status='active' "
        "ORDER BY key_version DESC LIMIT 1").fetchone()
    old_version = int(old["key_version"]) if old else 0
    new_version = create_key(conn, actor, note="rotation")
    if old_version:
        conn.execute(
            "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
            " VALUES (?, 'rotated', ?, ?, ?)",
            (old_version, actor, "retired by rotation to v%d" % new_version, _now()))
        conn.execute(
            "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
            " VALUES (?, 'rotated', ?, ?, ?)",
            (new_version, actor, "activated by rotation from v%d" % old_version, _now()))
        conn.commit()
    return old_version, new_version


def destroy_key(conn: sqlite3.Connection, version: int, actor: str) -> None:
    """Destruction = cryptographic wipe (overwrite stored bytes with zeros) +
    tombstone (status='destroyed'). Decryption with this version refuses."""
    if not actor:
        raise CryptoError("actor is required")
    row = conn.execute(
        "SELECT status FROM crypto_keys WHERE key_version=?", (version,)).fetchone()
    if row is None:
        raise KeyNotFoundError("key version %d not found" % version)
    if row["status"] == "destroyed":
        raise CryptoError("key version %d already destroyed" % version)
    conn.execute(
        "UPDATE crypto_keys SET key_hex=?, status='destroyed', rotated_at=? "
        "WHERE key_version=?", ("00" * KEY_BYTES, _now(), version))
    conn.execute(
        "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
        " VALUES (?, 'destroyed', ?, ?, ?)",
        (version, actor, "key material wiped (zeros), tombstoned", _now()))
    conn.commit()


def compromise_key(conn: sqlite3.Connection, version: int, actor: str) -> None:
    """Mark a version compromised (suspected/confirmed key exposure)."""
    row = conn.execute(
        "SELECT status FROM crypto_keys WHERE key_version=?", (version,)).fetchone()
    if row is None:
        raise KeyNotFoundError("key version %d not found" % version)
    if row["status"] in ("destroyed",):
        raise CryptoError("cannot mark a destroyed key compromised")
    conn.execute("UPDATE crypto_keys SET status='compromised' WHERE key_version=?",
                 (version,))
    conn.execute(
        "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
        " VALUES (?, 'compromised', ?, ?, ?)",
        (version, actor, "suspected exposure; rotate + re-encrypt required", _now()))
    conn.commit()


def store_message(conn: sqlite3.Connection, actor: str, plaintext: bytes) -> int:
    """Encrypt with the active key and store the envelope (demo message store)."""
    version, key = get_active_key(conn)
    env = encrypt(key, plaintext)
    cur = conn.execute(
        "INSERT INTO crypto_messages (key_version, nonce_hex, ct_hex, tag_hex, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (version, env["nonce"], env["ciphertext"], env["tag"], _now()))
    conn.execute(
        "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
        " VALUES (?, 'created', ?, ?, ?)",
        (version, actor, "message %d encrypted under v%d" % (cur.lastrowid, version),
         _now()))
    conn.commit()
    return int(cur.lastrowid)


def read_message(conn: sqlite3.Connection, message_id: int) -> bytes:
    """Decrypt a stored message with the key version recorded at write time."""
    row = conn.execute(
        "SELECT key_version, nonce_hex, ct_hex, tag_hex FROM crypto_messages "
        "WHERE id=?", (message_id,)).fetchone()
    if row is None:
        raise CryptoError("message %d not found" % message_id)
    key = _load_live_key(conn, int(row["key_version"]))  # refuses destroyed
    return decrypt(key, {
        "nonce": row["nonce_hex"], "aad": "",
        "ciphertext": row["ct_hex"], "tag": row["tag_hex"],
    })


def reencrypt_all(conn: sqlite3.Connection, actor: str) -> Dict[str, int]:
    """Re-encrypt every stored message under the current active key.
    Messages under destroyed keys cannot be recovered — counted as skipped."""
    active_version, active_key = get_active_key(conn)
    rows = conn.execute(
        "SELECT id, key_version, nonce_hex, ct_hex, tag_hex FROM crypto_messages"
    ).fetchall()
    reencrypted = 0
    skipped = 0
    for r in rows:
        if int(r["key_version"]) == active_version:
            continue
        try:
            old_key = _load_live_key(conn, int(r["key_version"]))
            pt = decrypt(old_key, {
                "nonce": r["nonce_hex"], "aad": "",
                "ciphertext": r["ct_hex"], "tag": r["tag_hex"]})
        except (KeyDestroyedError, TamperDetectedError, NonceReusedError, CryptoError):
            skipped += 1
            continue
        env = encrypt(active_key, pt)
        conn.execute(
            "UPDATE crypto_messages SET key_version=?, nonce_hex=?, ct_hex=?, "
            "tag_hex=? WHERE id=?",
            (active_version, env["nonce"], env["ciphertext"], env["tag"], r["id"]))
        reencrypted += 1
    conn.execute(
        "INSERT INTO crypto_key_events (key_version, event, actor, detail, created_at)"
        " VALUES (?, 'reencrypted', ?, ?, ?)",
        (active_version, actor,
         "%d messages re-encrypted under v%d; %d skipped (destroyed key)"
         % (reencrypted, active_version, skipped), _now()))
    conn.commit()
    return {"reencrypted": reencrypted, "skipped_destroyed": skipped,
            "active_version": active_version}


def compromise_response(conn: sqlite3.Connection, version: int,
                        actor: str) -> Dict[str, Any]:
    """Documented compromise procedure, executed: mark compromised ->
    rotate -> re-encrypt everything under the new key."""
    compromise_key(conn, version, actor)
    old_v, new_v = rotate_key(conn, actor)
    stats = reencrypt_all(conn, actor)
    return {
        "compromised_version": version,
        "rotated_from": old_v,
        "rotated_to": new_v,
        **stats,
        "note": "Compromised key v%d retired; new active key v%d; data "
                "re-encrypted where recoverable." % (version, new_v),
    }


def key_inventory(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT key_version, status, created_at, rotated_at, note FROM crypto_keys "
        "ORDER BY key_version").fetchall()
    events = conn.execute(
        "SELECT key_version, event, actor, created_at FROM crypto_key_events "
        "ORDER BY id").fetchall()
    ev_by_version: Dict[int, List[Dict[str, Any]]] = {}
    for e in events:
        ev_by_version.setdefault(int(e["key_version"]), []).append(dict(e))
    return [{
        "key_version": int(r["key_version"]),
        "status": r["status"],
        "created_at": r["created_at"],
        "rotated_at": r["rotated_at"],
        "note": r["note"],
        "events": ev_by_version.get(int(r["key_version"]), []),
    } for r in rows]


# --------------------------------------------------------------------------
# 10. Guided demo workflows (used by web pages + DEMO.md)
# --------------------------------------------------------------------------
def demo_sign_workflow(conn: sqlite3.Connection, actor: str,
                       message: bytes) -> List[Dict[str, str]]:
    """HMAC 'sign' workflow across a key rotation: sign -> verify -> rotate ->
    old signature still verifies with the retired key -> destroy old key ->
    further use of the destroyed key is refused. Each step logged."""
    steps: List[Dict[str, str]] = []

    def step(name: str, detail: str) -> None:
        steps.append({"step": name, "detail": detail})

    try:
        v1, key1 = get_active_key(conn)
    except KeyNotFoundError:
        v1 = create_key(conn, actor, note="demo workflow")
        _, key1 = get_active_key(conn)
    step("key-active", "active key v%d (synthetic, test-only)" % v1)

    tag = mac_sign(key1, message)
    step("sign", "HMAC tag created under v%d (symmetric MAC — not a public-key "
                 "signature)" % v1)

    ok = mac_verify(key1, message, tag)
    step("verify", "tag verifies under v%d: %s (constant-time compare)" % (v1, ok))

    tampered = bytearray(message); tampered[0] ^= 1
    ok_tampered = mac_verify(key1, bytes(tampered), tag)
    step("tamper-check", "modified message verifies: %s (must be False)" % ok_tampered)

    old_v, new_v = rotate_key(conn, actor)
    step("rotate", "rotated v%d -> v%d" % (old_v, new_v))

    retired_key = _load_live_key(conn, old_v)
    ok_retired = mac_verify(retired_key, message, tag)
    step("verify-retired", "old tag still verifies with retired v%d: %s "
                           "(old data stays readable)" % (old_v, ok_retired))

    destroy_key(conn, old_v, actor)
    step("destroy", "v%d wiped + tombstoned" % old_v)
    try:
        _load_live_key(conn, old_v)
        step("destroy-check", "ERROR: destroyed key still loadable")
    except KeyDestroyedError:
        step("destroy-check", "destroyed v%d refuses use: KeyDestroyedError "
                              "(fail closed)" % old_v)
    return steps


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def demo_encrypt_workflow(plaintext: bytes) -> Dict[str, Any]:
    """One-shot educational encrypt->tamper->decrypt narrative for the web demo."""
    key = generate_key(purpose="demo")
    env = encrypt(key, plaintext)
    good = decrypt(key, dict(env))
    # Fresh nonce state for the tamper step: the good decrypt above consumed
    # this (key, nonce) pair in the replay cache, and we want this step to
    # exercise TAG verification specifically.
    _reset_nonce_cache_for_tests()
    tampered = dict(env)
    ct = bytearray(bytes.fromhex(tampered["ciphertext"]))
    ct[0] ^= 1
    tampered["ciphertext"] = bytes(ct).hex()
    try:
        decrypt(key, tampered)
        tamper_result = "ERROR: tampered envelope decrypted"
    except TamperDetectedError:
        tamper_result = "tampered envelope rejected (TamperDetectedError)"
    return {
        "educational": True,
        "warning": EDUCATIONAL_BANNER,
        "roundtrip_ok": good == plaintext,
        "nonce_bits": NONCE_BYTES * 8,
        "tamper_result": tamper_result,
        "envelope_fields": sorted(env.keys()),
    }
