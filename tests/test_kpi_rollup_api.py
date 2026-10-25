"""API + web tests for Q07 — Multi-Location KPI Rollup Pipeline.

All data is synthetic fixture data. Uses the shared WSGI test client from
conftest (plus a query-string variant, since the conftest client drops
QUERY_STRING — same workaround as the Q06 API tests).
"""
import io
import json
from decimal import Decimal

import pytest

from tests.conftest import wsgi_call
from mavenu import kpi_defs, kpi_pipeline as kp


def wsgi_call_qs(app, method, path, query="", body=b"",
                 content_type="application/json"):
    """wsgi_call variant that sets QUERY_STRING."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
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

NORTH_MAP = {
    "job_id": "ticket_id", "completed_date": "date", "revenue": "rev_usd",
    "costs": "cost_usd", "is_callback": "callback_flag",
    "tech_days": "tech_days",
}
NORTH_CSV = (
    "ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days\n"
    "T-100,2026-09-03,450.00,180.00,N,1.0\n"
    "T-101,2026-09-05,275.50,120.00,Y,0.5\n"
)
SOUTH_MAP = {
    "job_id": "Job #", "completed_date": "Service Date", "revenue": "Amount",
    "costs": "Expenses", "is_callback": "CB", "tech_days": "CrewDays",
}
SOUTH_CSV = (
    "Job #,Service Date,Amount,Expenses,CB,CrewDays\n"
    "9001,2026-09-04,300.00,90.00,no,0.5\n"
    "9002,2026-09-07,525.25,210.00,yes,1.0\n"
)
PERIOD = "2026-09"


def post_json(app, path, payload):
    return wsgi_call(app, "POST", path, json.dumps(payload).encode())


@pytest.fixture
def api_seed(app, settings):
    from mavenu.db import get_connection
    conn = get_connection(settings.db_path)
    try:
        kp.register_location(conn, "north", "North Shop", NORTH_MAP,
                             actor="tester")
        kp.register_location(conn, "south", "South Shop", SOUTH_MAP,
                             actor="tester")
        kpi_defs.seed_default_definitions(conn, actor="tester")
    finally:
        conn.close()
    return app


def test_api_register_location(app):
    status, _, body = post_json(app, "/api/kpi/locations", {
        "code": "west", "name": "West Shop",
        "schema_map": {"job_id": "id", "completed_date": "completed",
                       "revenue": "total", "costs": "parts_labor",
                       "is_callback": "return_visit", "tech_days": "days"},
        "actor": "tester"})
    assert status == 201
    assert json.loads(body)["location_id"] > 0


def test_api_register_location_rejects_bad_map(app):
    status, _, body = post_json(app, "/api/kpi/locations", {
        "code": "x", "name": "X", "schema_map": {"job_id": "id"}})
    assert status == 422
    assert "missing canonical" in json.loads(body)["error"]["message"]


def test_api_locations_list(api_seed):
    status, _, body = wsgi_call(api_seed, "GET", "/api/kpi/locations")
    assert status == 200
    codes = {l["code"] for l in json.loads(body)["locations"]}
    assert {"north", "south"} <= codes


def test_api_upload_and_compute_roundtrip(api_seed):
    status, _, body = post_json(api_seed, "/api/kpi/upload", {
        "location_code": "north", "period": PERIOD, "csv": NORTH_CSV,
        "actor": "tester"})
    assert status == 200
    stats = json.loads(body)
    assert stats["staged"] == 2 and stats["deduped"] is False
    status, _, body = post_json(api_seed, "/api/kpi/upload", {
        "location_code": "south", "period": PERIOD, "csv": SOUTH_CSV,
        "actor": "tester"})
    assert status == 200
    status, _, body = post_json(api_seed, "/api/kpi/compute",
                                {"period": PERIOD, "actor": "tester"})
    assert status == 200
    values = json.loads(body)["values"]
    # north: 450.00+275.50 = 725.50 revenue over 2 jobs
    assert Decimal(values["north"]["revenue"]) == Decimal("725.50")
    # rollup: 725.50 + 825.25 = 1550.75
    assert Decimal(values["__rollup__"]["revenue"]) == Decimal("1550.75")
    assert Decimal(values["__rollup__"]["average_ticket"]) == Decimal("387.69")


def test_api_upload_dedupes_reupload(api_seed):
    post_json(api_seed, "/api/kpi/upload",
              {"location_code": "north", "period": PERIOD, "csv": NORTH_CSV})
    status, _, body = post_json(api_seed, "/api/kpi/upload", {
        "location_code": "north", "period": PERIOD, "csv": NORTH_CSV})
    assert status == 200
    assert json.loads(body)["deduped"] is True


def test_api_upload_bad_period_rejected(api_seed):
    status, _, body = post_json(api_seed, "/api/kpi/upload", {
        "location_code": "north", "period": "Sept", "csv": NORTH_CSV})
    assert status == 422


def test_api_dashboard_and_lineage(api_seed):
    post_json(api_seed, "/api/kpi/upload",
              {"location_code": "north", "period": PERIOD, "csv": NORTH_CSV})
    post_json(api_seed, "/api/kpi/compute", {"period": PERIOD})
    status, _, body = wsgi_call_qs(api_seed, "GET", "/api/kpi/dashboard",
                                     query=f"period={PERIOD}")
    assert status == 200
    payload = json.loads(body)
    assert payload["periods"] == [PERIOD]
    rollup_ids = [v["id"] for v in payload["values"]
                  if v["location_code"] is None]
    assert len(rollup_ids) == 5
    status, _, body = wsgi_call(
        api_seed, "GET", f"/api/kpi/values/{rollup_ids[0]}/lineage")
    assert status == 200
    dd = json.loads(body)
    assert len(dd["rows"]) == 2
    assert {r["job_id"] for r in dd["rows"]} == {"T-100", "T-101"}


def test_api_lineage_404(api_seed):
    status, _, body = wsgi_call(api_seed, "GET",
                                "/api/kpi/values/999999/lineage")
    assert status == 404


def test_api_quarantine_and_alerts(api_seed):
    drifted = ("ticket_id,date,rev_usd,cost_usd,callback_flag,tech_days,extra\n"
               "T-1,2026-09-01,100.00,40.00,N,1.0,z\n")
    status, _, body = post_json(api_seed, "/api/kpi/upload", {
        "location_code": "north", "period": PERIOD, "csv": drifted})
    assert status == 200
    assert json.loads(body)["alerts"] == 1
    status, _, body = wsgi_call_qs(api_seed, "GET", "/api/kpi/quarantine",
                                     query=f"period={PERIOD}")
    assert status == 200
    rows = json.loads(body)["quarantine"]
    assert any(r["reason"] == "unknown_column:extra" for r in rows)
    status, _, body = wsgi_call(api_seed, "GET", "/api/kpi/alerts")
    assert status == 200
    alerts = json.loads(body)["alerts"]
    assert len(alerts) == 1 and alerts[0]["alert_type"] == "schema_drift"


def test_api_definitions_and_restate(api_seed):
    post_json(api_seed, "/api/kpi/upload",
              {"location_code": "north", "period": PERIOD, "csv": NORTH_CSV})
    post_json(api_seed, "/api/kpi/compute", {"period": PERIOD})
    status, _, body = wsgi_call(api_seed, "GET", "/api/kpi/definitions")
    assert status == 200
    assert len(json.loads(body)["definitions"]) == 5
    status, _, body = post_json(api_seed, "/api/kpi/definitions", {
        "name": "gross_margin", "new_version": "v2",
        "formula": kpi_defs.V2_GROSS_MARGIN_DOC[0],
        "includes": kpi_defs.V2_GROSS_MARGIN_DOC[1],
        "excludes": kpi_defs.V2_GROSS_MARGIN_DOC[2],
        "actor": "tester"})
    assert status == 201
    status, _, body = post_json(api_seed, "/api/kpi/restate", {
        "period": PERIOD, "reason": "test restatement", "actor": "tester"})
    assert status == 200
    result = json.loads(body)
    assert result["restatements"] == 3  # north + south + rollup gross_margin
    # v2 margin for north: (725.50 - 300.00 - 50.00*1) / 725.50
    expected = ((Decimal("375.50")) / Decimal("725.50")).quantize(
        Decimal("0.000001"))
    assert Decimal(result["recomputed"]["north"]["gross_margin"]) == expected


def test_api_restate_requires_reason(api_seed):
    status, _, body = post_json(api_seed, "/api/kpi/restate",
                                {"period": PERIOD, "reason": ""})
    assert status == 422


def test_web_pages_render(api_seed):
    for path in ("/project_q07", "/project_q07/locations",
                 "/project_q07/quarantine", "/project_q07/kpi",
                 "/project_q07/restatements"):
        status, headers, body = wsgi_call(api_seed, "GET", path)
        assert status == 200, path
        assert b"SYNTHETIC DEMO DATA" in body, path


def test_web_kpi_detail_renders(api_seed):
    post_json(api_seed, "/api/kpi/upload",
              {"location_code": "north", "period": PERIOD, "csv": NORTH_CSV})
    post_json(api_seed, "/api/kpi/compute", {"period": PERIOD})
    _, _, body = wsgi_call_qs(api_seed, "GET", "/api/kpi/dashboard",
                                query=f"period={PERIOD}")
    value_id = json.loads(body)["values"][0]["id"]
    status, _, page = wsgi_call(api_seed, "GET", f"/project_q07/kpi/{value_id}")
    assert status == 200
    assert b"drill-down lineage" in page


def test_web_upload_form_roundtrip(api_seed):
    form = ("location_code=north&period=2026-09&csv="
            "ticket_id%2Cdate%2Crev_usd%2Ccost_usd%2Ccallback_flag%2Ctech_days"
            "%0AT-1%2C2026-09-01%2C100.00%2C40.00%2CN%2C1.0")
    status, _, body = wsgi_call(api_seed, "POST", "/project_q07/upload",
                                form.encode(),
                                content_type="application/x-www-form-urlencoded")
    assert status == 200
    assert b"Staged 1" in body


def test_web_compute_form_redirects(api_seed):
    post_json(api_seed, "/api/kpi/upload",
              {"location_code": "north", "period": PERIOD, "csv": NORTH_CSV})
    status, headers, _ = wsgi_call(
        api_seed, "POST", "/project_q07/compute", b"period=2026-09",
        content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"] == "/project_q07/kpi?period=2026-09"
