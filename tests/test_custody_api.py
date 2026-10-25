"""S04 Forensic Evidence Management — web + API tests (WSGI test client).

All cases, items, hashes, actors, and incidents are synthetic fixtures.
"""
import json

import pytest

import mavenu.web as web_module
from mavenu import custody as c
from tests.conftest import wsgi_call

SHA = "e" * 64
WRONG = "f" * 64
SENDER = "Case Officer A. Reyes"
RECEIVER = "Custodian J. Okafor"


def _get_with_query(app, path, query_string):
    """Like tests.conftest.wsgi_call but sets QUERY_STRING (the test
    client's wsgi_call puts everything in PATH_INFO, which real servers
    never do)."""
    import io

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
    }
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    out = b"".join(app(environ, start_response))
    return int(captured["status"].split()[0]), captured["headers"], out


def _post(app, path, payload):
    return wsgi_call(app, "POST", path, json.dumps(payload).encode())


def _get(app, path):
    return wsgi_call(app, "GET", path)


@pytest.fixture
def seeded(app):
    status, _, body = _post(app, "/api/custody/seed", {})
    assert status == 201, body.decode()
    return json.loads(body)


class TestSeedApi:
    def test_seed_ok(self, seeded):
        assert seeded["case_ref"] == "CASE-2026-SYN-047"
        assert seeded["chain"]["ok"] is True
        assert seeded["dual_hash"]["violations"] == []
        assert seeded["access_coverage"]["gaps"] == []

    def test_seed_twice_conflicts(self, app, seeded):
        status, _, body = _post(app, "/api/custody/seed", {})
        assert status == 409


class TestIntakeApi:
    def test_intake_ok(self, app):
        status, _, body = _post(app, "/api/custody/seed", {})
        assert status == 201
        payload = {
            "case_id": 1, "tag": "EV-API-001",
            "description": "Synthetic API intake",
            "storage_location": "Locker API-1",
            "acquisition_sha256": SHA, "acquired_by": SENDER,
            "acquisition_ref": "ACQ-API-001",
        }
        status, _, body = _post(app, "/api/custody/items", payload)
        assert status == 201, body.decode()
        assert json.loads(body)["item"]["tag"] == "EV-API-001"

    def test_intake_bad_hash_422(self, app):
        status, _, body = _post(app, "/api/custody/seed", {})
        assert status == 201
        payload = {
            "case_id": 1, "tag": "EV-API-002", "description": "x",
            "storage_location": "Locker API-1", "acquisition_sha256": "nope",
            "acquired_by": SENDER, "acquisition_ref": "ACQ-API-002",
        }
        status, _, body = _post(app, "/api/custody/items", payload)
        assert status == 422

    def test_items_list(self, app, seeded):
        status, _, body = _get(app, "/api/custody/items")
        assert status == 200
        assert len(json.loads(body)["items"]) == 4


class TestTransferApi:
    def test_full_transfer_lifecycle(self, app, seeded):
        item_id = seeded["item_tags"] and 4  # EV-047-004 stays in_custody
        payload = {"item_id": item_id, "sender": SENDER, "receiver": RECEIVER,
                   "purpose": "api move", "destination_location": "Locker API-9"}
        status, _, body = _post(app, "/api/custody/transfers", payload)
        assert status == 201, body.decode()
        tr = json.loads(body)["transfer"]
        tid = tr["id"]

        # hash-in before hash-out -> 409 (dual verification enforced)
        status, _, _ = _post(app, f"/api/custody/transfers/{tid}/hash-in",
                             {"hash_in": SHA})
        assert status == 409

        item_sha = json.loads(_get(app, f"/api/custody/items/{item_id}")[2]
                              )["item"]["acquisition_sha256"]
        status, _, body = _post(app, f"/api/custody/transfers/{tid}/hash-out",
                                {"hash_out": item_sha})
        assert status == 200
        status, _, body = _post(app, f"/api/custody/transfers/{tid}/hash-in",
                                {"hash_in": item_sha})
        assert status == 200
        tr = json.loads(body)["transfer"]
        assert tr["status"] == "completed"
        status, _, body = _get(app, f"/api/custody/items/{item_id}")
        assert json.loads(body)["item"]["storage_location"] == "Locker API-9"

    def test_mismatch_rejects_via_api(self, app):
        _post(app, "/api/custody/seed", {})
        status, _, body = _post(app, "/api/custody/items", {
            "case_id": 1, "tag": "EV-API-M", "description": "mismatch api item",
            "storage_location": "Locker API-2", "acquisition_sha256": SHA,
            "acquired_by": SENDER, "acquisition_ref": "ACQ-API-M"})
        assert status == 201
        item_id = json.loads(body)["item"]["id"]
        status, _, body = _post(app, "/api/custody/transfers", {
            "item_id": item_id, "sender": SENDER, "receiver": RECEIVER,
            "purpose": "drill", "destination_location": "Locker API-3"})
        tid = json.loads(body)["transfer"]["id"]
        status, _, body = _post(app, f"/api/custody/transfers/{tid}/hash-out",
                                {"hash_out": WRONG})
        assert status == 200
        tr = json.loads(body)["transfer"]
        assert tr["status"] == "rejected"
        assert tr["incident"]["kind"] == "hash_mismatch"
        # quarantined: further transfers blocked
        status, _, _ = _post(app, "/api/custody/transfers", {
            "item_id": item_id, "sender": SENDER, "receiver": RECEIVER,
            "purpose": "retry", "destination_location": "Locker API-4"})
        assert status == 409


class TestDispositionApi:
    def test_disposition_then_transfer_blocked(self, app):
        _post(app, "/api/custody/seed", {})
        item_id = 4  # EV-047-004 is in_custody in the seeded case
        status, _, body = _post(app, "/api/custody/dispositions", {
            "item_id": item_id, "disposition": "archived",
            "authorized_by": SENDER, "authorization_ref": "AUTH-API-1"})
        assert status == 201
        status, _, _ = _post(app, "/api/custody/transfers", {
            "item_id": item_id, "sender": SENDER, "receiver": RECEIVER,
            "purpose": "too late", "destination_location": "Locker X"})
        assert status == 409


class TestVerifyApi:
    def test_verify_ok(self, app, seeded):
        status, _, body = _get(app, "/api/custody/verify")
        assert status == 200
        data = json.loads(body)
        assert data["chain_verification"]["ok"] is True
        assert data["dual_hash_verification"]["violations"] == []
        assert data["access_coverage"]["gaps"] == []

    def test_item_detail_trace(self, app, seeded):
        status, _, body = _get(app, "/api/custody/items/2")
        assert status == 200
        data = json.loads(body)
        assert data["item"]["tag"] == "EV-047-002"
        assert data["chain_verdict"]["ok"] is True
        types = [e["event_type"] for e in data["custody_entries"]]
        assert "intake" in types and "transfer.completed" in types
        assert any(d["disposition"] == "returned" for d in data["dispositions"])

    def test_item_not_found(self, app, seeded):
        status, _, _ = _get(app, "/api/custody/items/999")
        assert status == 404


class TestPages:
    def test_s04_page(self, app, seeded):
        status, _, body = _get(app, "/project_s04")
        assert status == 200
        text = body.decode()
        assert "S04 — Forensic Evidence Management" in text
        assert "Synthetic case only" in text

    def test_register_page(self, app, seeded):
        status, _, body = _get(app, "/project_s04/register")
        assert status == 200
        text = body.decode()
        assert "EV-047-001" in text and "EV-047-004" in text

    def test_item_page_full_chain(self, app, seeded):
        status, _, body = _get(app, "/project_s04/items/1")
        assert status == 200
        text = body.decode()
        assert "EV-047-001" in text
        assert "VERIFIED" in text
        assert "archived" in text.lower() or "ARCHIVED" in text

    def test_form_pages_printable(self, app, seeded):
        for form, qs in [("intake", "item_id=1"),
                         ("custody_log", "item_id=2"),
                         ("access_log", "item_id=2"),
                         ("transfer_receipt", "transfer_id=1"),
                         ("disposition_record", "item_id=1")]:
            status, _, body = _get_with_query(app, f"/project_s04/forms/{form}", qs)
            assert status == 200, (form, body.decode()[:200])
            text = body.decode()
            assert "SYNTHETIC" in text
            assert "window.print()" in text

    def test_form_unknown_404(self, app, seeded):
        status, _, _ = _get_with_query(app, "/project_s04/forms/nope", "item_id=1")
        assert status == 404

    def test_incidents_page(self, app, seeded):
        status, _, body = _get(app, "/project_s04/incidents")
        assert status == 200
        assert "hash_mismatch" in body.decode()

    def test_web_seed_button(self, app):
        status, _, body = wsgi_call(app, "POST", "/project_s04/seed")
        assert status == 200
        assert "CASE-2026-SYN-047" in body.decode()
