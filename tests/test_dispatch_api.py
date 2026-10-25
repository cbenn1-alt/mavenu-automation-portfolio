"""API + page tests for Q09 — Technician Dispatch Optimizer."""
import json

import pytest

from tests.conftest import wsgi_call


def _post(app, path, payload):
    return wsgi_call(app, "POST", path, body=json.dumps(payload).encode())


def _get(app, path):
    return wsgi_call(app, "GET", path)


TECH = {"external_id": "t-api-1", "name": "Alex Morgan", "skills": ["hvac"],
        "home_zone": "B2", "shift_start": 480, "shift_end": 1020}
JOB = {"external_id": "j-api-1", "zone": "B2", "skill": "hvac",
       "duration_min": 60, "priority": 3, "window_start": 480,
       "window_end": 900}


def test_api_tech_crud_and_validation(app):
    s, _, body = _post(app, "/api/dispatch/techs", TECH)
    assert s == 201, body
    out = json.loads(body)
    assert out["external_id"] == "t-api-1" and out["replayed"] is False
    # natural-key idempotent
    s, _, body = _post(app, "/api/dispatch/techs", TECH)
    assert s == 201 and json.loads(body)["replayed"] is True
    # invalid skill -> 422
    bad = dict(TECH, external_id="t-api-2", skills=["welding"])
    s, _, _ = _post(app, "/api/dispatch/techs", bad)
    assert s == 422
    s, _, body = _get(app, "/api/dispatch/techs")
    assert s == 200 and len(json.loads(body)["techs"]) == 1


def test_api_job_crud_and_validation(app):
    s, _, body = _post(app, "/api/dispatch/jobs", JOB)
    assert s == 201, body
    bad = dict(JOB, external_id="j-api-2", window_start=900, window_end=480)
    s, _, _ = _post(app, "/api/dispatch/jobs", bad)
    assert s == 422
    s, _, body = _get(app, "/api/dispatch/jobs")
    assert s == 200 and len(json.loads(body)["jobs"]) == 1


def test_api_seed_run_and_detail(app):
    s, _, body = _post(app, "/api/dispatch/seed",
                       {"seed": 7, "n_techs": 6, "n_jobs": 24})
    assert s == 200
    seeded = json.loads(body)
    assert seeded["techs_total"] == 6 and seeded["jobs_total"] == 24

    s, _, body = _post(app, "/api/dispatch/run", {})
    assert s == 200
    summary = json.loads(body)
    assert summary["assigned"] + summary["infeasible"] == 24
    assert "cost_gap_pct" in summary

    s, _, body = _get(app, f"/api/dispatch/runs/{summary['run_id']}")
    assert s == 200
    detail = json.loads(body)
    assert detail["run"]["solver"] == "greedy_local_improvement"
    for a in detail["assignments"]:
        assert isinstance(a["reason_codes"], list) and a["reason_codes"]
    # every job accounted for: assigned or infeasible, never dropped
    got = ({a["job_ext"] for a in detail["assignments"]}
           | {i["job_ext"] for i in detail["infeasible"]})
    assert len(got) == 24

    s, _, _ = _get(app, "/api/dispatch/runs/999999")
    assert s == 404


def test_api_override_requires_reason_and_is_audited(app):
    _post(app, "/api/dispatch/seed", {"seed": 7, "n_techs": 6, "n_jobs": 24})
    s, _, body = _get(app, "/api/dispatch/techs")
    tech = json.loads(body)["techs"][0]["external_id"]
    s, _, body = _get(app, "/api/dispatch/jobs")
    job = json.loads(body)["jobs"][0]["external_id"]

    # missing reason -> 422, nothing logged
    s, _, _ = _post(app, "/api/dispatch/overrides",
                    {"job_id": job, "tech_id": tech, "kind": "pin"})
    assert s == 422
    s, _, _ = _post(app, "/api/dispatch/overrides",
                    {"job_id": job, "tech_id": tech, "kind": "pin",
                     "reason": "short"})
    assert s == 422
    # unknown job -> 404
    s, _, _ = _post(app, "/api/dispatch/overrides",
                    {"job_id": "nope", "tech_id": tech, "kind": "pin",
                     "reason": "a proper reason here"})
    assert s == 404

    s, _, body = _post(app, "/api/dispatch/overrides",
                       {"job_id": job, "tech_id": tech, "kind": "pin",
                        "reason": "Customer asked for this tech by name",
                        "actor": "dispatcher"})
    assert s == 201, body
    s, _, body = _get(app, "/api/dispatch/overrides")
    overrides = json.loads(body)["overrides"]
    assert len(overrides) == 1
    assert overrides[0]["reason"] == "Customer asked for this tech by name"
    assert overrides[0]["actor"] == "dispatcher"


def test_api_run_with_custom_policy_params(app):
    _post(app, "/api/dispatch/seed", {"seed": 7, "n_techs": 4, "n_jobs": 10})
    s, _, body = _post(app, "/api/dispatch/run",
                       {"lateness_weight": 2.0, "max_passes": 0})
    assert s == 200
    summary = json.loads(body)
    assert summary["solver"] == "greedy_local_improvement"
    s, _, body = _get(app, f"/api/dispatch/runs/{summary['run_id']}")
    params = json.loads(body)["run"]["policy_params"]
    assert json.loads(params) == {"lateness_weight": 2.0, "max_passes": 0}


def test_pages_render(app):
    for path in ("/project_q09", "/project_q09/overrides"):
        s, _, body = _get(app, path)
        assert s == 200, path
        assert b"Q09" in body
    _post(app, "/api/dispatch/seed", {"seed": 7, "n_techs": 4, "n_jobs": 10})
    s, _, body = _post(app, "/api/dispatch/run", {})
    run_id = json.loads(body)["run_id"]
    s, _, body = _get(app, f"/project_q09/runs/{run_id}")
    assert s == 200
    assert b"Honest gap" in body
    assert b"Infeasibility report" in body
    s, _, _ = _get(app, "/project_q09/runs/999999")
    assert s == 422  # unknown run -> error page


def test_form_seed_and_run_flow(app):
    s, headers, _ = wsgi_call(
        app, "POST", "/project_q09/seed",
        body=b"seed=7&n_techs=5&n_jobs=12",
        content_type="application/x-www-form-urlencoded")
    assert s == 303 and headers["Location"] == "/project_q09"
    s, headers, _ = wsgi_call(
        app, "POST", "/project_q09/run", body=b"",
        content_type="application/x-www-form-urlencoded")
    assert s == 303 and headers["Location"].startswith("/project_q09/runs/")
    s, _, body = _get(app, headers["Location"])
    assert s == 200


def test_form_override_flow(app):
    _post(app, "/api/dispatch/seed", {"seed": 7, "n_techs": 4, "n_jobs": 10})
    s, _, body = _get(app, "/api/dispatch/techs")
    tech = json.loads(body)["techs"][0]["external_id"]
    s, _, body = _get(app, "/api/dispatch/jobs")
    job = json.loads(body)["jobs"][0]["external_id"]
    form = (f"job_id={job}&tech_id={tech}&kind=pin&actor=webtest"
            f"&reason=Dispatcher+overrule+with+a+written+reason").encode()
    s, headers, _ = wsgi_call(
        app, "POST", "/project_q09/overrides", body=form,
        content_type="application/x-www-form-urlencoded")
    assert s == 303, (s, headers)
    s, _, body = _get(app, "/project_q09/overrides")
    assert b"Dispatcher overrule with a written reason" in body
