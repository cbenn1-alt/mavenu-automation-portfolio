"""N01 — web pages + /api/netforensics* endpoints (WSGI)."""
import io
import json
from urllib.parse import urlencode

from tests.conftest import wsgi_call

from mavenu import netforensics as nf


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _get_q(app, path, query_string):
    """GET with a real QUERY_STRING (conftest's wsgi_call puts everything
    in PATH_INFO, which real servers never do)."""
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

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    out = b"".join(app(environ, start_response))
    return int(captured["status"].split()[0]), captured["headers"], out


def _post_json(app, path, payload):
    return wsgi_call(app, "POST", path, body=json.dumps(payload).encode())


def _post_form(app, path, fields):
    return wsgi_call(
        app, "POST", path, body=urlencode(fields).encode(),
        content_type="application/x-www-form-urlencoded")


def _body_json(resp):
    return json.loads(resp[2].decode("utf-8"))


def _run_capture(app, scenario="port_scan", seed=20261023):
    status, _, body = _post_json(
        app, "/api/netforensics/capture", {"scenario": scenario, "seed": seed})
    assert status == 200, body.decode("utf-8")[:300]
    return _body_json((status, {}, body))


class TestN01Pages:
    def test_dashboard_200_has_capture_plan(self, app):
        status, _, body = _get(app, "/project_n01")
        assert status == 200
        text = body.decode("utf-8")
        assert "LAWFUL LAB ONLY" in text
        for sc in nf.SCENARIOS:
            assert sc in text

    def test_run_form_persists_and_shows_sessions(self, app):
        status, _, body = _post_form(
            app, "/project_n01/run", {"scenario": "port_scan", "seed": "20261023"})
        assert status == 200
        text = body.decode("utf-8")
        assert "N01 Sessions" in text
        assert "Handshake" in text

    def test_run_rejects_unknown_scenario(self, app):
        status, _, body = _post_form(
            app, "/project_n01/run", {"scenario": "internet", "seed": "1"})
        assert status == 422

    def test_sessions_timeline_anomalies_scoping_report_pages(self, app):
        cap = _run_capture(app, "c2_beaconing")
        cid = cap["capture_id"]
        for page, marker in [
                ("/project_n01/sessions", "N01 Sessions"),
                ("/project_n01/timeline", "N01 Timeline"),
                ("/project_n01/anomalies", "N01 Anomalies"),
                ("/project_n01/scoping", "Scoping memo"),
                ("/project_n01/report", "Evidentiary report")]:
            status, _, body = _get_q(app, page, f"capture_id={cid}")
            assert status == 200, page
            assert marker in body.decode("utf-8"), page

    def test_pages_default_to_latest_capture(self, app):
        _run_capture(app, "baseline_clean")
        status, _, body = _get(app, "/project_n01/report")
        assert status == 200
        assert "baseline_clean" in body.decode("utf-8")

    def test_pages_404_without_captures(self, app):
        for path in ("/project_n01/sessions", "/project_n01/timeline",
                     "/project_n01/anomalies", "/project_n01/scoping",
                     "/project_n01/report"):
            status, _, _ = _get(app, path)
            assert status == 404, path

    def test_report_page_shows_facts_and_inferences(self, app):
        cap = _run_capture(app, "port_scan")
        status, _, body = _get_q(
            app, "/project_n01/report", f"capture_id={cap['capture_id']}")
        text = body.decode("utf-8")
        assert "Facts" in text and "Inferences" in text
        assert "Ground-truth match" in text

    def test_anomalies_page_names_baseline(self, app):
        cap = _run_capture(app, "baseline_clean")
        status, _, body = _get_q(
            app, "/project_n01/anomalies", f"capture_id={cap['capture_id']}")
        text = body.decode("utf-8")
        assert "No anomalies" in text
        assert "port_scan_min_ports" in text


class TestN01Api:
    def test_capture_endpoint_all_scenarios(self, app):
        expected = {"baseline_clean": [], "port_scan": ["port_scan"],
                    "c2_beaconing": ["beaconing"],
                    "data_exfiltration": ["byte_exfiltration"]}
        for sc, anoms in expected.items():
            resp = _run_capture(app, sc)
            assert resp["scenario"] == sc
            assert resp["anomalies"] == anoms, sc
            assert resp["ground_truth_match"] is True, sc
            assert resp["synthetic"] is True
            assert "LAWFUL LAB ONLY" in resp["ethical_banner"]

    def test_capture_rejects_bad_scenario(self, app):
        status, _, body = _post_json(
            app, "/api/netforensics/capture", {"scenario": "nope"})
        assert status == 422

    def test_capture_rejects_nonint_seed(self, app):
        status, _, body = _post_json(
            app, "/api/netforensics/capture",
            {"scenario": "port_scan", "seed": "abc"})
        assert status == 422

    def test_captures_list(self, app):
        _run_capture(app, "port_scan")
        status, _, body = _get(app, "/api/netforensics/captures")
        assert status == 200
        data = _body_json((status, {}, body))
        assert len(data["captures"]) >= 1
        assert data["captures"][0]["scenario"] == "port_scan"

    def test_anomalies_endpoint_cites_ranges(self, app):
        cap = _run_capture(app, "data_exfiltration")
        status, _, body = _get_q(app, "/api/netforensics/anomalies", f"capture_id={cap['capture_id']}")
        assert status == 200
        data = _body_json((status, {}, body))
        assert len(data["anomalies"]) == 1
        a = data["anomalies"][0]
        assert a["anomaly_type"] == "byte_exfiltration"
        assert 0 <= a["start_index"] <= a["end_index"] < cap["packet_count"]
        assert a["detail"]["bytes_out"] == 560000

    def test_report_endpoint_fact_inference_separation(self, app):
        cap = _run_capture(app, "port_scan")
        status, _, body = _get_q(app, "/api/netforensics/report", f"capture_id={cap['capture_id']}")
        assert status == 200
        rep = _body_json((status, {}, body))["report"]
        assert rep["synthetic"] is True
        assert len(rep["facts"]) > 0
        assert len(rep["inferences"]) > 0
        for claim in rep["facts"] + rep["inferences"]:
            lo, hi = claim["packet_range"]
            assert 0 <= lo <= hi < rep["packet_count"]
        for inf in rep["inferences"]:
            assert inf["confidence"] in ("low", "medium", "high")
        for fact in rep["facts"]:
            assert "confidence" not in fact

    def test_api_404_without_captures(self, app):
        for path in ("/api/netforensics/anomalies", "/api/netforensics/report"):
            status, _, body = _get(app, path)
            assert status == 404, path
