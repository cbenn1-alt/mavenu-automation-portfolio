"""V4 local-only read-only UI and versioned API transport."""

from __future__ import annotations

from html import escape
from pathlib import Path
from wsgiref.simple_server import make_server

from .charter import InvalidCharter, load_charter
from . import api_v1

ROUTES = (
    ("/", "Overview"),
    ("/workbench", "Case workspace"),
    ("/evaluation", "Evaluation"),
    ("/governance", "Boundaries"),
)

CSS_PATH = Path(__file__).resolve().parent / "static" / "style.css"

SECURITY_HEADERS = [
    ("Cache-Control", "no-store"),
    ("Content-Security-Policy", "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
]


def _response(start_response, status: str, mime: str, body: bytes, method: str, extra=()):
    headers = [("Content-Type", mime), ("Content-Length", str(len(body))), *SECURITY_HEADERS, *extra]
    start_response(status, headers)
    return [] if method == "HEAD" else [body]


def _navigation(active: str) -> str:
    items = []
    for path, name in ROUTES:
        current = ' aria-current="page"' if path == active else ""
        items.append(
            f'<a class="nav-item" href="{path}"{current}>{escape(name)}</a>'
        )
    return "\n".join(items)


def _page_content(path: str, charter: dict) -> str:
    person = escape(charter["primary_user_role"])
    buyer = escape(charter["buyer_role"])
    goal = escape(str(charter["primary_metric"]["proposed_relative_improvement_pct"]))
    if path == "/":
        return f"""<section class="hero">
          <p class="eyebrow">V3 / Prototype foundation</p>
          <h1>Maintenance intelligence that keeps people in control.</h1>
          <p class="lead">A proposed, source-traceable review workspace for industrial maintenance teams. This shell contains no customer records, predictions, or production connections.</p>
          <a class="text-link" href="/workbench">Open empty case workspace</a>
        </section>
        <section class="section" aria-label="Product scope">
          <h2>Prototype scope</h2>
          <div class="cards">
            <article class="panel"><p class="eyebrow">Proposed user</p><h3>{person}</h3><p>Operator role not yet customer-validated.</p></article>
            <article class="panel"><p class="eyebrow">Proposed buyer</p><h3>{buyer}</h3><p>Commercial owner not yet confirmed.</p></article>
            <article class="panel"><p class="eyebrow">Review objective</p><h3>Fewer manual review minutes</h3><p>Proposed ≥{goal}% relative reduction; not a measured outcome.</p></article>
          </div>
        </section>"""
    if path == "/workbench":
        return """<section class="section">
          <p class="eyebrow">01 / Human review workspace</p>
          <h1>Maintenance cases</h1>
          <p class="lead">The navigation and review shell are available. Representative synthetic case fixtures are planned for V5, and end-to-end workflow logic for V6.</p>
          <div class="panel">
            <div class="table-head"><span>Asset / case</span><span>Evidence</span><span>Review</span></div>
            <div class="empty-state" role="status"><h2>No cases loaded</h2><p>There is no live maintenance queue. No work orders are created or modified.</p></div>
          </div>
        </section>"""
    if path == "/evaluation":
        return f"""<section class="section">
          <p class="eyebrow">02 / Pre-registered evidence</p>
          <h1>Evaluation plan</h1>
          <p class="lead">A candidate experiment to compare human-only and assisted case review. No evaluation has been conducted.</p>
          <div class="cards two">
            <article class="panel"><p class="eyebrow">Proposed primary metric</p><h3>Median reviewer minutes per completed case</h3><p>Directional target: ≥{goal}% improvement, conditional on safety and quality guardrails.</p></article>
            <article class="panel"><p class="eyebrow">Observed results</p><h3>Not measured</h3><p>No approved baseline, case cohort, measured savings, or customer pilot.</p></article>
          </div>
          <h2>Review protocol</h2>
          <ol class="steps"><li>Confirm an unmet need and one asset cohort.</li><li>Compare with incumbent CMMS, ERP and reporting capabilities.</li><li>Freeze labels, sample size, manual baseline and reviewer assignments.</li><li>Test for critical misses, false flags, evidence traceability and review time.</li><li>Obtain human domain and security approvals before any pilot.</li></ol>
        </section>"""
    if path == "/governance":
        return """<section class="section">
          <p class="eyebrow">03 / Operating boundaries</p>
          <h1>Controls before integration</h1>
          <p class="lead">The system is not approved for industrial operational use. This page documents constraints, not security certification.</p>
          <div class="cards two">
            <article class="panel"><h3>Permitted now</h3><ul><li>Local UI/navigation smoke tests</li><li>Review proposed requirements</li><li>Run synthetic-only automated checks</li></ul></article>
            <article class="panel"><h3>Not permitted</h3><ul><li>Customer or employee records</li><li>CMMS, ERP, PLC, SCADA or OT connections</li><li>Writes to maintenance or control systems</li><li>Autonomous safety decisions or ROI claims</li></ul></article>
          </div>
          <p class="note">Formal V2 problem acceptance is pending. V3 proves only that a local user can navigate a minimal shell.</p>
        </section>"""
    raise KeyError(path)


def render_page(path: str, charter: dict) -> bytes:
    """Render inert semantic HTML with fixed, first-party navigation only."""
    page_title = next(name for url, name in ROUTES if url == path)
    main = _page_content(path, charter)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{escape(page_title)} | Mavenu Reliability Intelligence</title>
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to content</a>
  <header class="topbar"><div class="identity"><span class="brand-mark" aria-hidden="true">M</span><div><strong>MAVENU</strong><span>Reliability Intelligence</span></div></div><div class="environment">Synthetic only · Local prototype · Unapproved</div></header>
  <div class="app-layout">
    <nav class="sidebar" aria-label="Primary navigation"><p class="nav-label">Workspace</p>{_navigation(path)}</nav>
    <main id="main-content" tabindex="-1">{main}
      <footer><p>V3 navigation shell. No live integrations, operational recommendations, measured savings, or Minn-Dak endorsement.</p></footer>
    </main>
  </div>
</body>
</html>""".encode("utf-8")


def app(environ, start_response):
    """WSGI application; fixed GET/HEAD pages, no user-input mutation path."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")
    if path.startswith("/api/"):
        if method not in ("GET", "HEAD"):
            return _response(start_response, "405 Method Not Allowed", api_v1.API_MEDIA_TYPE,
                             api_v1.serialize(api_v1.error("method_not_allowed", "GET or HEAD only.")),
                             method, (("Allow", "GET, HEAD"),))
        if path not in api_v1.ROUTE_DESCRIPTIONS:
            return _response(start_response, "404 Not Found", api_v1.API_MEDIA_TYPE,
                             api_v1.serialize(api_v1.error("not_found", "Unknown API resource or version.")),
                             method)
        try:
            charter = load_charter()
        except InvalidCharter:
            return _response(start_response, "503 Service Unavailable", api_v1.API_MEDIA_TYPE,
                             api_v1.serialize(api_v1.error("charter_invalid", "Requirements contract unavailable.")),
                             method)
        try:
            payload = api_v1.data_for_path(path, charter)
        except (KeyError, ValueError, TypeError):
            return _response(start_response, "503 Service Unavailable", api_v1.API_MEDIA_TYPE,
                             api_v1.serialize(api_v1.error("contract_failure", "Versioned response unavailable.")),
                             method)
        return _response(start_response, "200 OK", api_v1.API_MEDIA_TYPE,
                         api_v1.serialize(payload), method)
    if method not in ("GET", "HEAD"):
        return _response(start_response, "405 Method Not Allowed", "text/plain; charset=utf-8",
                         b"Read-only interface. GET or HEAD only.\n", method, (("Allow", "GET, HEAD"),))
    if path == "/assets/style.css":
        try:
            data = CSS_PATH.read_bytes()
        except OSError:
            return _response(start_response, "503 Service Unavailable", "text/plain; charset=utf-8",
                             b"Stylesheet unavailable.\n", method)
        return _response(start_response, "200 OK", "text/css; charset=utf-8", data, method)
    if path not in dict(ROUTES):
        return _response(start_response, "404 Not Found", "text/plain; charset=utf-8", b"Not found.\n", method)
    try:
        charter = load_charter()
    except InvalidCharter:
        return _response(start_response, "503 Service Unavailable", "text/plain; charset=utf-8",
                         b"Requirements contract invalid. Interface unavailable.\n", method)
    return _response(start_response, "200 OK", "text/html; charset=utf-8",
                     render_page(path, charter), method)


def serve_local(port: int = 8765):
    """Only loopback binding is allowed. No configurable public host."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Port must be an integer between 1024 and 65535")
    with make_server("127.0.0.1", port, app) as server:
        print(f"Local prototype: http://127.0.0.1:{port}/")
        print("Synthetic-only navigation shell; Ctrl+C to stop.")
        server.serve_forever()
