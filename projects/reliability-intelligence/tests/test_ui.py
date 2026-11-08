"""V3 smoke and negative-path tests; no operational or ML accuracy is implied."""

import contextlib
import copy
import io
import json
import unittest
from unittest import mock
from wsgiref.util import setup_testing_defaults

from reliability_intelligence.__main__ import main
from reliability_intelligence.charter import InvalidCharter, load_charter
from reliability_intelligence.web import ROUTES, app, render_page, serve_local


def invoke(path="/", method="GET"):
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)
    chunks = app(environ, start_response)
    return captured["status"], captured["headers"], b"".join(chunks)


class V3InterfaceTests(unittest.TestCase):
    def test_all_navigation_pages_work(self):
        for path, title in ROUTES:
            with self.subTest(path=path):
                status, headers, body = invoke(path)
                self.assertEqual(status, "200 OK")
                self.assertIn("text/html", headers["Content-Type"])
                html = body.decode("utf-8")
                self.assertIn("<main ", html)
                self.assertIn(f"<title>{title} | Mavenu Reliability Intelligence</title>", html)
                self.assertIn("Synthetic only", html)

    def test_navigation_has_four_first_party_links(self):
        status, _, body = invoke("/")
        self.assertEqual(status, "200 OK")
        html = body.decode()
        for path, _ in ROUTES:
            self.assertIn(f'href="{path}"', html)
        self.assertIn('aria-label="Primary navigation"', html)

    def test_selected_page_has_aria_current(self):
        for path, _ in ROUTES:
            with self.subTest(path=path):
                _, _, body = invoke(path)
                html = body.decode()
                self.assertEqual(html.count('aria-current="page"'), 1)

    def test_accessibility_has_landmarks_and_skip_link(self):
        _, _, body = invoke("/workbench")
        html = body.decode()
        self.assertIn('href="#main-content"', html)
        self.assertIn('id="main-content"', html)
        self.assertIn("<caption>V5 fictional example records", html)
        self.assertIn('scope="col"', html)
        self.assertIn('<html lang="en">', html)

    def test_workspace_shows_only_labeled_synthetic_fixtures(self):
        status, _, body = invoke("/workbench")
        html = body.decode()
        self.assertEqual(status, "200 OK")
        self.assertIn("Illustrative maintenance records", html)
        self.assertIn("All 12 records", html)
        self.assertIn("SYN-CASE-001", html)
        self.assertIn("V5 fictional example records", html)
        self.assertNotIn("expected_review_label", html)
        self.assertNotIn("repeat_history_candidate", html)

    def test_evaluation_does_not_claim_results(self):
        _, _, body = invoke("/evaluation")
        html = body.decode()
        self.assertIn("Not measured", html)
        self.assertIn("≥20%", html)
        self.assertIn("No approved baseline", html)

    def test_boundaries_are_explicit(self):
        _, _, body = invoke("/governance")
        html = body.decode()
        self.assertIn("Not permitted", html)
        self.assertIn("PLC, SCADA or OT", html)
        self.assertIn("not approved for industrial operational use", html)

    def test_static_css_is_local(self):
        status, headers, body = invoke("/assets/style.css")
        self.assertEqual(status, "200 OK")
        self.assertIn("text/css", headers["Content-Type"])
        self.assertIn(b".nav-item", body)
        self.assertIn(b"@media(max-width:760px)", body)

    def test_missing_route_fails_closed(self):
        for path in ("/admin", "/api/workorders", "/../../etc/passwd", "/favicon.ico"):
            with self.subTest(path=path):
                status, _, body = invoke(path)
                self.assertEqual(status, "404 Not Found")
                self.assertNotIn(b"work order", body.lower())

    def test_unsafe_http_methods_refused(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                status, headers, _ = invoke("/workbench", method)
                self.assertEqual(status, "405 Method Not Allowed")
                self.assertEqual(headers["Allow"], "GET, HEAD")

    def test_head_has_matching_content_length_no_body(self):
        status_get, headers_get, body_get = invoke("/")
        status_head, headers_head, body_head = invoke("/", "HEAD")
        self.assertEqual((status_get, status_head), ("200 OK", "200 OK"))
        self.assertEqual(body_head, b"")
        self.assertEqual(headers_get["Content-Length"], headers_head["Content-Length"])
        self.assertEqual(len(body_get), int(headers_get["Content-Length"]))

    def test_browser_response_has_restrictive_headers(self):
        _, headers, _ = invoke("/")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("style-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_charter_content_is_html_escaped(self):
        charter = copy.deepcopy(load_charter())
        charter["buyer_role"] = '<script>alert("danger")</script>'
        body = render_page("/", charter).decode("utf-8")
        self.assertNotIn('<script>', body)
        self.assertIn("&lt;script&gt;", body)

    def test_invalid_charter_disables_ui(self):
        with mock.patch("reliability_intelligence.web.load_charter",
                        side_effect=InvalidCharter("sensitive invalid charter")):
            status, _, body = invoke("/")
        self.assertEqual(status, "503 Service Unavailable")
        self.assertNotIn(b"sensitive invalid charter", body)

    def test_static_ui_requires_no_customer_data(self):
        charter = load_charter()
        self.assertEqual(charter["data_and_safety"]["data_mode"], "SYNTHETIC_ONLY")
        self.assertFalse(charter["data_and_safety"]["external_integrations_enabled"])
        _, _, body = invoke("/")
        self.assertNotIn(b"integrations enabled", body)

    def test_cli_preserves_v2_contract_with_v3_ui(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["status", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["increment"], "V8")
        self.assertEqual(payload["api_schema_version"], "1.3.0")
        self.assertEqual(payload["api_version"], "v1")
        self.assertEqual(payload["charter_increment"], "V2")
        self.assertEqual(payload["ui_mode"], "loopback_only")
        self.assertFalse(payload["business_approved"])

    def test_serving_restricted_to_loopback(self):
        server = mock.MagicMock()
        server.__enter__.return_value = server
        with mock.patch("reliability_intelligence.web.make_server", return_value=server) as factory:
            with contextlib.redirect_stdout(io.StringIO()):
                serve_local(8765)
        factory.assert_called_once_with("127.0.0.1", 8765, app)
        server.serve_forever.assert_called_once()

    def test_reject_invalid_port(self):
        for port in (-1, 0, 80, 65536, "8765", True):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    serve_local(port)

    def test_cli_server_dispatch(self):
        with mock.patch("reliability_intelligence.__main__.serve_local") as serve:
            self.assertEqual(main(["serve", "--port", "8766"]), 0)
        serve.assert_called_once_with(8766)


if __name__ == "__main__":
    unittest.main()
