"""S05 — web pages + /api/crypto* endpoints (WSGI). Educational demo surface."""
import json

from tests.conftest import wsgi_call

from mavenu import crypto_demo as cd


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _post_json(app, path, payload):
    return wsgi_call(app, "POST", path, body=json.dumps(payload).encode())


def _body_json(resp):
    return json.loads(resp[2].decode("utf-8"))


class TestS05Pages:
    def test_overview_200_bannered(self, app):
        status, _, body = _get(app, "/project_s05")
        assert status == 200
        text = body.decode("utf-8")
        assert "S05 — Applied Cryptography" in text
        assert "Educational demo only" in text
        assert "EDUCATIONAL-ONLY" in text

    def test_primitives_page_200(self, app):
        status, _, body = _get(app, "/project_s05/primitives")
        assert status == 200
        text = body.decode("utf-8")
        assert "HMAC-SHA256" in text and "PBKDF2" in text

    def test_pitfalls_page_200(self, app):
        status, _, body = _get(app, "/project_s05/pitfalls")
        assert status == 200
        text = body.decode("utf-8")
        assert "P-ECB" in text and "P-NONCE" in text and "P-HOMEROLL" in text

    def test_keymgmt_page_200(self, app):
        status, _, body = _get(app, "/project_s05/keymgmt")
        assert status == 200
        assert "versioned registry" in body.decode("utf-8").lower()

    def test_demo_post_runs_workflows(self, app):
        status, _, body = _post_json(app, "/project_s05/demo", {})
        assert status == 200
        text = body.decode("utf-8")
        assert "destroy-check" in text
        assert "KeyDestroyedError" in text
        assert "Roundtrip ok: True" in text


class TestCryptoApi:
    def test_pitfalls_catalog(self, app):
        status, _, body = _get(app, "/api/crypto/pitfalls")
        assert status == 200
        data = _body_json((status, _, body))
        assert data["educational_only"] is True
        assert len(data["pitfalls"]) == 8
        assert {p["id"] for p in data["pitfalls"]} >= {"P-ECB", "P-NONCE", "P-HARDCODE"}

    def test_hash_endpoint(self, app):
        status, _, body = _post_json(app, "/api/crypto/hash",
                                     {"message_hex": b"abc".hex()})
        assert status == 200
        data = _body_json((status, _, body))
        assert data["digest_hex"] == cd.sha256_hex(b"abc")

    def test_hash_rejects_bad_hex(self, app):
        status, _, _ = _post_json(app, "/api/crypto/hash", {"message_hex": "zz"})
        assert status == 422

    def test_hmac_endpoint(self, app):
        key = cd.generate_key()
        status, _, body = _post_json(app, "/api/crypto/hmac",
                                     {"key_hex": key.hex(),
                                      "message_hex": b"m".hex()})
        assert status == 200
        data = _body_json((status, _, body))
        assert data["tag_hex"] == cd.hmac_sha256_hex(key, b"m")

    def test_hmac_rejects_weak_key(self, app):
        status, _, _ = _post_json(app, "/api/crypto/hmac",
                                   {"key_hex": b"password".hex(),
                                    "message_hex": b"m".hex()})
        assert status == 422

    def test_password_endpoint_roundtrip(self, app):
        status, _, body = _post_json(app, "/api/crypto/password",
                                     {"password": "s3cret-pw", "iterations": 10000})
        assert status == 200
        data = _body_json((status, _, body))
        assert data["verify"] is True
        assert data["stored"].startswith("$pbkdf2-sha256$10000$")

    def test_password_rejects_low_work_factor(self, app):
        status, _, _ = _post_json(app, "/api/crypto/password",
                                   {"password": "s3cret-pw", "iterations": 100})
        assert status == 422

    def test_encrypt_decrypt_roundtrip(self, app):
        s1, _, b1 = _post_json(app, "/api/crypto/encrypt",
                               {"plaintext_hex": b"hello".hex()})
        assert s1 == 200
        d1 = _body_json((s1, _, b1))
        assert d1["educational_only"] is True
        assert "demo_key_hex" in d1  # fresh synthetic key generated
        s2, _, b2 = _post_json(app, "/api/crypto/decrypt",
                               {"key_hex": d1["demo_key_hex"],
                                "envelope": d1["envelope"]})
        assert s2 == 200
        d2 = _body_json((s2, _, b2))
        assert bytes.fromhex(d2["plaintext_hex"]) == b"hello"

    def test_decrypt_tampered_fails_closed(self, app):
        s1, _, b1 = _post_json(app, "/api/crypto/encrypt",
                               {"plaintext_hex": b"hello".hex()})
        d1 = _body_json((s1, _, b1))
        env = dict(d1["envelope"])
        ct = bytearray(bytes.fromhex(env["ciphertext"]))
        ct[0] ^= 1
        env["ciphertext"] = bytes(ct).hex()
        s2, _, b2 = _post_json(app, "/api/crypto/decrypt",
                               {"key_hex": d1["demo_key_hex"], "envelope": env})
        assert s2 == 422
        d2 = _body_json((s2, _, b2))
        assert d2["error"]["code"] == "auth_failed"

    def test_keys_rotate_destroy(self, app):
        s1, _, b1 = _post_json(app, "/api/crypto/rotate", {"actor": "api-test"})
        assert s1 == 200
        d1 = _body_json((s1, _, b1))
        assert d1["rotated_to"] >= 1
        s2, _, b2 = _get(app, "/api/crypto/keys")
        assert s2 == 200
        keys = _body_json((s2, _, b2))["keys"]
        assert any(k["status"] == "active" for k in keys)
        active = next(k for k in keys if k["status"] == "active")
        s3, _, b3 = _post_json(app, "/api/crypto/destroy",
                               {"key_version": active["key_version"],
                                "actor": "api-test"})
        assert s3 == 200
        s4, _, b4 = _get(app, "/api/crypto/keys")
        inv = _body_json((s4, _, b4))["keys"]
        assert next(k for k in inv
                    if k["key_version"] == active["key_version"])["status"] == "destroyed"

    def test_cert_design_endpoint(self, app):
        status, _, body = _get(app, "/api/crypto/cert-design")
        assert status == 200
        data = _body_json((status, _, body))
        assert data["certificate_validation"]["status"].startswith("DESIGN ONLY")
