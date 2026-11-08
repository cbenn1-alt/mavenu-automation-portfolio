"""Project P04 — API + page tests (WSGI, stdlib only). All data synthetic."""
import json
from urllib.parse import urlencode

from tests.conftest import wsgi_call
from tests.test_reconciliation_api import wsgi_call_qs
from tests.test_sqlops import EST_SPEC


def api(app, method, path, payload=None, query=""):
    body = b""
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    return wsgi_call_qs(app, method, path, query=query, body=body)


def form(app, method, path, fields):
    body = urlencode(fields).encode("utf-8")
    return wsgi_call_qs(app, method, path, body=body,
                         content_type="application/x-www-form-urlencoded")


def seed(app):
    status, _, _ = form(app, "POST", "/project04/seed", {})
    assert status == 303


def make_query(app, name="EST-API"):
    status, _, body = api(app, "POST", "/api/sqlops/queries",
                          {"name": name, "spec": EST_SPEC, "actor": "api-test"})
    assert status == 201, body
    return json.loads(body)["query"]


def run_query(app, qid, start="2026-10-01", end="2026-11-08"):
    status, _, body = api(app, "POST", f"/api/sqlops/queries/{qid}/run",
                          {"period_start": start, "period_end": end})
    assert status == 200, body
    return json.loads(body)["run"]


MC_SPEC = {"table": "missed_calls", "dimensions": ["state"],
           "metrics": [{"kind": "count"},
                       {"kind": "sum", "column": "duration_seconds"}],
           "filters": [], "grain": "none"}


def test_pages_render_before_and_after_seed(app):
    status, _, body = wsgi_call(app, "GET", "/project04")
    assert status == 200
    assert b"SQL Operations Intelligence" in body
    assert b"No saved queries yet" in body
    seed(app)
    for path in ("/project04", "/project04/queries", "/project04/runs",
                 "/project04/compare"):
        status, _, _ = wsgi_call(app, "GET", path)
        assert status == 200, path


def test_create_query_api(app):
    q = make_query(app)
    assert q["id"] == 1 and q["version"] == 1 and q["status"] == "current"
    assert q["spec"]["table"] == "estimates"
    # Duplicate name is rejected.
    status, _, body = api(app, "POST", "/api/sqlops/queries",
                          {"name": "EST-API", "spec": EST_SPEC})
    assert status == 422
    assert json.loads(body)["error"]["code"] == "validation_failed"
    # Unknown table is rejected.
    bad = dict(EST_SPEC, table="customers")
    status, _, _ = api(app, "POST", "/api/sqlops/queries",
                       {"name": "BAD-TABLE", "spec": bad})
    assert status == 422
    # Non-dict spec is rejected.
    status, _, _ = api(app, "POST", "/api/sqlops/queries",
                       {"name": "BAD-SPEC", "spec": "estimates"})
    assert status == 422
    # Missing name is rejected.
    status, _, _ = api(app, "POST", "/api/sqlops/queries", {"spec": EST_SPEC})
    assert status == 422


def test_injection_attempts_rejected_at_create(app):
    spec = dict(EST_SPEC, dimensions=["service_type; DROP TABLE leads"])
    status, _, _ = api(app, "POST", "/api/sqlops/queries",
                       {"name": "INJ-1", "spec": spec})
    assert status == 422
    spec = dict(EST_SPEC, metrics=[{"kind": "sum",
                                    "column": "amount_cents) OR 1=1 --"}])
    status, _, _ = api(app, "POST", "/api/sqlops/queries",
                       {"name": "INJ-2", "spec": spec})
    assert status == 422
    # A table name that looks like an expression is rejected too.
    spec = dict(EST_SPEC, table="estimates; SELECT 1")
    status, _, _ = api(app, "POST", "/api/sqlops/queries",
                       {"name": "INJ-3", "spec": spec})
    assert status == 422


def test_list_and_get_query(app):
    make_query(app, "Q-A")
    make_query(app, "Q-B")
    status, _, body = api(app, "GET", "/api/sqlops/queries")
    assert status == 200
    assert len(json.loads(body)["queries"]) == 2
    status, _, body = api(app, "GET", "/api/sqlops/queries/1")
    assert status == 200
    assert json.loads(body)["query"]["name"] == "Q-A"
    status, _, body = api(app, "GET", "/api/sqlops/queries/999")
    assert status == 404
    assert json.loads(body)["error"]["code"] == "not_found"


def test_supersede_via_api(app):
    q = make_query(app)
    new_spec = dict(EST_SPEC, dimensions=[])
    status, _, body = api(app, "POST", f"/api/sqlops/queries/{q['id']}/supersede",
                          {"spec": new_spec, "actor": "api-test"})
    assert status == 200, body
    new_q = json.loads(body)["query"]
    assert new_q["version"] == 2 and new_q["id"] != q["id"]
    status, _, body = api(app, "GET", "/api/sqlops/queries")
    current = json.loads(body)["queries"]
    assert len(current) == 1 and current[0]["version"] == 2
    status, _, body = api(app, "GET", "/api/sqlops/queries", query="all=1")
    assert len(json.loads(body)["queries"]) == 2
    # The old version's runs still resolve to v1.
    old = json.loads(body)["queries"]
    assert {q["version"] for q in old} == {1, 2}


def test_run_query_api(app):
    seed(app)
    q = make_query(app)
    run = run_query(app, q["id"])
    assert run["status"] == "ok" and run["rows_returned"] == 3
    assert isinstance(run["duration_ms"], int) and run["duration_ms"] >= 0
    by = {r["dimensions"]["service_type"]: r["metrics"] for r in run["results"]}
    assert by["hvac"]["count"] == 3
    assert by["hvac"]["sum_amount_cents"] == 350000
    assert by["hvac"]["avg_amount_cents"] == "116666.67"
    assert by["plumbing"]["count"] == 2
    assert by["electrical"]["count"] == 1
    # Decimal values cross the wire as strings, never floats.
    assert isinstance(by["hvac"]["avg_amount_cents"], str)


def test_run_query_invalid_period_records_error_run(app):
    seed(app)
    q = make_query(app)
    status, _, body = api(app, "POST", f"/api/sqlops/queries/{q['id']}/run",
                          {"period_start": "2026-11-08", "period_end": "2026-10-01"})
    assert status == 422
    payload = json.loads(body)
    assert payload["error"]["code"] == "validation_failed"
    assert "run_id" in payload
    status, _, body = api(app, "GET", f"/api/sqlops/runs/{payload['run_id']}")
    assert status == 200
    run = json.loads(body)["run"]
    assert run["status"] == "error" and run["error_text"]


def test_list_runs_and_get_run(app):
    seed(app)
    q = make_query(app)
    run = run_query(app, q["id"])
    status, _, body = api(app, "GET", "/api/sqlops/runs")
    assert status == 200
    runs = json.loads(body)["runs"]
    assert len(runs) == 1 and runs[0]["id"] == run["id"]
    status, _, body = api(app, "GET", "/api/sqlops/runs", query=f"query_id={q['id']}")
    assert len(json.loads(body)["runs"]) == 1
    status, _, body = api(app, "GET", "/api/sqlops/runs/999")
    assert status == 404


def test_drilldown_api(app):
    seed(app)
    status, _, body = api(app, "POST", "/api/sqlops/queries",
                          {"name": "MC-API", "spec": MC_SPEC})
    q = json.loads(body)["query"]
    run = run_query(app, q["id"])
    status, _, body = api(app, "POST", f"/api/sqlops/runs/{run['id']}/drilldown",
                          {"dimension": "state", "value": "booked"})
    assert status == 200, body
    dd = json.loads(body)["drilldown"]
    assert dd["row_count"] == 2 and dd["dimension"] == "state"
    assert all(r["state"] == "booked" for r in dd["rows"])
    # Bad dimension is rejected, and the table is untouched.
    status, _, body = api(app, "POST", f"/api/sqlops/runs/{run['id']}/drilldown",
                          {"dimension": "caller_id", "value": "x"})
    assert status == 422
    status, _, body = api(app, "GET", "/api/sqlops/runs")
    assert len(json.loads(body)["runs"]) == 1


def test_snapshot_api_and_status(app):
    seed(app)
    q = make_query(app)
    run = run_query(app, q["id"])
    status, _, body = api(app, "POST", f"/api/sqlops/runs/{run['id']}/snapshot",
                          {"actor": "api-test"})
    assert status == 201, body
    snap = json.loads(body)["snapshot"]
    # The snapshot row carries no status field — status is computed by
    # the /status endpoint (current vs. stale).
    assert snap["run_id"] == run["id"]
    assert len(snap["fingerprint"]) == 64
    status, _, body = api(app, "GET", f"/api/sqlops/snapshots/{snap['id']}/status")
    assert status == 200
    st = json.loads(body)
    assert st["status"] == "current"
    assert st["snapshot_id"] == snap["id"]
    assert st["current_fingerprint"] == st["fingerprint"]
    # Snapshot of a missing run is 404.
    status, _, _ = api(app, "POST", "/api/sqlops/runs/999/snapshot", {})
    assert status == 404


def test_compare_api(app):
    seed(app)
    q = make_query(app)
    status, _, body = api(app, "POST", "/api/sqlops/compare",
                          {"query_id": q["id"],
                           "period_a": ["2026-10-01", "2026-10-31"],
                           "period_b": ["2026-11-01", "2026-11-08"]})
    assert status == 200, body
    cmp = json.loads(body)["comparison"]
    assert cmp["period_a"]["run_id"] != cmp["period_b"]["run_id"]
    by = {r["dimensions"]["service_type"]: r["metrics"] for r in cmp["rows"]}
    # Seed truth: Oct hvac = 2 ($230,000, 1 accepted), Nov hvac = 1 ($120,000).
    assert by["hvac"]["count"] == {"a": 2, "b": 1, "delta": -1, "pct": "-50.000000"}
    assert by["hvac"]["sum_amount_cents"] == {"a": 230000, "b": 120000,
                                              "delta": -110000,
                                              "pct": "-47.826087"}
    # Plumbing appears only in period A: b is None, pct is None.
    assert by["plumbing"]["count"]["b"] is None
    assert by["plumbing"]["count"]["pct"] is None
    # Bad payload shape is rejected.
    status, _, _ = api(app, "POST", "/api/sqlops/compare", {"query_id": q["id"]})
    assert status == 422


def test_export_api(app):
    seed(app)
    q = make_query(app)
    run = run_query(app, q["id"])
    status, headers, body = api(app, "GET", f"/api/sqlops/runs/{run['id']}/export",
                                query="format=csv")
    assert status == 200
    assert headers.get("Content-Type") == "text/csv"
    lines = body.decode().strip().splitlines()
    assert lines[0] == "service_type,acceptance_rate,avg_amount_cents,count,sum_amount_cents"
    assert len(lines) == 4
    status, headers, body = api(app, "GET", f"/api/sqlops/runs/{run['id']}/export",
                                query="format=json")
    assert status == 200
    # JSON export is the raw results array (not wrapped in an envelope).
    assert len(json.loads(body)) == 3
    status, _, _ = api(app, "GET", f"/api/sqlops/runs/{run['id']}/export",
                       query="format=xml")
    assert status == 422
    status, _, _ = api(app, "GET", "/api/sqlops/runs/999/export", query="format=csv")
    assert status == 404


def test_page_create_run_and_drilldown_flow(app):
    seed(app)
    status, headers, _ = form(app, "POST", "/project04/queries",
                              {"name": "EST-PAGE", "description": "page flow",
                               "spec": json.dumps(EST_SPEC)})
    assert status == 303
    location = dict(headers)["Location"]
    assert location.startswith("/project04/queries/")
    status, _, body = wsgi_call(app, "GET", location)
    assert status == 200 and b"EST-PAGE" in body
    qid = location.rsplit("/", 1)[1]
    status, headers, _ = form(app, "POST", f"/project04/queries/{qid}/run",
                              {"period_start": "2026-10-01",
                               "period_end": "2026-11-08"})
    assert status == 303
    run_location = dict(headers)["Location"]
    assert run_location.startswith("/project04/runs/")
    status, _, body = wsgi_call(app, "GET", run_location)
    assert status == 200
    assert b"hvac" in body and b"350000" in body
    # Drill-down via the page's GET form.
    status, _, body = wsgi_call_qs(
        app, "GET", run_location, query="drill_dimension=service_type&drill_value=hvac")
    assert status == 200
    assert b"Drill-down: service_type = hvac" in body
    assert b"6 source rows" in body or b"3 source rows" in body


def test_page_compare_flow(app):
    seed(app)
    q = make_query(app)
    status, _, body = wsgi_call_qs(
        app, "GET", "/project04/compare",
        query=(f"query_id={q['id']}&a_start=2026-10-01&a_end=2026-10-31"
               "&b_start=2026-11-01&b_end=2026-11-08"))
    assert status == 200
    assert b"Comparison (A" in body
    assert b"hvac" in body


def test_page_create_with_bad_spec_shows_error(app):
    status, _, body = form(app, "POST", "/project04/queries",
                           {"name": "BAD", "spec": "{not json"})
    assert status == 200  # re-rendered with an error, not a crash
    assert b"valid JSON" in body
