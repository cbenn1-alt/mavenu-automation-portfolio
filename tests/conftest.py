"""Shared pytest fixtures: temp DB, app instance, WSGI test client."""
import io
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
)

from mavenu.config import Settings
from mavenu.db import get_connection, run_migrations
from mavenu.web import App

# All contact details below are synthetic fixtures, not real people.
GOOD_LEAD = {
    "name": "Dana Rivera",
    "phone": "(701) 555-0142",
    "email": "Dana.Rivera@Example.com",
    "service": "hvac",
    "zip": "58102",
    "urgency": "priority",
    "notes": "Furnace stopped blowing hot air last night; the house is getting cold.",
}

# In-area but thin: email only, no notes -> classifier confidence below threshold.
LOW_CONFIDENCE_LEAD = {
    "name": "Sam Chen",
    "email": "sam.chen@example.com",
    "service": "landscaping",
    "zip": "58103",
    "notes": "",
}

# Strong signal but outside the synthetic service area -> rules-layer review.
OUT_OF_AREA_LEAD = {
    "name": "Priya Nair",
    "phone": "7015550199",
    "email": "priya.nair@example.com",
    "service": "plumbing",
    "zip": "99999",
    "urgency": "priority",
    "notes": "Water heater leaking in the basement, need someone today.",
}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "test.db"),
        port=8080,
        idempotency_ttl_hours=72,
        review_confidence_threshold=0.65,
        log_level="INFO",
    )


@pytest.fixture
def conn(settings):
    c = get_connection(settings.db_path)
    run_migrations(c)
    yield c
    c.close()


@pytest.fixture
def app(settings):
    return App(settings)


def wsgi_call(app, method, path, body=b"", headers=None, content_type="application/json"):
    """Minimal WSGI test client (stdlib only). Returns (status_int, headers, body_bytes)."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
    }
    for k, v in (headers or {}).items():
        environ["HTTP_" + k.upper().replace("-", "_")] = v
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    out = b"".join(app(environ, start_response))
    return int(captured["status"].split()[0]), captured["headers"], out


def db_count(settings):
    c = get_connection(settings.db_path)
    try:
        return c.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
    finally:
        c.close()
