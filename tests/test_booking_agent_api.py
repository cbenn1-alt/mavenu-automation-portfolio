"""Q04 — Conversational Booking Agent: web/API tests (WSGI, stdlib only)."""
import json

from tests.conftest import wsgi_call

HAPPY = ["i need hvac", "58102", "tuesday morning", "Dana Rivera",
         "7015550142", "yes"]


def _post(app, path, payload):
    body = json.dumps(payload).encode()
    return wsgi_call(app, "POST", path, body=body)


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _start(app):
    status, _, body = _post(app, "/api/booking-agent/conversations", {})
    assert status == 201, body
    return json.loads(body)


def test_api_start_conversation_identifies_as_automated(app):
    data = _start(app)
    assert data["public_id"].startswith("CONV-")
    assert data["state"] == "service"
    assert "automated" in data["agent_message"].lower()
    assert data["handoff"] is False


def test_api_full_chat_to_booking(app):
    data = _start(app)
    pid = data["public_id"]
    for msg in HAPPY:
        status, _, body = _post(
            app, f"/api/booking-agent/conversations/{pid}/turns", {"text": msg})
        assert status == 200, body
        data = json.loads(body)
    assert data["state"] == "booked"
    assert data["agent_message"].startswith("You're booked!")


def test_api_turn_validation_errors(app):
    data = _start(app)
    pid = data["public_id"]
    status, _, _ = _post(
        app, f"/api/booking-agent/conversations/{pid}/turns", {"text": "   "})
    assert status == 422
    status, _, _ = _post(
        app, "/api/booking-agent/conversations/CONV-999999/turns", {"text": "hi"})
    assert status == 404


def test_api_turn_on_terminal_conversation_conflicts(app):
    data = _start(app)
    pid = data["public_id"]
    for msg in HAPPY:
        _post(app, f"/api/booking-agent/conversations/{pid}/turns", {"text": msg})
    status, _, body = _post(
        app, f"/api/booking-agent/conversations/{pid}/turns", {"text": "hello?"})
    assert status == 409


def test_api_get_transcript(app):
    data = _start(app)
    pid = data["public_id"]
    _post(app, f"/api/booking-agent/conversations/{pid}/turns", {"text": "hvac"})
    status, _, body = _get(app, f"/api/booking-agent/conversations/{pid}")
    assert status == 200
    convo = json.loads(body)
    assert convo["public_id"] == pid
    assert convo["slots"]["service"] == "hvac"
    assert [t["turn"] for t in convo["turns"]] == [0, 1, 2]
    status, _, _ = _get(app, "/api/booking-agent/conversations/CONV-999999")
    assert status == 404


def test_api_handoffs_queue_and_status(app):
    data = _start(app)
    _post(app, f"/api/booking-agent/conversations/{data['public_id']}/turns",
          {"text": "gibberish xyz"})
    status, _, body = _get(app, "/api/booking-agent/handoffs")
    assert status == 200
    queue = json.loads(body)["handoffs"]
    assert len(queue) == 1
    hid = queue[0]["id"]
    assert queue[0]["reason"] == "low_confidence"
    assert isinstance(queue[0]["transcript"], list)
    status, _, body = _post(app, f"/api/booking-agent/handoffs/{hid}",
                            {"status": "claimed"})
    assert status == 200
    assert json.loads(body)["status"] == "claimed"
    status, _, _ = _post(app, f"/api/booking-agent/handoffs/{hid}",
                         {"status": "bogus"})
    assert status == 422
    status, _, _ = _post(app, "/api/booking-agent/handoffs/999999",
                         {"status": "claimed"})
    assert status == 404


def test_api_bookings_list(app):
    status, _, body = _get(app, "/api/booking-agent/bookings")
    assert status == 200
    assert json.loads(body)["bookings"] == []
    data = _start(app)
    for msg in HAPPY:
        _post(app, f"/api/booking-agent/conversations/{data['public_id']}/turns",
              {"text": msg})
    status, _, body = _get(app, "/api/booking-agent/bookings")
    bookings = json.loads(body)["bookings"]
    assert len(bookings) == 1
    assert bookings[0]["booking_ref"].startswith("QB-")
    assert bookings[0]["adapter_name"] == "demo-booking-q04"


def test_pages_render(app):
    for path, marker in [
        ("/project_q04", "Conversational Booking Agent"),
        ("/project_q04/handoffs", "handoff queue"),
        ("/project_q04/bookings", "Adapter-confirmed bookings"),
        ("/", "Q04 — Conversational Booking Agent"),
    ]:
        status, headers, body = _get(app, path)
        assert status == 200, path
        assert marker in body.decode("utf-8"), path
    # synthetic-data banner present on the chat page
    _, _, body = _get(app, "/project_q04")
    assert "SYNTHETIC DEMO DATA" in body.decode("utf-8")
    # nav links present
    assert "/project_q04/handoffs" in body.decode("utf-8")
