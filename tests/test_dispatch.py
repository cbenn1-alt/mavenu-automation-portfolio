"""Tests for Q09 — Technician Dispatch Optimizer (service + solver).

All fixtures are synthetic: invented tech names, a fictional 4x4 zone
grid, generated jobs. Nothing here is real dispatch data.
"""
import json

import pytest

from mavenu import dispatch as d
from mavenu import dispatch_model as dm
from mavenu.db import rollback_migration, run_migrations, applied_migrations
from mavenu.dispatch import (
    DispatchError,
    GreedyLocalImprovementPolicy,
    NearestAvailableBaseline,
    current_pins,
    create_job,
    create_tech,
    list_jobs,
    list_techs,
    record_override,
    run_solver,
    seed_demo,
    verify_solution,
)
from mavenu.dispatch_model import (
    INF_NO_FEASIBLE_SLOT,
    INF_NO_SHIFT_OVERLAP,
    INF_NO_SKILLED_TECH,
    INF_PIN_SKILL_MISMATCH,
    INF_PIN_UNSATISFIABLE,
    INF_WINDOW_TOO_SHORT,
    REASON_CODES,
    REASON_LOCAL_IMPROVEMENT,
    REASON_PINNED,
    REASON_SKILL_MATCH,
    normalize_job,
    normalize_tech,
    synthetic_day,
    travel_minutes,
)
from mavenu.validation import ValidationError

# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

def _tech(ext="t1", skills=("hvac",), home="A1", sstart=480, send=1020,
          name="Alex Morgan", load=()):
    return {"external_id": ext, "name": name, "skills": list(skills),
            "home_zone": home, "shift_start": sstart, "shift_end": send,
            "current_load": list(load)}


def _job(ext="j1", zone="A1", skill="hvac", dur=60, pri=3,
         wstart=480, wend=720):
    return {"external_id": ext, "zone": zone, "skill": skill,
            "duration_min": dur, "priority": pri,
            "window_start": wstart, "window_end": wend}


def test_travel_matrix_documented_and_symmetric():
    assert travel_minutes("A1", "A1") == 5
    assert travel_minutes("A1", "B1") == 9
    assert travel_minutes("A1", "D4") == 5 + 4 * 6
    assert travel_minutes("A1", "D4") == travel_minutes("D4", "A1")


def test_normalize_job_rejects_bad_input():
    with pytest.raises(ValidationError):
        normalize_job(_job(zone="ZZ9"))
    with pytest.raises(ValidationError):
        normalize_job(_job(skill="welding"))          # unknown skill
    with pytest.raises(ValidationError):
        normalize_job(_job(dur=10))                   # below minimum
    with pytest.raises(ValidationError):
        normalize_job(_job(wstart=720, wend=480))     # inverted window
    with pytest.raises(ValidationError):
        normalize_job(_job(pri=9))                    # priority out of range
    with pytest.raises(ValidationError):
        normalize_job(_job(ext=""))                   # missing id


def test_normalize_tech_rejects_bad_input():
    with pytest.raises(ValidationError):
        normalize_tech(_tech(skills=[]))              # no skills    with pytest.raises(ValidationError):
        normalize_tech(_tech(skills=["welding"]))     # unknown skill
    with pytest.raises(ValidationError):
        normalize_tech(_tech(home="ZZ9"))
    with pytest.raises(ValidationError):
        normalize_tech(_tech(sstart=1020, send=480))  # inverted shift
    with pytest.raises(ValidationError):
        normalize_tech(_tech(load=[{"zone": "A1", "start": 500, "end": 560},
                                   {"zone": "A2", "start": 540, "end": 600}]))
    # commitment outside the shift is rejected at creation
    with pytest.raises(ValidationError):
        normalize_tech(_tech(load=[{"zone": "A1", "start": 200, "end": 300}]))


def test_window_shorter_than_duration_is_creation_legal_but_reported():
    # A window shorter than the job is NOT a creation error: the solver must
    # surface it in the infeasibility report instead of silently dropping it.
    job = normalize_job(_job(wstart=540, wend=555, dur=60))
    assert job.window_end - job.window_start < job.duration_min


# ---------------------------------------------------------------------------
# Known-good fixture: solver reproduces the obvious assignment
# ---------------------------------------------------------------------------

def _known_good_domain():
    techs = [
        normalize_tech(_tech("t-hvac", ("hvac",), "A1")),
        normalize_tech(_tech("t-plumb", ("plumbing",), "D4")),
    ]
    jobs = [
        normalize_job(_job("j1", "A1", "hvac", 60, 3, 480, 720)),
        normalize_job(_job("j2", "A2", "hvac", 60, 3, 480, 720)),
        normalize_job(_job("j3", "D4", "plumbing", 60, 3, 480, 720)),
        normalize_job(_job("j4", "D3", "plumbing", 60, 2, 780, 1020)),
    ]
    return techs, jobs


def test_known_good_fixture_reproduced():
    techs, jobs = _known_good_domain()
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
    assert not sol.infeasible
    mapping = {a.job_id: a.tech_id for a in sol.assignments}
    assert mapping == {"j1": "t-hvac", "j2": "t-hvac",
                       "j3": "t-plumb", "j4": "t-plumb"}
    assert verify_solution(techs, jobs,
                           {a.job_id: a for a in sol.assignments}, {}) == []
    for a in sol.assignments:
        assert REASON_SKILL_MATCH in a.reason_codes


def test_solver_is_deterministic():
    tech_dicts, job_dicts = synthetic_day(42, 6, 30)
    techs = [normalize_tech(t) for t in tech_dicts]
    jobs = [normalize_job(j) for j in job_dicts]
    pol = GreedyLocalImprovementPolicy()
    s1 = pol.solve(jobs, techs, {})
    s2 = pol.solve(jobs, techs, {})
    k = lambda s: sorted((a.job_id, a.tech_id, a.start,
                          tuple(a.reason_codes)) for a in s.assignments)
    assert k(s1) == k(s2)
    assert [i.job_id for i in s1.infeasible] == [i.job_id for i in s2.infeasible]


def test_fixture_generators_are_deterministic():
    assert synthetic_day(11, 5, 20) == synthetic_day(11, 5, 20)
    assert synthetic_day(11, 5, 20) != synthetic_day(12, 5, 20)


# ---------------------------------------------------------------------------
# Infeasibility: explicit reports, never silent drops
# ---------------------------------------------------------------------------

def test_infeasibility_no_skilled_tech():
    techs = [normalize_tech(_tech("t1", ("hvac",)))]
    jobs = [normalize_job(_job("j1", skill="roofing"))]
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
    assert not sol.assignments
    assert len(sol.infeasible) == 1
    assert INF_NO_SKILLED_TECH in sol.infeasible[0].violated
    assert sol.infeasible[0].detail  # human-readable explanation present


def test_infeasibility_window_too_short():
    techs = [normalize_tech(_tech("t1", ("hvac",)))]
    jobs = [normalize_job(_job("j1", wstart=540, wend=555, dur=60))]
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
    assert INF_WINDOW_TOO_SHORT in sol.infeasible[0].violated


def test_infeasibility_no_shift_overlap():
    techs = [normalize_tech(_tech("t1", ("hvac",), sstart=480, send=1020))]
    jobs = [normalize_job(_job("j1", wstart=1080, wend=1200, dur=60))]
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
    assert INF_NO_SHIFT_OVERLAP in sol.infeasible[0].violated


def test_infeasibility_no_feasible_slot_capacity():
    # One tech, one-hour shift, two overlapping one-hour jobs: exactly one
    # must be reported infeasible with NO_FEASIBLE_SLOT.
    techs = [normalize_tech(_tech("t1", ("hvac",), sstart=480, send=540))]
    jobs = [normalize_job(_job("j1", wstart=480, wend=540, dur=60, pri=5)),
            normalize_job(_job("j2", wstart=480, wend=540, dur=60, pri=1))]
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
    assert len(sol.assignments) == 1
    assert sol.assignments[0].job_id == "j1"  # higher priority wins
    assert len(sol.infeasible) == 1
    assert sol.infeasible[0].job_id == "j2"
    assert INF_NO_FEASIBLE_SLOT in sol.infeasible[0].violated


def test_pin_to_unskilled_tech_is_reported_not_forced():
    techs = [normalize_tech(_tech("t-hvac", ("hvac",))),
             normalize_tech(_tech("t-plumb", ("plumbing",)))]
    jobs = [normalize_job(_job("j1", skill="hvac"))]
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {"j1": "t-plumb"})
    assert not sol.assignments
    assert INF_PIN_SKILL_MISMATCH in sol.infeasible[0].violated
    # And verify_solution would catch it if anyone forced the assignment.
    from mavenu.dispatch import Assignment as A
    bad = {"j1": A("j1", "t-plumb", 480, 5, [REASON_SKILL_MATCH],
                   duration_min=60)}
    viols = verify_solution(techs, jobs, bad, {})
    assert any("skill" in v for v in viols)


def test_pin_unsatisfiable_reported():
    # Pinned tech is skilled and the window overlaps the shift, but the
    # shift is fully committed: PIN_UNSATISFIABLE, never a silent drop.
    techs = [normalize_tech(_tech(
        "t1", ("hvac",), sstart=480, send=540,
        load=[{"zone": "A1", "start": 480, "end": 540,
               "label": "existing"}]))]
    jobs = [normalize_job(_job("j1", wstart=480, wend=540, dur=30))]
    sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {"j1": "t1"})
    assert not sol.assignments
    assert INF_PIN_UNSATISFIABLE in sol.infeasible[0].violated


def test_verify_solution_catches_window_violation():
    techs, jobs = _known_good_domain()
    from mavenu.dispatch import Assignment as A
    bad = {"j1": A("j1", "t-hvac", 700, 5, [REASON_SKILL_MATCH],
                   duration_min=60)}  # window ends at 720 -> ends 760
    viols = verify_solution(techs, jobs, bad, {})
    assert any("window" in v for v in viols)


def test_verify_solution_catches_overlap():
    techs, jobs = _known_good_domain()
    from mavenu.dispatch import Assignment as A
    bad = {
        "j1": A("j1", "t-hvac", 480, 5, [REASON_SKILL_MATCH], duration_min=60),
        "j2": A("j2", "t-hvac", 500, 5, [REASON_SKILL_MATCH], duration_min=60),
    }
    viols = verify_solution(techs, jobs, bad, {})
    assert any("overlap" in v for v in viols)


# ---------------------------------------------------------------------------
# Reason codes on every assignment
# ---------------------------------------------------------------------------

def test_every_assignment_carries_valid_reason_codes():
    for seed in range(5):
        tech_dicts, job_dicts = synthetic_day(100 + seed, 6, 30)
        techs = [normalize_tech(t) for t in tech_dicts]
        jobs = [normalize_job(j) for j in job_dicts]
        sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
        assert sol.assignments, f"seed {seed}: nothing assigned"
        for a in sol.assignments:
            assert a.reason_codes, f"{a.job_id}: no reason codes"
            assert REASON_SKILL_MATCH in a.reason_codes
            for code in a.reason_codes:
                assert code in REASON_CODES, f"unknown code {code}"
        assert verify_solution(techs, jobs,
                               {a.job_id: a for a in sol.assignments}, {}) == []


def test_local_improvement_marks_moved_assignments():
    # The improver must never break constraints, and anything it moves is
    # labeled LOCAL_IMPROVEMENT.
    for seed in range(10):
        tech_dicts, job_dicts = synthetic_day(200 + seed, 5, 24)
        techs = [normalize_tech(t) for t in tech_dicts]
        jobs = [normalize_job(j) for j in job_dicts]
        full = GreedyLocalImprovementPolicy(max_passes=20).solve(jobs, techs, {})
        greedy = GreedyLocalImprovementPolicy(max_passes=0).solve(jobs, techs, {})
        assert verify_solution(techs, jobs,
                               {a.job_id: a for a in full.assignments}, {}) == []
        assert full.total_cost <= greedy.total_cost + 1e-6
        moved = {(a.job_id, a.tech_id, a.start) for a in full.assignments}
        greedy_set = {(a.job_id, a.tech_id, a.start) for a in greedy.assignments}
        for a in full.assignments:
            if (a.job_id, a.tech_id, a.start) not in greedy_set:
                assert REASON_LOCAL_IMPROVEMENT in a.reason_codes


# ---------------------------------------------------------------------------
# Baseline comparison: honest margin on synthetic days
# ---------------------------------------------------------------------------

def test_baseline_comparison_honest_margin():
    # 250 synthetic days. Records the honest margin; asserts the solver
    # beats the baseline on average and never catastrophically on any day.
    # Seeds are fixed, so these numbers are reproducible. The -20 floor is
    # a regression tripwire, not a performance claim: the heuristic is NOT
    # optimal and loses on a few days (see TEST_RESULTS.md for the honest
    # numbers, including the worst day).
    gaps = []
    for seed in range(3000, 3250):
        tech_dicts, job_dicts = synthetic_day(seed, 6, 30)
        techs = [normalize_tech(t) for t in tech_dicts]
        jobs = [normalize_job(j) for j in job_dicts]
        pins = {}
        sol = GreedyLocalImprovementPolicy().solve(jobs, techs, pins)
        base = NearestAvailableBaseline().solve(jobs, techs, pins)
        assert verify_solution(techs, jobs,
                               {a.job_id: a for a in sol.assignments}, {}) == []
        assert verify_solution(techs, jobs,
                               {a.job_id: a for a in base.assignments}, {}) == []
        if base.total_cost > 0:
            gaps.append((base.total_cost - sol.total_cost)
                        / base.total_cost * 100.0)
    assert len(gaps) == 250
    mean_gap = sum(gaps) / len(gaps)
    # Recorded honestly in TEST_RESULTS.md; the assertion below only guards
    # against a regression that makes the heuristic systematically worse.
    assert mean_gap > 0, f"mean baseline gap went non-positive: {mean_gap}"
    assert min(gaps) > -20, f"worst day gap regressed: {min(gaps)}"
    print(f"\n[Q09] baseline comparison over 250 synthetic days: "
          f"mean gap {mean_gap:.2f}%, min {min(gaps):.2f}%, "
          f"max {max(gaps):.2f}%")


def test_zero_violations_across_large_synthetic_run():
    # 250 days x 30 jobs = 7,500 dispatches; every placed job is verified.
    total = 0
    for seed in range(4000, 4250):
        tech_dicts, job_dicts = synthetic_day(seed, 6, 30)
        techs = [normalize_tech(t) for t in tech_dicts]
        jobs = [normalize_job(j) for j in job_dicts]
        sol = GreedyLocalImprovementPolicy().solve(jobs, techs, {})
        viols = verify_solution(techs, jobs,
                                {a.job_id: a for a in sol.assignments}, {})
        assert viols == [], f"seed {seed}: {viols[:3]}"
        total += len(jobs)
    assert total == 7500
    print(f"\n[Q09] verified {total} synthetic dispatches, 0 violations")


# ---------------------------------------------------------------------------
# Persistence: CRUD, runs, overrides, audit
# ---------------------------------------------------------------------------

def test_create_tech_and_job_idempotent(conn):
    r1 = create_tech(conn, _tech("t1"), actor="test")
    r2 = create_tech(conn, _tech("t1"), actor="test")
    assert r1["replayed"] is False and r2["replayed"] is True
    assert r1["id"] == r2["id"]
    j1 = create_job(conn, _job("j1"), actor="test")
    j2 = create_job(conn, _job("j1"), actor="test")
    assert j2["replayed"] is True and j1["id"] == j2["id"]
    assert len(list_techs(conn)) == 1 and len(list_jobs(conn)) == 1


def test_create_rejects_invalid(conn):
    with pytest.raises(ValidationError):
        create_job(conn, _job(skill="welding"))
    with pytest.raises(ValidationError):
        create_tech(conn, _tech(skills=[]))
    assert list_jobs(conn) == [] and list_techs(conn) == []


def test_run_solver_persists_run_and_comparison(conn):
    seed_demo(conn, seed=7, n_techs=6, n_jobs=24, actor="test")
    summary = run_solver(conn, actor="test")
    assert summary["assigned"] + summary["infeasible"] == 24
    assert summary["baseline_cost"] >= 0
    assert isinstance(summary["cost_gap_pct"], float)
    detail = d.run_detail(conn, summary["run_id"])
    assert detail["run"]["solver"] == "greedy_local_improvement"
    assert len(detail["assignments"]) == summary["assigned"]
    assert len(detail["infeasible"]) == summary["infeasible"]
    for a in detail["assignments"]:
        codes = json.loads(a["reason_codes"])
        assert codes and all(c in REASON_CODES for c in codes)
    # Infeasibility rows are explicit: every unassigned job is listed.
    assigned_jobs = {a["job_ext"] for a in detail["assignments"]}
    infeasible_jobs = {i["job_ext"] for i in detail["infeasible"]}
    all_jobs = {j["external_id"] for j in list_jobs(conn)}
    assert assigned_jobs | infeasible_jobs == all_jobs
    assert assigned_jobs & infeasible_jobs == set()


def test_run_solver_stores_policy_params(conn):
    seed_demo(conn, seed=7, n_techs=4, n_jobs=10, actor="test")
    summary = run_solver(conn, policy=GreedyLocalImprovementPolicy(
        lateness_weight=1.5, max_passes=5), actor="test")
    params = json.loads(d.run_detail(conn, summary["run_id"])["run"]
                        ["policy_params"])
    assert params == {"lateness_weight": 1.5, "max_passes": 5}


def test_override_requires_reason(conn):
    seed_demo(conn, seed=7, n_techs=4, n_jobs=10, actor="test")
    job = list_jobs(conn)[0]["external_id"]
    tech = list_techs(conn)[0]["external_id"]
    with pytest.raises(ValidationError):
        record_override(conn, job, tech, "pin", "", actor="test")
    with pytest.raises(ValidationError):
        record_override(conn, job, tech, "pin", "short", actor="test")
    with pytest.raises(ValidationError):
        record_override(conn, job, tech, "bogus-kind",
                        "a proper reason here", actor="test")
    with pytest.raises(KeyError):
        record_override(conn, "no-such-job", tech, "pin",
                        "a proper reason here", actor="test")
    assert d.list_overrides(conn) == []


def test_override_audit_completeness_and_pin_honored(conn):
    seed_demo(conn, seed=7, n_techs=6, n_jobs=24, actor="test")
    jobs = {j["external_id"]: j for j in list_jobs(conn)}
    techs = {t["external_id"]: t for t in list_techs(conn)}

    # Pick real, feasible pin targets: an assigned job and a *different*
    # tech that holds the same skill.
    plain = run_solver(conn, actor="test")
    plain_map = {a["job_ext"]: a["tech_ext"]
                 for a in d.run_detail(conn, plain["run_id"])["assignments"]}
    target_job = next(iter(plain_map))
    skill = jobs[target_job]["skill"]
    alt_tech = next(t for t, tech in techs.items()
                    if t != plain_map[target_job]
                    and skill in json.loads(tech["skills"]))
    other_job = next(j for j in plain_map if j != target_job)
    other_skill = jobs[other_job]["skill"]
    other_alt = next(t for t, tech in techs.items()
                     if t != plain_map[other_job]
                     and other_skill in json.loads(tech["skills"]))
    third_job = next(j for j in plain_map
                     if j not in (target_job, other_job))

    # Record a mix of pins, reassigns, and unpins — every one must be
    # logged with its reason (100% audit completeness).
    record_override(conn, target_job, alt_tech, "pin",
                    "Customer requested this tech specifically", actor="disp")
    record_override(conn, other_job, other_alt, "pin",
                    "Warranty job must go to senior tech", actor="disp")
    record_override(conn, other_job, alt_tech if other_skill in json.loads(techs[alt_tech]["skills"]) else other_alt,
                    "reassign", "Senior tech called in sick today", actor="disp")
    record_override(conn, third_job, alt_tech, "pin",
                    "Dispatcher gut feeling on this one", actor="disp")
    record_override(conn, third_job, None, "unpin",
                    "Gut feeling was wrong, release it", actor="disp")

    overrides = d.list_overrides(conn)
    assert len(overrides) == 5  # 100% of overrides logged
    for o in overrides:
        assert o["reason"] and len(o["reason"]) >= 8
        assert o["actor"] == "disp"
        assert o["kind"] in ("pin", "reassign", "unpin")

    pins = current_pins(conn)
    assert pins[target_job] == alt_tech
    assert third_job not in pins  # unpin cleared it

    # Re-solve honors the pins as hard constraints. A pinned job is either
    # assigned to its pinned tech (labeled PINNED) or appears in the
    # infeasibility report — it is NEVER silently assigned elsewhere.
    # (The dedicated feasible-pin case is covered by
    # test_pin_forces_non_greedy_choice.)
    summary = run_solver(conn, actor="test")
    detail = d.run_detail(conn, summary["run_id"])
    mapping = {a["job_ext"]: a["tech_ext"] for a in detail["assignments"]}
    infeasible = {i["job_ext"] for i in detail["infeasible"]}
    for pinned_job, pinned_tech in pins.items():
        assert pinned_job not in mapping or mapping[pinned_job] == pinned_tech
        assert pinned_job in mapping or pinned_job in infeasible
    for a in detail["assignments"]:
        if a["job_ext"] in pins:
            assert REASON_PINNED in json.loads(a["reason_codes"])


def test_pin_forces_non_greedy_choice(conn):
    # Two techs, one hvac job next to tech B's home: greedy picks B, but a
    # pin to A must win and be labeled PINNED.
    create_tech(conn, _tech("tA", ("hvac",), "A1"), actor="test")
    create_tech(conn, _tech("tB", ("hvac",), "A2"), actor="test")
    create_job(conn, _job("j1", "A2", "hvac", 60, 3, 480, 1020), actor="test")
    plain = run_solver(conn, actor="test")
    m0 = {a["job_ext"]: a["tech_ext"]
          for a in d.run_detail(conn, plain["run_id"])["assignments"]}
    assert m0["j1"] == "tB"  # greedy: closest
    record_override(conn, "j1", "tA", "pin",
                    "Tech A already has the parts on the van", actor="disp")
    pinned = run_solver(conn, actor="test")
    detail = d.run_detail(conn, pinned["run_id"])
    m1 = {a["job_ext"]: a["tech_ext"] for a in detail["assignments"]}
    assert m1["j1"] == "tA"
    codes = json.loads(detail["assignments"][0]["reason_codes"])
    assert REASON_PINNED in codes


def test_events_audit_trail(conn):
    seed_demo(conn, seed=7, n_techs=3, n_jobs=6, actor="test")
    run_solver(conn, actor="test")
    types = {r["event_type"] for r in conn.execute(
        "SELECT event_type FROM dispatch_events").fetchall()}
    assert {"tech.created", "job.created", "run.completed"} <= types


# ---------------------------------------------------------------------------
# Rollback: the 012 down-step is exercised for real
# ---------------------------------------------------------------------------

def test_migration_012_down_step_rolls_back_for_real(conn):
    seed_demo(conn, seed=7, n_techs=4, n_jobs=10, actor="test")
    run_solver(conn, actor="test")
    record_override(conn, list_jobs(conn)[0]["external_id"],
                    list_techs(conn)[0]["external_id"], "pin",
                    "rollback test pin reason", actor="test")
    assert "012_dispatch.sql" in applied_migrations(conn)

    assert rollback_migration(conn, "012_dispatch.sql") is True

    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert not any(t.startswith("dispatch_") for t in tables)
    assert "012_dispatch.sql" not in applied_migrations(conn)
    # Other projects' tables are untouched.
    assert "leads" in tables and "reviews" in tables

    # Re-apply works cleanly.
    applied = run_migrations(conn)
    assert applied == ["012_dispatch.sql"]
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "dispatch_runs" in tables
