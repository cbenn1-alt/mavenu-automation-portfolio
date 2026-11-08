"""Project P05 — API + page tests (WSGI, stdlib only). All data synthetic."""
import json
from urllib.parse import urlencode

from tests.conftest import wsgi_call
from tests.test_reconciliation_api import wsgi_call_qs


def api(app, method, path, payload=None, query=""):
    body = b""
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    return wsgi_call_qs(app, method, path, query=query, body=body)


def form(app, method, path, fields):
    body = urlencode(fields).encode("utf-8")
    return wsgi_call_qs(app, method, path, body=body,
                         content_type="application/x-www-form-urlencoded")


def get(app, path, query=""):
    return wsgi_call_qs(app, "GET", path, query=query)


def seed(app):
    status, _, body = api(app, "POST", "/api/governance/seed", {})
    assert status == 200, body
    return json.loads(body)["created"]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def test_pages_render_before_and_after_seed(app):
    status, _, body = get(app, "/project05")
    assert status == 200
    assert b"Reliability" in body and b"never sent" in body
    status, _, body = get(app, "/")
    assert status == 200
    assert b"Gate E" in body
    created = seed(app)
    assert created["checks"] == 5 and created["policies"] == 2
    assert created["rules"] == 4 and created["runbooks"] == 2
    status, _, body = get(app, "/project05")
    assert status == 200
    assert b"DB-REACHABLE" in body
    status, _, body = get(app, "/project05/checks")
    assert status == 200 and b"QUEUE-MISSED-CALLS" in body
    status, _, body = get(app, "/project05/alerts")
    assert status == 200 and b"recorded only" in body
    status, _, body = get(app, "/project05/incidents")
    assert status == 200 and b"weekly governance review" in body
    status, _, body = get(app, "/project05/jobs")
    assert status == 200 and b"DEMO-WEBHOOK-DELIVERY" in body
    status, _, body = get(app, "/project05/rules")
    assert status == 200 and b"QUEUE-DEPTH-HIGH" in body
    status, _, body = get(app, "/project05/policies")
    assert status == 200 and b"STANDARD-RETRY" in body
    status, _, body = get(app, "/project05/runbooks")
    assert status == 200 and b"RB-CRITICAL" in body


def test_seed_is_idempotent_via_api(app):
    first = seed(app)
    assert first["runs"] == 5
    second = seed(app)
    assert all(v == 0 for v in second.values())


def test_check_detail_page_and_run_form(app):
    seed(app)
    status, _, body = get(app, "/project05/checks/1")
    assert status == 200 and b"DB-REACHABLE" in body
    status, headers, _ = form(app, "POST", "/project05/checks/1/run", {})
    assert status == 303 and headers["Location"] == "/project05/checks/1"
    status, _, body = get(app, "/project05/checks/1")
    assert b"pass" in body
    status, _, body = get(app, "/project05/checks/99999")
    assert status == 404


# ---------------------------------------------------------------------------
# Status + checks API
# ---------------------------------------------------------------------------
def test_status_api(app):
    seed(app)
    status, _, body = api(app, "GET", "/api/governance/status")
    assert status == 200
    data = json.loads(body)["status"]
    assert data["overall"] == "pass"
    assert len(data["checks"]) == 5
    assert data["open_alerts"] == 0


def test_create_check_api_and_validation(app):
    status, _, body = api(
        app, "POST", "/api/governance/checks",
        {"name": "API-CHECK", "subsystem": "db", "kind": "liveness",
         "probe": "db_reachable", "warn_threshold": 0, "fail_threshold": 0})
    assert status == 201, body
    check = json.loads(body)["check"]
    assert check["name"] == "API-CHECK"
    status, _, body = api(
        app, "POST", "/api/governance/checks",
        {"name": "API-CHECK", "subsystem": "db", "kind": "liveness",
         "probe": "db_reachable"})
    assert status == 422  # duplicate name
    status, _, body = api(
        app, "POST", "/api/governance/checks",
        {"name": "BAD", "subsystem": "db", "kind": "liveness",
         "probe": "no-such-probe"})
    assert status == 422
    status, _, body = api(
        app, "POST", "/api/governance/checks",
        {"name": "BAD", "subsystem": "db", "kind": "liveness",
         "probe": "queue_depth", "params": {"table": "users", "value": "x"}})
    assert status == 422
    status, _, body = api(app, "GET", "/api/governance/checks/99999")
    assert status == 404


def test_run_check_api(app):
    seed(app)
    status, _, body = api(app, "POST", "/api/governance/checks/1/run", {})
    assert status == 200, body
    run = json.loads(body)["run"]
    assert run["status"] == "pass" and run["alerts"] == []
    status, _, body = api(app, "GET", "/api/governance/runs",
                          query="check_id=1")
    assert status == 200
    assert len(json.loads(body)["runs"]) >= 2  # seed run + this run


# ---------------------------------------------------------------------------
# Policies + jobs API
# ---------------------------------------------------------------------------
def test_policy_supersede_and_job_lifecycle_api(app):
    seed(app)
    status, _, body = api(
        app, "POST", "/api/governance/policies",
        {"name": "API-POL", "max_attempts": 2, "backoff_base_s": 5,
         "backoff_cap_s": 60, "jitter_max_s": 0, "dead_letter_after": 2})
    assert status == 201, body
    policy = json.loads(body)["policy"]
    assert policy["version"] == 1
    status, _, body = api(
        app, "POST", f"/api/governance/policies/{policy['id']}/supersede",
        {"max_attempts": 3, "backoff_base_s": 10, "backoff_cap_s": 120,
         "jitter_max_s": 0, "dead_letter_after": 3})
    assert status == 200, body
    assert json.loads(body)["policy"]["version"] == 2
    status, _, body = api(app, "GET", "/api/governance/policies",
                          query="all=1")
    versions = [p["version"] for p in json.loads(body)["policies"]
                if p["name"] == "API-POL"]
    assert versions == [1, 2]

    status, _, body = api(
        app, "POST", "/api/governance/jobs",
        {"name": "API-JOB", "policy_id": policy["id"], "payload": {"a": 1}})
    assert status == 201, body
    job = json.loads(body)["job"]
    status, _, body = api(
        app, "POST", f"/api/governance/jobs/{job['id']}/attempt",
        {"outcome": "failure", "error": "timeout"})
    assert status == 200, body
    job = json.loads(body)["job"]
    assert job["status"] == "scheduled" and job["attempts"] == 1
    status, _, body = api(
        app, "POST", f"/api/governance/jobs/{job['id']}/attempt",
        {"outcome": "failure", "error": "timeout"})
    assert status == 200, body
    job = json.loads(body)["job"]
    # The job pinned policy v1 (max 2 / dead-letter after 2) at creation;
    # superseding the policy to v2 did not change the pinned version, so
    # the second failure dead-letters it.
    assert job["status"] == "dead_lettered" and job["attempts"] == 2
    status, _, body = api(app, "GET", "/api/governance/dead-letters")
    assert status == 200
    dead = json.loads(body)["dead_letters"]
    assert len(dead) == 1
    status, _, body = api(
        app, "POST", f"/api/governance/dead-letters/{dead[0]['id']}/replay", {})
    assert status == 201, body
    fresh = json.loads(body)["job"]
    assert fresh["status"] == "pending" and fresh["attempts"] == 0
    status, _, body = api(
        app, "POST", f"/api/governance/dead-letters/{dead[0]['id']}/replay", {})
    assert status == 422  # already replayed
    status, _, body = api(
        app, "POST", "/api/governance/jobs/99999/attempt",
        {"outcome": "success"})
    assert status == 404


def test_job_create_rejects_unknown_policy(app):
    status, _, body = api(
        app, "POST", "/api/governance/jobs",
        {"name": "NOPE", "policy_id": 99999})
    assert status == 404


# ---------------------------------------------------------------------------
# Rules + alerts API (alert fires only via a real check run)
# ---------------------------------------------------------------------------
def test_rule_fire_ack_resolve_api(app):
    seed(app)
    status, _, body = api(app, "GET", "/api/governance/alerts")
    assert status == 200
    assert json.loads(body)["alerts"] == []
    # Create a rule that fires on the DB check's value (0) with lt 1.
    status, _, body = api(
        app, "POST", "/api/governance/rules",
        {"name": "DB-ALWAYS", "check_name": "DB-REACHABLE", "metric": "value",
         "operator": "lt", "threshold": 1, "severity": "low"})
    assert status == 201, body
    status, _, body = api(app, "POST", "/api/governance/checks/1/run", {})
    assert status == 200, body
    run = json.loads(body)["run"]
    assert len(run["alerts"]) == 1
    alert_id = run["alerts"][0]
    status, _, body = api(app, "GET", f"/api/governance/alerts/{alert_id}")
    assert status == 200
    assert json.loads(body)["alert"]["severity"] == "low"
    status, _, body = api(app, "POST", f"/api/governance/alerts/{alert_id}/ack", {})
    assert status == 200
    assert json.loads(body)["alert"]["status"] == "acked"
    status, _, body = api(app, "POST", f"/api/governance/alerts/{alert_id}/resolve", {})
    assert status == 200
    assert json.loads(body)["alert"]["status"] == "resolved"
    status, _, body = api(app, "POST", f"/api/governance/alerts/{alert_id}/ack", {})
    assert status == 422  # resolved is terminal
    status, _, body = api(app, "GET", "/api/governance/alerts/99999")
    assert status == 404


def test_rule_validation_and_silence_api(app):
    seed(app)
    status, _, body = api(
        app, "POST", "/api/governance/rules",
        {"name": "BAD-OP", "check_name": "DB-REACHABLE", "metric": "value",
         "operator": "xor", "threshold": 0, "severity": "low"})
    assert status == 422
    status, _, body = api(
        app, "POST", "/api/governance/rules",
        {"name": "BAD-SEV", "check_name": "DB-REACHABLE", "metric": "value",
         "operator": "gt", "threshold": 0, "severity": "fatal"})
    assert status == 422
    status, _, body = api(
        app, "POST", "/api/governance/rules/1/silence",
        {"until": "2020-01-01T00:00:00+00:00"})
    assert status == 422  # must be in the future
    status, _, body = api(
        app, "POST", "/api/governance/rules/1/silence",
        {"until": "2099-01-01T00:00:00+00:00"})
    assert status == 200, body
    assert json.loads(body)["rule"]["silenced_until"] == "2099-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Runbooks + incidents API
# ---------------------------------------------------------------------------
def test_runbook_walkthrough_api(app):
    seed(app)
    status, _, body = api(app, "GET", "/api/governance/runbooks")
    assert status == 200
    runbooks = json.loads(body)["runbooks"]
    rb = next(r for r in runbooks if r["name"] == "RB-CRITICAL")
    status, _, body = api(
        app, "POST", f"/api/governance/runbooks/{rb['id']}/walkthrough", {})
    assert status == 200, body
    wt = json.loads(body)["walkthrough"]
    assert wt["all_within_timebox"] is True
    assert len(wt["steps"]) == 4
    status, _, body = api(
        app, "POST", f"/api/governance/runbooks/{rb['id']}/supersede",
        {"alert_key": "critical",
         "steps": [{"step": "acknowledge", "action": "Open an incident.",
                    "timebox_s": 900}]})
    assert status == 200, body
    assert json.loads(body)["runbook"]["version"] == 2


def test_incident_lifecycle_api(app):
    seed(app)
    status, _, body = api(
        app, "POST", "/api/governance/incidents",
        {"title": "API incident", "severity": "high"})
    assert status == 201, body
    inc = json.loads(body)["incident"]
    assert inc["status"] == "open"
    assert len(inc["timeline"]) == 1
    status, _, body = api(
        app, "POST", f"/api/governance/incidents/{inc['id']}/transition",
        {"to_status": "closed"})
    assert status == 422  # open -> closed is illegal
    status, _, body = api(
        app, "POST", f"/api/governance/incidents/{inc['id']}/transition",
        {"to_status": "triaged"})
    assert status == 200
    status, _, body = api(
        app, "POST", f"/api/governance/incidents/{inc['id']}/transition",
        {"to_status": "mitigating"})
    assert status == 200
    status, _, body = api(
        app, "POST", f"/api/governance/incidents/{inc['id']}/transition",
        {"to_status": "resolved"})
    assert status == 422  # resolution note required
    status, _, body = api(
        app, "POST", f"/api/governance/incidents/{inc['id']}/transition",
        {"to_status": "resolved", "note": "Queue drained; checks pass."})
    assert status == 200, body
    inc = json.loads(body)["incident"]
    assert inc["status"] == "resolved"
    assert inc["resolution_note"] == "Queue drained; checks pass."
    status, _, body = api(
        app, "POST", f"/api/governance/incidents/{inc['id']}/notes",
        {"note": "Post-incident: tune the threshold."})
    assert status == 200, body
    inc = json.loads(body)["incident"]
    assert len(inc["timeline"]) == 5  # created + 3 transitions + note
    status, _, body = api(app, "GET", f"/api/governance/incidents/{inc['id']}")
    assert status == 200
    assert len(json.loads(body)["incident"]["timeline"]) == 5


def test_incident_page_flow(app):
    seed(app)
    status, headers, _ = form(
        app, "POST", "/project05/incidents",
        {"title": "Page incident", "severity": "medium"})
    assert status == 303
    assert headers["Location"].startswith("/project05/incidents/")
    incident_id = headers["Location"].rsplit("/", 1)[-1]
    status, _, body = get(app, f"/project05/incidents/{incident_id}")
    assert status == 200 and b"Page incident" in body
    status, headers, _ = form(
        app, "POST", f"/project05/incidents/{incident_id}/transition",
        {"to_status": "triaged", "note": ""})
    assert status == 303
    status, _, body = get(app, f"/project05/incidents/{incident_id}")
    assert b"triaged" in body
