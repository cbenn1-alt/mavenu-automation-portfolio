"""WSGI web application: portfolio hub + Project 01 pages and JSON API.

Standard library only (wsgiref-style callable). No framework, no assets,
no external requests — the whole UI is rendered server-side.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl

from . import leads as lead_service
from .classifier import DeterministicDemoClassifier
from .config import Settings
from .db import get_connection, run_migrations
from .events import log_system_event
from .leads import BookingError, FakeBookingAdapter  # noqa: F401 (re-exported for tests)
from .validation import SERVICES, ValidationError
from .workflow import LEAD_WORKFLOW

STATUS_TEXT = {
    200: "200 OK", 201: "201 Created", 303: "303 See Other",
    400: "400 Bad Request", 404: "404 Not Found",
    409: "409 Conflict", 422: "422 Unprocessable Entity",
    500: "500 Internal Server Error",
}

BANNER = (
    '<div class="banner">SYNTHETIC DEMO DATA — no real people, no real businesses. '
    'All names, numbers and addresses on this site are fictional.</div>'
)

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.5}
.banner{background:#fff3cd;border:1px solid #e6c200;padding:10px 14px;border-radius:6px;
margin-bottom:20px;font-size:14px}
.card{border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}
th{background:#f5f5f5}.state{font-weight:bold;text-transform:uppercase;font-size:12px;
padding:2px 8px;border-radius:10px;background:#eef;display:inline-block}
form label{display:block;margin:10px 0 4px}input,select,textarea{width:100%;padding:8px;
border:1px solid #bbb;border-radius:4px;box-sizing:border-box}
button{background:#0b5fff;color:#fff;border:0;padding:10px 18px;border-radius:6px;cursor:pointer}
.errors{color:#a00}.error-list{background:#fdecea;border:1px solid #e0a3a3;padding:10px;
border-radius:6px;margin-bottom:12px}
nav a{margin-right:16px}.timeline{font-size:14px}.timeline li{margin-bottom:6px}
code{background:#f4f4f4;padding:2px 6px;border-radius:4px}
"""


def _page(title: str, body: str) -> bytes:
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Mavenu Portfolio</title><style>{CSS}</style></head>
<body>{BANNER}<nav><a href="/">Hub</a><a href="/project01">Project 01</a>
<a href="/project01/dashboard">Dashboard</a></nav>
<h1>{title}</h1>{body}</body></html>"""
    return html.encode("utf-8")


def _json(status: int, payload: Any) -> tuple[int, list, bytes]:
    return status, [("Content-Type", "application/json")], json.dumps(payload).encode()


def _html(status: int, title: str, body: str) -> tuple[int, list, bytes]:
    return status, [("Content-Type", "text/html; charset=utf-8")], _page(title, body)


def _error_envelope(code: str, message: str, fields: Optional[dict] = None) -> dict:
    env: dict[str, Any] = {"error": {"code": code, "message": message}}
    if fields:
        env["error"]["fields"] = fields
    return env


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Fresh connection per request keeps the demo simple and thread-safe enough.
        conn = get_connection(settings.db_path)
        applied = run_migrations(conn)
        conn.close()
        if applied:
            log_system_event("db.migrated", {"applied": applied})
        self.classifier = DeterministicDemoClassifier(
            threshold=settings.review_confidence_threshold
        )
        self.booking_adapter = FakeBookingAdapter()

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.settings.db_path)

    # -- WSGI entry -----------------------------------------------------
    def __call__(self, environ: dict, start_response: Callable) -> Any:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/") or "/"
        try:
            status, headers, body = self.route(method, path, environ)
        except ValidationError as exc:
            status, headers, body = self._handle_validation_error(exc, environ)
        except KeyError as exc:
            status, headers, body = _json(404, _error_envelope("not_found", str(exc)))
        except Exception as exc:  # never leak internals to the client
            log_system_event("http.internal_error", {"path": path, "error": type(exc).__name__})
            status, headers, body = _json(
                500, _error_envelope("internal_error", "Something went wrong.")
            )
        start_response(STATUS_TEXT[status], headers)
        return [body]

    # -- routing ----------------------------------------------------------
    def route(self, method: str, path: str, environ: dict):
        if method == "GET" and path == "/":
            return self.hub()
        if method == "GET" and path == "/project01":
            return self.project_page()
        if method == "POST" and path == "/project01/leads":
            return self.form_submit(environ)
        if method == "GET" and path == "/project01/dashboard":
            return self.dashboard()
        m = re.fullmatch(r"/project01/leads/([A-Za-z0-9-]+)", path or "")
        if m and method == "GET":
            return self.lead_detail(m.group(1))
        if m and method == "POST":
            return self.lead_transition_form(m.group(1), environ)
        if method == "GET" and path == "/api/health":
            return _json(200, {"ok": True})
        if method == "GET" and path == "/api/stats":
            conn = self._conn()
            try:
                return _json(200, lead_service.stats(conn))
            finally:
                conn.close()
        if method == "POST" and path == "/api/leads":
            return self.api_create_lead(environ)
        m = re.fullmatch(r"/api/leads/([A-Za-z0-9-]+)", path or "")
        if m and method == "GET":
            return self.api_get_lead(m.group(1))
        mt = re.fullmatch(r"/api/leads/([A-Za-z0-9-]+)/transition", path or "")
        if mt and method == "POST":
            return self.api_transition(mt.group(1), environ)
        return _json(404, _error_envelope("not_found", f"No route for {method} {path}"))

    # -- helpers ------------------------------------------------------------
    def _read_body(self, environ: dict) -> bytes:
        # Cache on the environ: error handlers may need the body after routing read it.
        if "_mavenu_body" not in environ:
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            environ["_mavenu_body"] = (
                environ["wsgi.input"].read(length) if length > 0 else b""
            )
        return environ["_mavenu_body"]

    def _read_json(self, environ: dict) -> dict:
        raw = self._read_body(environ)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValidationError({"body": "Request body must be valid JSON."})
        if not isinstance(data, dict):
            raise ValidationError({"body": "Request body must be a JSON object."})
        return data

    def _idempotency_key(self, environ: dict, data: dict) -> Optional[str]:
        header = environ.get("HTTP_IDEMPOTENCY_KEY")
        if header:
            return header.strip() or None
        form_key = data.get("idempotency_key")
        return str(form_key).strip() or None if form_key else None

    # -- pages ------------------------------------------------------------------
    def hub(self):
        body = """
<p>Production-style AI automation projects built by Mavenu. Each project is a
working application with automated tests — or it is labeled honestly as planned.</p>
<div class="card"><h2>Project 01 — AI Revenue Operations Engine</h2>
<p>Synthetic home-services leads flow through intake, validation, rule-based
qualification, classifier routing, booking, and human review.</p>
<p><a href="/project01">Open the project</a> · <a href="/project01/dashboard">Dashboard</a></p>
<p><strong>Status:</strong> implemented + tested (Gate A)</p></div>
<div class="card"><h2>Project 02 — Enterprise Request &amp; Approval Automation</h2>
<p><strong>Status:</strong> planned</p></div>
<div class="card"><h2>Project 03 — AI Document Intelligence</h2>
<p><strong>Status:</strong> planned</p></div>
<div class="card"><h2>Project 04 — SQL Operations Intelligence</h2>
<p><strong>Status:</strong> planned</p></div>
<div class="card"><h2>Project 05 — Automation Reliability &amp; Governance Center</h2>
<p><strong>Status:</strong> planned</p></div>"""
        return _html(200, "Mavenu Automation Portfolio", body)

    def project_page(self, errors: Optional[dict] = None, values: Optional[dict] = None):
        values = values or {}
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        options = "".join(
            f'<option value="{s}" {"selected" if values.get("service") == s else ""}>{s}</option>'
            for s in SERVICES
        )
        key = uuid.uuid4().hex
        body = f"""
<p>Submit a synthetic lead. Server-side validation, duplicate protection, and
workflow routing run on every submission. Low-confidence classifications go to
human review — never silently dropped.</p>
{err_html}
<form method="post" action="/project01/leads">
<input type="hidden" name="idempotency_key" value="{key}">
<label>Name <input name="name" value="{values.get("name","")}" required></label>
<label>Phone <input name="phone" value="{values.get("phone","")}" placeholder="10 digits"></label>
<label>Email <input name="email" value="{values.get("email","")}" placeholder="optional"></label>
<label>Service <select name="service">{options}</select></label>
<label>ZIP <input name="zip" value="{values.get("zip","")}" placeholder="5 digits" required></label>
<label>Urgency <select name="urgency">
<option value="standard">standard</option><option value="priority">priority</option></select></label>
<label>Notes <textarea name="notes" rows="3">{values.get("notes","")}</textarea></label>
<p><button type="submit">Submit lead</button></p>
</form>
<p>Prefer the API? <code>POST /api/leads</code> with JSON and an
<code>Idempotency-Key</code> header. See <code>projects/project01/DEMO.md</code>.</p>"""
        return _html(200, "Project 01 — AI Revenue Operations Engine", body)

    def form_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        key = self._idempotency_key(environ, data)
        conn = self._conn()
        try:
            result = lead_service.submit_lead(
                conn, data, idempotency_key=key, classifier=self.classifier,
                booking_adapter=self.booking_adapter, actor="public-form",
                review_threshold=self.settings.review_confidence_threshold,
            )
        finally:
            conn.close()
        pid = result["body"]["public_id"]
        return 303, [("Location", f"/project01/leads/{pid}")], b""

    def lead_detail(self, public_id: str):
        conn = self._conn()
        try:
            lead = lead_service.get_lead(conn, public_id)
            if lead is None:
                return _html(404, "Not found", "<p>No such lead.</p>")
            events = lead_service.lead_events(conn, lead["id"])
        finally:
            conn.close()
        allowed = sorted(LEAD_WORKFLOW.allowed_from(lead["state"]))
        trans_opts = "".join(f'<option value="{s}">{s}</option>' for s in allowed)
        trans_form = (
            f"""<form method="post" action="/project01/leads/{lead['public_id']}">
<label>Reviewer action <select name="to_state">{trans_opts}</select></label>
<label>Reviewer name <input name="actor" value="reviewer"></label>
<p><button type="submit">Apply transition</button></p></form>"""
            if allowed else "<p><em>Terminal state — no further transitions.</em></p>"
        )
        rows = "".join(
            f"<tr><td>{k}</td><td>{'' if v is None else v}</td></tr>"
            for k, v in lead.items() if k != "id"
        )
        timeline = "".join(
            f"<li><code>{e['created_at']}</code> <strong>{e['event_type']}</strong> "
            f"by {e['actor']}"
            + (f" ({e['from_state']} → {e['to_state']})" if e["from_state"] or e["to_state"] else "")
            + (f" — <code>{e['detail']}</code>" if e["detail"] else "")
            + "</li>"
            for e in events
        )
        body = f"""
<p><span class="state">{lead['state']}</span></p>
<div class="card"><h2>Lead record</h2><table>{rows}</table></div>
<div class="card"><h2>Reviewer actions</h2>{trans_form}</div>
<div class="card"><h2>Audit timeline</h2><ul class="timeline">{timeline}</ul></div>"""
        return _html(200, f"Lead {lead['public_id']}", body)

    def lead_transition_form(self, public_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        to_state = data.get("to_state", "")
        actor = data.get("actor", "reviewer") or "reviewer"
        conn = self._conn()
        try:
            try:
                lead_service.transition_lead(conn, public_id, to_state, f"reviewer:{actor}")
            except Exception as exc:
                conn.close()
                return _html(400, "Transition failed",
                             f'<p class="errors">{exc}</p><p><a href="/project01/leads/{public_id}">Back</a></p>')
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", f"/project01/leads/{public_id}")], b""

    def dashboard(self):
        conn = self._conn()
        try:
            s = lead_service.stats(conn)
            recent = lead_service.list_leads(conn, limit=20)
        finally:
            conn.close()
        cells = "".join(
            f"<tr><td><span class='state'>{st}</span></td><td>{c}</td></tr>"
            for st, c in sorted(s["by_state"].items())
        )
        rows = "".join(
            f"<tr><td><a href=\"/project01/leads/{l['public_id']}\">{l['public_id']}</a></td>"
            f"<td>{l['name']}</td><td>{l['service']}</td>"
            f"<td><span class='state'>{l['state']}</span></td><td>{l['created_at']}</td></tr>"
            for l in recent
        )
        body = f"""
<div class="card"><h2>Totals (reconciled with the database)</h2>
<table><tr><th>State</th><th>Count</th></tr>{cells}
<tr><th>Total</th><th>{s['total']}</th></tr></table></div>
<div class="card"><h2>Recent leads</h2>
<table><tr><th>ID</th><th>Name</th><th>Service</th><th>State</th><th>Created</th></tr>
{rows}</table></div>"""
        return _html(200, "Project 01 — Operations Dashboard", body)

    # -- JSON API -----------------------------------------------------------------
    def api_create_lead(self, environ: dict):
        data = self._read_json(environ)
        key = self._idempotency_key(environ, data)
        data.pop("idempotency_key", None)
        conn = self._conn()
        try:
            result = lead_service.submit_lead(
                conn, data, idempotency_key=key, classifier=self.classifier,
                booking_adapter=self.booking_adapter, actor="api",
                review_threshold=self.settings.review_confidence_threshold,
            )
        finally:
            conn.close()
        status = 200 if result["replayed"] else result["status"]
        payload = dict(result["body"])
        if result["replayed"]:
            payload["replayed"] = True
        return _json(status, payload)

    def api_get_lead(self, public_id: str):
        conn = self._conn()
        try:
            lead = lead_service.get_lead(conn, public_id)
            if lead is None:
                return _json(404, _error_envelope("not_found", f"No lead {public_id!r}."))
            events = lead_service.lead_events(conn, lead["id"])
        finally:
            conn.close()
        lead["events"] = events
        lead["allowed_transitions"] = sorted(LEAD_WORKFLOW.allowed_from(lead["state"]))
        return _json(200, lead)

    def api_transition(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        to_state = data.get("to_state", "")
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            lead = lead_service.transition_lead(conn, public_id, to_state, actor)
        except KeyError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        except Exception as exc:
            conn.close()
            return _json(409, _error_envelope("invalid_transition", str(exc)))
        conn.close()
        return _json(200, {"public_id": lead["public_id"], "state": lead["state"]})

    def _handle_validation_error(self, exc: ValidationError, environ: dict):
        ctype = environ.get("CONTENT_TYPE", "")
        if environ.get("PATH_INFO", "").startswith("/api/") or "json" in ctype:
            return _json(422, _error_envelope("validation_failed",
                                             "The submission failed validation.",
                                             exc.field_errors))
        # HTML form: re-render with errors and the user's values preserved.
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        _, headers, body = self.project_page(errors=exc.field_errors, values=data)
        return 422, headers, body


def create_app(settings: Optional[Settings] = None) -> App:
    from .config import load_settings
    return App(settings or load_settings())
