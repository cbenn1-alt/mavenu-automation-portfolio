"""Project Q09 — Technician Dispatch Optimizer: solver + service layer.

Architecture (the spec's ``model/``, ``solve/``, ``explain/``, ``audit/``
layers map onto the two service modules)::

    dispatch_model.py   model/    — jobs, techs, constraints, reason codes,
                                    synthetic fixtures
    dispatch.py         solve/    — DispatchPolicy protocol, greedy +
                                    local-improvement heuristic, baseline
                      explain/    — reason codes on every assignment
                      audit/      — overrides, re-solves, event log

The heuristic
-------------
A ``DispatchPolicy`` takes jobs, techs, and dispatcher pins and returns a
``Solution``. The default policy (``GreedyLocalImprovementPolicy``) works
in two phases:

1. **Greedy construction.** Jobs are ordered by priority (desc), then
   window open (asc). Each job is inserted into the tech/time slot with the
   lowest *incremental cost* among all feasible candidates. A slot is
   feasible only if every hard constraint holds (skill, window, shift, no
   overlap, travel allowances, pins).
2. **Local improvement.** Relocate and swap moves are tried until no move
   strictly reduces total cost (or ``max_passes`` is hit). Pinned jobs are
   never moved by this phase.

**Documented objective** (minimized)::

    total_cost = total_travel_minutes
               + lateness_weight * SUM(priority * max(0, start - window_start))

i.e. drive time plus a priority-weighted penalty for starting later than
the job's window opens. ``lateness_weight`` defaults to 0.5 and is stored
on every run row, so results are reproducible and auditable.

**NOT optimal.** This is a heuristic. Every run is executed side-by-side
with a ``NearestAvailableBaseline`` (same constraints, myopic choice: the
skilled tech whose home zone is closest, first feasible slot) and the run
records the honest gap — whichever direction it goes.

Failure handling
----------------
* Skill/window/shift violations are *structurally impossible* in a returned
  solution: slots are only ever created by the feasibility check, and
  ``verify_solution`` re-checks every assignment before persistence. Any
  violation is an internal error, never a silent accept.
* Jobs that cannot be placed appear in the **infeasibility report** with
  explicit violated-constraint codes — never silently dropped.
* Dispatcher overrides (pin / reassign / unpin) require a written reason
  (>= 8 chars), are append-only in ``dispatch_overrides``, and are honored
  as hard constraints by every later solve.

ALL DATA THIS MODULE PROCESSES IS SYNTHETIC DEMONSTRATION DATA.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Protocol

from .db import utcnow_iso
from .dispatch_model import (
    INF_NO_FEASIBLE_SLOT,
    INF_NO_SHIFT_OVERLAP,
    INF_NO_SKILLED_TECH,
    INF_PIN_SKILL_MISMATCH,
    INF_PIN_UNSATISFIABLE,
    INF_WINDOW_TOO_SHORT,
    OVERRIDE_KINDS,
    OVERRIDE_PIN,
    OVERRIDE_REASON_MIN_CHARS,
    OVERRIDE_REASSIGN,
    OVERRIDE_UNPIN,
    REASON_CODES,
    REASON_LOAD_BALANCE,
    REASON_LOCAL_IMPROVEMENT,
    REASON_MIN_INCREMENTAL_COST,
    REASON_PINNED,
    REASON_SKILL_MATCH,
    REASON_ZONE_PROXIMITY,
    Assignment,
    Commitment,
    InfeasibleJob,
    Job,
    Solution,
    Tech,
    fmt_clock,
    normalize_job,
    normalize_tech,
    synthetic_day,
    travel_minutes,
    zones,
)
from .events import log_system_event
from .validation import ValidationError

#: Default lateness weight in the documented objective.
DEFAULT_LATENESS_WEIGHT = 0.5
#: A relocate/swap must beat the current cost by at least this to be taken
#: (guards against float churn; costs are otherwise integral-ish).
IMPROVEMENT_EPS = 1e-9
#: Travel at or below this counts as "zone proximity" for explainability.
ZONE_PROXIMITY_MAX_MIN = 10


class DispatchError(Exception):
    """Internal dispatch failure (e.g. a solution that violates constraints)."""


# ---------------------------------------------------------------------------
# Policy protocol
# ---------------------------------------------------------------------------

class DispatchPolicy(Protocol):
    """Replaceable dispatch strategy (same pattern as P01's LeadClassifier).

    ``solve`` returns a pure ``Solution``: it must never violate a hard
    constraint, and every infeasible job must carry violated codes.
    """

    name: str

    def solve(
        self,
        jobs: list[Job],
        techs: list[Tech],
        pins: dict[str, str],
    ) -> Solution:
        ...


# ---------------------------------------------------------------------------
# Internal timeline helpers (pure)
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    start: int
    end: int
    zone: str
    job_id: Optional[str]  # None = pre-existing commitment


def _tech_blocks(tech: Tech, assigns: list[Assignment],
                 jobs_by_id: dict[str, Job]) -> list[_Block]:
    blocks = [_Block(c.start, c.end, c.zone, None) for c in tech.current_load]
    for a in assigns:
        job = jobs_by_id[a.job_id]
        blocks.append(_Block(a.start, a.start + job.duration_min, job.zone,
                             a.job_id))
    blocks.sort(key=lambda b: (b.start, b.end))
    return blocks


def _solution_cost(techs: list[Tech], jobs: list[Job],
                   assign: dict[str, Assignment],
                   lateness_weight: float) -> tuple[float, int, float]:
    """(total_cost, total_travel, total_lateness) for an assignment map."""
    jobs_by_id = {j.external_id: j for j in jobs}
    by_tech: dict[str, list[Assignment]] = {t.external_id: [] for t in techs}
    for a in assign.values():
        by_tech[a.tech_id].append(a)
    total_travel = 0
    total_lateness = 0.0
    for tech in techs:
        blocks = _tech_blocks(tech, by_tech[tech.external_id], jobs_by_id)
        prev_zone: Optional[str] = None
        for b in blocks:
            zone = b.zone
            if prev_zone is None:
                leg_from = tech.home_zone
            else:
                leg_from = prev_zone
            if b.job_id is not None:
                total_travel += travel_minutes(leg_from, zone)
                job = jobs_by_id[b.job_id]
                total_lateness += job.priority * max(0, b.start - job.window_start)
            prev_zone = zone
    total_cost = total_travel + lateness_weight * total_lateness
    return total_cost, total_travel, total_lateness


@dataclass
class _Slot:
    start: int
    travel_in: int       # travel from previous stop (or home) into the job
    incremental_cost: float


def _best_slot(tech: Tech, job: Job, blocks: list[_Block],
               lateness_weight: float) -> Optional[_Slot]:
    """Cheapest feasible insertion slot for ``job`` on ``tech``'s timeline.

    ``blocks`` must be sorted and must already contain the tech's
    commitments plus currently assigned jobs. Returns None when no slot
    satisfies every hard constraint.
    """
    best: Optional[_Slot] = None
    n = len(blocks)
    for i in range(n + 1):
        prev = blocks[i - 1] if i > 0 else None
        nxt = blocks[i] if i < n else None

        if prev is None:
            earliest = max(job.window_start, tech.shift_start)
            travel_in = travel_minutes(tech.home_zone, job.zone)
            displaced = travel_minutes(tech.home_zone, nxt.zone) if nxt else 0
        else:
            earliest = max(job.window_start, tech.shift_start,
                           prev.end + travel_minutes(prev.zone, job.zone))
            travel_in = travel_minutes(prev.zone, job.zone)
            displaced = (travel_minutes(prev.zone, nxt.zone)
                         if nxt else 0)

        latest = min(job.window_end, tech.shift_end) - job.duration_min
        if nxt is not None:
            latest = min(latest,
                         nxt.start - travel_minutes(job.zone, nxt.zone)
                         - job.duration_min)
        if earliest > latest:
            continue
        start = earliest  # earliest start minimizes lateness within the gap
        incremental_travel = travel_in + (
            travel_minutes(job.zone, nxt.zone) if nxt else 0) - displaced
        lateness = job.priority * max(0, start - job.window_start)
        incremental_cost = incremental_travel + lateness_weight * lateness
        if best is None or incremental_cost < best.incremental_cost - IMPROVEMENT_EPS:
            best = _Slot(start=start, travel_in=travel_in,
                         incremental_cost=incremental_cost)
        # Deterministic tie-break: keep the earlier gap (lower index) on
        # ties, since we scan gaps in order and only replace on strict
        # improvement.
    return best


def _diagnose(job: Job, techs: list[Tech],
              pins: dict[str, str]) -> InfeasibleJob:
    """Explain *why* a job could not be placed. Never returns empty codes."""
    tech_by_id = {t.external_id: t for t in techs}
    pinned_tech_id = pins.get(job.external_id)
    skilled = [t for t in techs if job.skill in t.skills]
    if not skilled:
        if pinned_tech_id is not None:
            return InfeasibleJob(job.external_id, [INF_PIN_SKILL_MISMATCH],
                                 f"Pinned tech {pinned_tech_id!r} does not "
                                 f"hold skill {job.skill!r}, and no other "
                                 f"tech does either.")
        return InfeasibleJob(job.external_id, [INF_NO_SKILLED_TECH],
                             f"No tech holds skill {job.skill!r}.")
    if pinned_tech_id is not None and job.skill not in tech_by_id[pinned_tech_id].skills:
        return InfeasibleJob(job.external_id, [INF_PIN_SKILL_MISMATCH],
                             f"Pinned tech {pinned_tech_id!r} does not hold "
                             f"skill {job.skill!r}.")
    if job.window_end - job.window_start < job.duration_min:
        return InfeasibleJob(job.external_id, [INF_WINDOW_TOO_SHORT],
                             f"Window {fmt_clock(job.window_start)}-"
                             f"{fmt_clock(job.window_end)} is shorter than "
                             f"the {job.duration_min}-minute job.")
    pool = ([tech_by_id[pinned_tech_id]] if pinned_tech_id is not None
            else skilled)
    if not any(t.shift_start < job.window_end and job.window_start < t.shift_end
               for t in pool):
        return InfeasibleJob(job.external_id, [INF_NO_SHIFT_OVERLAP],
                             "Job window does not overlap any candidate "
                             "tech's shift.")
    if pinned_tech_id is not None:
        return InfeasibleJob(job.external_id, [INF_PIN_UNSATISFIABLE],
                             f"Pinned tech {pinned_tech_id!r} has no feasible "
                             f"slot (capacity, travel, or existing load).")
    return InfeasibleJob(job.external_id, [INF_NO_FEASIBLE_SLOT],
                         "No skilled tech has a feasible slot (capacity, "
                         "travel allowances, or existing load).")


def verify_solution(techs: list[Tech], jobs: list[Job],
                    assign: dict[str, Assignment],
                    pins: dict[str, str]) -> list[str]:
    """Re-check every hard constraint on a finished assignment map.

    Returns a list of violation descriptions; empty means clean. Used by
    tests AND by ``run_solver`` before persistence — a non-empty result is
    an internal error, never something shown to a dispatcher as valid.
    """
    violations: list[str] = []
    jobs_by_id = {j.external_id: j for j in jobs}
    tech_by_id = {t.external_id: t for t in techs}
    for job_id, a in assign.items():
        job = jobs_by_id.get(job_id)
        tech = tech_by_id.get(a.tech_id)
        if job is None or tech is None:
            violations.append(f"{job_id}: references unknown job or tech")
            continue
        if job.skill not in tech.skills:
            violations.append(f"{job_id}: skill {job.skill!r} not held by "
                              f"tech {tech.external_id!r}")
        if not (job.window_start <= a.start and
                a.start + job.duration_min <= job.window_end):
            violations.append(f"{job_id}: [{fmt_clock(a.start)}-"
                              f"{fmt_clock(a.start + job.duration_min)}] "
                              f"outside window "
                              f"[{fmt_clock(job.window_start)}-"
                              f"{fmt_clock(job.window_end)}]")
        if not (tech.shift_start <= a.start and
                a.start + job.duration_min <= tech.shift_end):
            violations.append(f"{job_id}: outside shift of "
                              f"{tech.external_id!r}")
        pinned = pins.get(job_id)
        if pinned is not None and pinned != a.tech_id:
            violations.append(f"{job_id}: pin to {pinned!r} violated "
                              f"(assigned to {a.tech_id!r})")
    # Overlap + travel consistency per tech.
    by_tech: dict[str, list[Assignment]] = {t.external_id: [] for t in techs}
    for a in assign.values():
        if a.tech_id in by_tech:
            by_tech[a.tech_id].append(a)
    for tech in techs:
        blocks = _tech_blocks(tech, by_tech[tech.external_id], jobs_by_id)
        for b1, b2 in zip(blocks, blocks[1:]):
            if b1.end > b2.start:
                violations.append(
                    f"tech {tech.external_id!r}: overlapping bookings "
                    f"({b1.job_id or 'commitment'} / {b2.job_id or 'commitment'})")
            need = travel_minutes(b1.zone, b2.zone)
            if b1.end + need > b2.start:
                violations.append(
                    f"tech {tech.external_id!r}: insufficient travel time "
                    f"between {b1.job_id or 'commitment'} and "
                    f"{b2.job_id or 'commitment'}")
    return violations


# ---------------------------------------------------------------------------
# Greedy + local-improvement policy
# ---------------------------------------------------------------------------

class GreedyLocalImprovementPolicy:
    """Default heuristic: greedy construction + relocate/swap improvement.

    ``lateness_weight`` is the documented objective's lateness term;
    ``max_passes`` bounds the improvement loop (0 = greedy only).
    """

    name = "greedy_local_improvement"

    def __init__(self, lateness_weight: float = DEFAULT_LATENESS_WEIGHT,
                 max_passes: int = 20):
        if lateness_weight < 0:
            raise ValueError("lateness_weight must be >= 0")
        if max_passes < 0:
            raise ValueError("max_passes must be >= 0")
        self.lateness_weight = lateness_weight
        self.max_passes = max_passes

    @property
    def params(self) -> dict:
        return {"lateness_weight": self.lateness_weight,
                "max_passes": self.max_passes}

    def solve(self, jobs: list[Job], techs: list[Tech],
              pins: dict[str, str]) -> Solution:
        tech_by_id = {t.external_id: t for t in techs}
        for job_id, tech_id in pins.items():
            if tech_id not in tech_by_id:
                raise DispatchError(f"Pin references unknown tech {tech_id!r}.")
        order = sorted(jobs, key=lambda j: (-j.priority, j.window_start,
                                            j.external_id))
        timelines: dict[str, list[_Block]] = {
            t.external_id: _tech_blocks(t, [], {j.external_id: j for j in jobs})
            for t in techs
        }
        assigned_minutes: dict[str, int] = {t.external_id: 0 for t in techs}
        assign: dict[str, Assignment] = {}
        infeasible: list[InfeasibleJob] = []

        for job in order:
            pinned = pins.get(job.external_id)
            candidates = ([tech_by_id[pinned]] if pinned is not None
                          else list(techs))
            best_tech = None
            best_slot: Optional[_Slot] = None
            for tech in candidates:
                if job.skill not in tech.skills:
                    continue
                slot = _best_slot(tech, job, timelines[tech.external_id],
                                  self.lateness_weight)
                if slot is None:
                    continue
                if (best_slot is None or
                        slot.incremental_cost < best_slot.incremental_cost - IMPROVEMENT_EPS or
                        (abs(slot.incremental_cost - best_slot.incremental_cost) <= IMPROVEMENT_EPS and
                         (assigned_minutes[tech.external_id], tech.external_id) <
                         (assigned_minutes[best_tech.external_id], best_tech.external_id))):
                    best_tech, best_slot = tech, slot
            if best_tech is None or best_slot is None:
                infeasible.append(_diagnose(job, techs, pins))
                continue
            reasons = [REASON_SKILL_MATCH]
            if best_slot.travel_in <= ZONE_PROXIMITY_MAX_MIN:
                reasons.append(REASON_ZONE_PROXIMITY)
            avg_load = (sum(assigned_minutes.values()) / len(techs)
                        if techs else 0)
            if not pinned and assigned_minutes[best_tech.external_id] < avg_load:
                reasons.append(REASON_LOAD_BALANCE)
            if pinned is not None:
                reasons.append(REASON_PINNED)
            else:
                reasons.append(REASON_MIN_INCREMENTAL_COST)
            a = Assignment(job_id=job.external_id, tech_id=best_tech.external_id,
                           start=best_slot.start,
                           travel_minutes=best_slot.travel_in,
                           reason_codes=reasons,
                           duration_min=job.duration_min)
            assign[job.external_id] = a
            timelines[best_tech.external_id] = _tech_blocks(
                best_tech,
                [x for x in assign.values()
                 if x.tech_id == best_tech.external_id],
                {j.external_id: j for j in jobs})
            assigned_minutes[best_tech.external_id] += job.duration_min

        if self.max_passes > 0:
            assign = self._local_improvement(techs, jobs, assign, pins)

        cost, travel, lateness = _solution_cost(techs, jobs, assign,
                                                self.lateness_weight)
        assignments = sorted(assign.values(),
                             key=lambda a: (a.tech_id, a.start))
        return Solution(assignments=assignments, infeasible=infeasible,
                        total_travel=travel, total_lateness=lateness,
                        total_cost=cost)

    # -- local improvement -------------------------------------------------
    def _local_improvement(self, techs: list[Tech], jobs: list[Job],
                           assign: dict[str, Assignment],
                           pins: dict[str, str]) -> dict[str, Assignment]:
        jobs_by_id = {j.external_id: j for j in jobs}
        tech_by_id = {t.external_id: t for t in techs}
        greedy_placement = {jid: (a.tech_id, a.start) for jid, a in assign.items()}

        def blocks_for(tech_id: str, amap: dict[str, Assignment]) -> list[_Block]:
            tech = tech_by_id[tech_id]
            mine = [a for a in amap.values() if a.tech_id == tech_id]
            return _tech_blocks(tech, mine, jobs_by_id)

        def cost_of(amap: dict[str, Assignment]) -> float:
            c, _, _ = _solution_cost(techs, jobs, amap, self.lateness_weight)
            return c

        current = cost_of(assign)
        for _ in range(self.max_passes):
            moved = False
            for job_id in list(assign.keys()):
                if job_id in pins:
                    continue  # pins are hard; the improver never moves them
                job = jobs_by_id[job_id]
                home_tech_id = assign[job_id].tech_id
                # --- relocate to another tech ---
                relocated = False
                for tech in techs:
                    if tech.external_id == home_tech_id:
                        continue
                    if job.skill not in tech.skills:
                        continue
                    trial = dict(assign)
                    del trial[job_id]
                    slot = _best_slot(tech, job,
                                      blocks_for(tech.external_id, trial),
                                      self.lateness_weight)
                    if slot is None:
                        continue
                    trial[job_id] = Assignment(
                        job_id, tech.external_id, slot.start, slot.travel_in,
                        list(assign[job_id].reason_codes),
                        duration_min=job.duration_min)
                    if cost_of(trial) < current - IMPROVEMENT_EPS:
                        assign, current = trial, cost_of(trial)
                        relocated = moved = True
                        break
                if relocated:
                    continue
                # --- swap with another assigned job ---
                for other_id in list(assign.keys()):
                    if other_id == job_id or other_id in pins:
                        continue
                    t1, t2 = assign[job_id].tech_id, assign[other_id].tech_id
                    if t1 == t2:
                        continue
                    job2 = jobs_by_id[other_id]
                    if job.skill not in tech_by_id[t2].skills:
                        continue
                    if job2.skill not in tech_by_id[t1].skills:
                        continue
                    trial = dict(assign)
                    del trial[job_id]
                    del trial[other_id]
                    s1 = _best_slot(tech_by_id[t2], job,
                                    blocks_for(t2, trial), self.lateness_weight)
                    if s1 is None:
                        continue
                    trial[job_id] = Assignment(
                        job_id, t2, s1.start, s1.travel_in,
                        list(assign[job_id].reason_codes),
                        duration_min=job.duration_min)
                    s2 = _best_slot(tech_by_id[t1], job2,
                                    blocks_for(t1, trial), self.lateness_weight)
                    if s2 is None:
                        continue
                    trial[other_id] = Assignment(
                        other_id, t1, s2.start, s2.travel_in,
                        list(assign[other_id].reason_codes),
                        duration_min=job2.duration_min)
                    if cost_of(trial) < current - IMPROVEMENT_EPS:
                        assign, current = trial, cost_of(trial)
                        moved = True
                        break
            if not moved:
                break

        # Refresh explainability for anything the improver touched.
        for job_id, a in assign.items():
            moved_here = greedy_placement.get(job_id) != (a.tech_id, a.start)
            codes = [c for c in a.reason_codes
                     if c not in (REASON_ZONE_PROXIMITY, REASON_LOCAL_IMPROVEMENT)]
            if a.travel_minutes <= ZONE_PROXIMITY_MAX_MIN:
                codes.append(REASON_ZONE_PROXIMITY)
            if moved_here and REASON_LOCAL_IMPROVEMENT not in codes:
                codes.append(REASON_LOCAL_IMPROVEMENT)
            a.reason_codes = codes
        return assign


class NearestAvailableBaseline:
    """Honest baseline: same constraints, myopic choice.

    Jobs are considered in the same order as the greedy policy, but each
    job goes to the skilled tech whose *home zone* is closest, at that
    tech's earliest feasible slot (next-closest on failure). No load
    balancing, no lateness awareness, no improvement pass. The run records
    the solver's gap versus this baseline — whichever direction it goes.
    """

    name = "nearest_available"

    def __init__(self, lateness_weight: float = DEFAULT_LATENESS_WEIGHT):
        self.lateness_weight = lateness_weight

    @property
    def params(self) -> dict:
        return {"lateness_weight": self.lateness_weight}

    def solve(self, jobs: list[Job], techs: list[Tech],
              pins: dict[str, str]) -> Solution:
        tech_by_id = {t.external_id: t for t in techs}
        jobs_by_id = {j.external_id: j for j in jobs}
        order = sorted(jobs, key=lambda j: (-j.priority, j.window_start,
                                            j.external_id))
        assign: dict[str, Assignment] = {}
        infeasible: list[InfeasibleJob] = []
        for job in order:
            pinned = pins.get(job.external_id)
            if pinned is not None:
                candidates = [tech_by_id[pinned]]
            else:
                candidates = sorted(
                    (t for t in techs if job.skill in t.skills),
                    key=lambda t: (travel_minutes(t.home_zone, job.zone),
                                   t.external_id))
            placed = False
            for tech in candidates:
                blocks = _tech_blocks(
                    tech,
                    [a for a in assign.values() if a.tech_id == tech.external_id],
                    jobs_by_id)
                slot = _best_slot(tech, job, blocks, self.lateness_weight)
                if slot is None:
                    continue
                reasons = [REASON_SKILL_MATCH]
                if slot.travel_in <= ZONE_PROXIMITY_MAX_MIN:
                    reasons.append(REASON_ZONE_PROXIMITY)
                if pinned is not None:
                    reasons.append(REASON_PINNED)
                assign[job.external_id] = Assignment(
                    job_id=job.external_id, tech_id=tech.external_id,
                    start=slot.start, travel_minutes=slot.travel_in,
                    reason_codes=reasons, duration_min=job.duration_min)
                placed = True
                break
            if not placed:
                infeasible.append(_diagnose(job, techs, pins))
        cost, travel, lateness = _solution_cost(techs, jobs, assign,
                                                self.lateness_weight)
        return Solution(assignments=sorted(assign.values(),
                                           key=lambda a: (a.tech_id, a.start)),
                        infeasible=infeasible, total_travel=travel,
                        total_lateness=lateness, total_cost=cost)


# ---------------------------------------------------------------------------
# Persistence / service layer
# ---------------------------------------------------------------------------

def _row_to_tech(row: sqlite3.Row) -> Tech:
    load = [c for c in json.loads(row["current_load"] or "[]")]
    return Tech(
        external_id=row["external_id"], name=row["name"],
        skills=frozenset(json.loads(row["skills"] or "[]")),
        home_zone=row["home_zone"], shift_start=row["shift_start"],
        shift_end=row["shift_end"],
        current_load=tuple(
            Commitment(zone=c["zone"], start=c["start"], end=c["end"],
                       label=c.get("label", ""))
            for c in load),
    )


def _event(conn: sqlite3.Connection, event_type: str, actor: str,
           detail: Optional[dict] = None, run_id: Optional[int] = None,
           now: Optional[datetime] = None) -> None:
    created = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO dispatch_events (run_id, event_type, actor, detail,
                                        created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, event_type, actor,
         json.dumps(detail or {}, sort_keys=True), created))
    log_system_event(f"dispatch.{event_type}",
                     {"actor": actor, "run_id": run_id, **(detail or {})})


def create_tech(conn: sqlite3.Connection, raw: Mapping[str, Any],
                actor: str = "system",
                now: Optional[datetime] = None) -> dict:
    """Validate + insert a tech. Natural-key idempotent on ``external_id``."""
    tech = normalize_tech(raw)
    existing = conn.execute(
        "SELECT id FROM dispatch_techs WHERE external_id = ?",
        (tech.external_id,)).fetchone()
    if existing:
        return {"id": existing["id"], "external_id": tech.external_id,
                "replayed": True}
    cur = conn.execute(
        """INSERT INTO dispatch_techs
           (external_id, name, skills, home_zone, shift_start, shift_end,
            current_load, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (tech.external_id, tech.name, json.dumps(sorted(tech.skills)),
         tech.home_zone, tech.shift_start, tech.shift_end,
         json.dumps([{"zone": c.zone, "start": c.start, "end": c.end,
                      "label": c.label} for c in tech.current_load]),
         (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")))
    conn.commit()
    _event(conn, "tech.created", actor,
           {"external_id": tech.external_id, "skills": sorted(tech.skills)},
           now=now)
    return {"id": cur.lastrowid, "external_id": tech.external_id,
            "replayed": False}


def create_job(conn: sqlite3.Connection, raw: Mapping[str, Any],
               actor: str = "system",
               now: Optional[datetime] = None) -> dict:
    """Validate + insert a job. Natural-key idempotent on ``external_id``."""
    job = normalize_job(raw)
    existing = conn.execute(
        "SELECT id FROM dispatch_jobs WHERE external_id = ?",
        (job.external_id,)).fetchone()
    if existing:
        return {"id": existing["id"], "external_id": job.external_id,
                "replayed": True}
    cur = conn.execute(
        """INSERT INTO dispatch_jobs
           (external_id, zone, skill, duration_min, priority, window_start,
            window_end, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (job.external_id, job.zone, job.skill, job.duration_min, job.priority,
         job.window_start, job.window_end,
         (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")))
    conn.commit()
    _event(conn, "job.created", actor,
           {"external_id": job.external_id, "skill": job.skill,
            "zone": job.zone},
           now=now)
    return {"id": cur.lastrowid, "external_id": job.external_id,
            "replayed": False}


def list_techs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM dispatch_techs ORDER BY external_id").fetchall()
    return [dict(r) for r in rows]


def list_jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM dispatch_jobs ORDER BY external_id").fetchall()
    return [dict(r) for r in rows]


def _load_domain(conn: sqlite3.Connection) -> tuple[list[Tech], list[Job]]:
    tech_rows = conn.execute("SELECT * FROM dispatch_techs").fetchall()
    job_rows = conn.execute("SELECT * FROM dispatch_jobs").fetchall()
    techs = [_row_to_tech(r) for r in tech_rows]
    jobs = [Job(external_id=r["external_id"], zone=r["zone"], skill=r["skill"],
                duration_min=r["duration_min"], priority=r["priority"],
                window_start=r["window_start"], window_end=r["window_end"])
            for r in job_rows]
    return techs, jobs


def current_pins(conn: sqlite3.Connection) -> dict[str, str]:
    """Latest override per job: pin/reassign set, unpin clears. {job: tech}."""
    rows = conn.execute(
        """SELECT o.job_id, j.external_id AS job_ext,
                  t.external_id AS tech_ext, o.kind
           FROM dispatch_overrides o
           JOIN dispatch_jobs j ON j.id = o.job_id
           LEFT JOIN dispatch_techs t ON t.id = o.tech_id
           ORDER BY o.id""").fetchall()
    pins: dict[str, str] = {}
    for r in rows:
        if r["kind"] in (OVERRIDE_PIN, OVERRIDE_REASSIGN):
            pins[r["job_ext"]] = r["tech_ext"]
        elif r["kind"] == OVERRIDE_UNPIN:
            pins.pop(r["job_ext"], None)
    return pins


def record_override(conn: sqlite3.Connection, job_external_id: str,
                    tech_external_id: Optional[str], kind: str, reason: str,
                    actor: str = "dispatcher",
                    now: Optional[datetime] = None) -> dict:
    """Record a dispatcher override. The reason is mandatory and audited.

    ``kind``: ``pin`` (job must go to tech), ``reassign`` (pin to a
    different tech — recorded distinctly for the audit trail), ``unpin``
    (release the pin; ``tech_external_id`` may be None). Every later solve
    honors the resulting pins as hard constraints.
    """
    if kind not in OVERRIDE_KINDS:
        raise ValidationError({"kind": f"Must be one of {OVERRIDE_KINDS}."})
    reason = (reason or "").strip()
    if len(reason) < OVERRIDE_REASON_MIN_CHARS:
        raise ValidationError(
            {"reason": f"An override reason is required "
                       f"(>= {OVERRIDE_REASON_MIN_CHARS} chars) — every "
                       f"override is audited."})
    job = conn.execute(
        "SELECT id FROM dispatch_jobs WHERE external_id = ?",
        (job_external_id,)).fetchone()
    if job is None:
        raise KeyError(f"No job {job_external_id!r}.")
    tech_id = None
    if kind in (OVERRIDE_PIN, OVERRIDE_REASSIGN):
        if not tech_external_id:
            raise ValidationError(
                {"tech_id": f"{kind} requires a tech."})
        tech = conn.execute(
            "SELECT id FROM dispatch_techs WHERE external_id = ?",
            (tech_external_id,)).fetchone()
        if tech is None:
            raise KeyError(f"No tech {tech_external_id!r}.")
        tech_id = tech["id"]
    cur = conn.execute(
        """INSERT INTO dispatch_overrides
           (job_id, tech_id, kind, reason, actor, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job["id"], tech_id, kind, reason, actor,
         (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")))
    conn.commit()
    _event(conn, "override.recorded", actor,
           {"job": job_external_id, "tech": tech_external_id, "kind": kind,
            "reason": reason},
           now=now)
    return {"id": cur.lastrowid, "job": job_external_id,
            "tech": tech_external_id, "kind": kind}


def list_overrides(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT o.id, j.external_id AS job, t.external_id AS tech,
                  o.kind, o.reason, o.actor, o.created_at
           FROM dispatch_overrides o
           JOIN dispatch_jobs j ON j.id = o.job_id
           LEFT JOIN dispatch_techs t ON t.id = o.tech_id
           ORDER BY o.id DESC""").fetchall()
    return [dict(r) for r in rows]


def run_solver(conn: sqlite3.Connection,
               policy: Optional[DispatchPolicy] = None,
               actor: str = "system",
               now: Optional[datetime] = None) -> dict:
    """Run the solver (plus baseline) over all current techs/jobs.

    Honors dispatcher pins as hard constraints, persists the run with its
    assignments, infeasibility report, and the honest baseline gap, and
    returns a summary dict.
    """
    policy = policy or GreedyLocalImprovementPolicy()
    techs, jobs = _load_domain(conn)
    pins = current_pins(conn)
    t0 = time.perf_counter()

    solution = policy.solve(jobs, techs, pins)
    violations = verify_solution(techs, jobs,
                                 {a.job_id: a for a in solution.assignments},
                                 pins)
    if violations:
        # Structural invariant broken — never persist a bad plan.
        raise DispatchError(
            "Solver produced constraint violations: " + "; ".join(violations))

    baseline = NearestAvailableBaseline(
        lateness_weight=getattr(policy, "lateness_weight",
                                DEFAULT_LATENESS_WEIGHT))
    baseline_solution = baseline.solve(jobs, techs, pins)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    if baseline_solution.total_cost > 0:
        gap_pct = ((baseline_solution.total_cost - solution.total_cost)
                   / baseline_solution.total_cost * 100.0)
    else:
        gap_pct = 0.0

    created = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO dispatch_runs
           (solver, policy_params, total_cost, total_travel, total_lateness,
            baseline_cost, baseline_travel, cost_gap_pct, assigned_count,
            infeasible_count, duration_ms, actor, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (policy.name, json.dumps(policy.params, sort_keys=True),
         solution.total_cost, solution.total_travel, solution.total_lateness,
         baseline_solution.total_cost, baseline_solution.total_travel,
         gap_pct, len(solution.assignments), len(solution.infeasible),
         duration_ms, actor, created))
    run_id = cur.lastrowid
    for a in solution.assignments:
        if not a.reason_codes:
            raise DispatchError(f"Assignment {a.job_id} has no reason codes.")
        for code in a.reason_codes:
            if code not in REASON_CODES:
                raise DispatchError(f"Unknown reason code {code!r}.")
        conn.execute(
            """INSERT INTO dispatch_assignments
               (run_id, job_id, tech_id, scheduled_start, scheduled_end,
                travel_minutes, reason_codes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, _job_pk(conn, a.job_id), _tech_pk(conn, a.tech_id),
             a.start, a.start + a.duration_min, a.travel_minutes,
             json.dumps(a.reason_codes), created))
    for inf in solution.infeasible:
        conn.execute(
            """INSERT INTO dispatch_infeasibility
               (run_id, job_id, violated, detail, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, _job_pk(conn, inf.job_id),
             json.dumps(inf.violated), inf.detail, created))
    conn.commit()
    _event(conn, "run.completed", actor,
           {"run_id": run_id, "solver": policy.name,
            "assigned": len(solution.assignments),
            "infeasible": len(solution.infeasible),
            "cost": round(solution.total_cost, 2),
            "baseline_cost": round(baseline_solution.total_cost, 2),
            "gap_pct": round(gap_pct, 2)},
           run_id=run_id, now=now)
    return {
        "run_id": run_id,
        "solver": policy.name,
        "assigned": len(solution.assignments),
        "infeasible": len(solution.infeasible),
        "total_cost": solution.total_cost,
        "total_travel": solution.total_travel,
        "total_lateness": solution.total_lateness,
        "baseline_cost": baseline_solution.total_cost,
        "baseline_travel": baseline_solution.total_travel,
        "cost_gap_pct": gap_pct,
        "duration_ms": duration_ms,
    }


def _job_pk(conn: sqlite3.Connection, external_id: str) -> int:
    row = conn.execute("SELECT id FROM dispatch_jobs WHERE external_id = ?",
                       (external_id,)).fetchone()
    return row["id"]


def _tech_pk(conn: sqlite3.Connection, external_id: str) -> int:
    row = conn.execute("SELECT id FROM dispatch_techs WHERE external_id = ?",
                       (external_id,)).fetchone()
    return row["id"]


def run_detail(conn: sqlite3.Connection, run_id: int) -> dict:
    """Full run view: assignments with reason codes, baseline gap, infeasibility."""
    run = conn.execute("SELECT * FROM dispatch_runs WHERE id = ?",
                       (run_id,)).fetchone()
    if run is None:
        raise KeyError(f"No run {run_id}.")
    assigns = conn.execute(
        """SELECT a.*, j.external_id AS job_ext, j.zone, j.skill,
                  j.duration_min, j.priority, j.window_start, j.window_end,
                  t.external_id AS tech_ext, t.name AS tech_name
           FROM dispatch_assignments a
           JOIN dispatch_jobs j ON j.id = a.job_id
           JOIN dispatch_techs t ON t.id = a.tech_id
           WHERE a.run_id = ? ORDER BY t.external_id, a.scheduled_start""",
        (run_id,)).fetchall()
    infeasible = conn.execute(
        """SELECT i.*, j.external_id AS job_ext, j.zone, j.skill,
                  j.duration_min, j.priority, j.window_start, j.window_end
           FROM dispatch_infeasibility i
           JOIN dispatch_jobs j ON j.id = i.job_id
           WHERE i.run_id = ? ORDER BY j.external_id""",
        (run_id,)).fetchall()
    return {
        "run": dict(run),
        "assignments": [dict(r) for r in assigns],
        "infeasible": [dict(r) for r in infeasible],
    }


def latest_run_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM dispatch_runs ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def seed_demo(conn: sqlite3.Connection, seed: int = 7, n_techs: int = 6,
              n_jobs: int = 24, actor: str = "demo") -> dict:
    """Load a deterministic synthetic demo day (techs + jobs)."""
    tech_dicts, job_dicts = synthetic_day(seed, n_techs, n_jobs)
    created_techs = sum(
        1 for t in tech_dicts
        if not create_tech(conn, t, actor=actor)["replayed"])
    created_jobs = sum(
        1 for j in job_dicts
        if not create_job(conn, j, actor=actor)["replayed"])
    return {"seed": seed, "techs_created": created_techs,
            "jobs_created": created_jobs,
            "techs_total": len(list_techs(conn)),
            "jobs_total": len(list_jobs(conn))}
