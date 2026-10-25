"""Project Q09 — Technician Dispatch Optimizer: data model.

Defines the synthetic domain (zones, jobs, technicians, constraints,
reason codes) plus deterministic synthetic-fixture generators.

ALL DATA IS SYNTHETIC. Zone geography is a fabricated 4x4 grid, technician
names are invented, and every job is a generated record. Nothing here
represents a real service territory, real people, or real customers.

Concepts
--------
* **Zone** — one cell of a synthetic 4x4 service grid (``A1`` .. ``D4``).
  Travel time between zones is a deterministic function of Manhattan
  distance; it is a model of travel, not a claim about any real place.
* **Job** — work to be scheduled: zone, required skill, duration, priority
  (1-5), and a hard time window ``[window_start, window_end)`` in minutes
  since midnight.
* **Tech** — a technician: skill set, home zone, shift ``[shift_start,
  shift_end)``, and a list of pre-existing ``current_load`` commitments that
  block time on the shift.
* **Constraint** — hard rules the solver must never violate (see
  ``HARD_CONSTRAINTS``): skill match, window containment, shift
  containment, no overlapping bookings on one tech, and pin compliance.
* **Reason codes** — every assignment carries at least one code explaining
  *why* it was made (``REASON_CODES``).

This module is intentionally free of solver logic: it validates input,
describes constraints, and generates fixtures. The heuristic lives in
:mod:`mavenu.dispatch`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .validation import ValidationError

#: Skills the dispatcher knows about. A strict subset of the portfolio's
#: service verticals — dispatch only schedules these four.
DISPATCH_SKILLS = ("hvac", "plumbing", "electrical", "roofing")

#: Priorities. Higher = more urgent. Used as a lateness-penalty weight.
PRIORITY_MIN = 1
PRIORITY_MAX = 5

#: Synthetic workday bounds (minutes since midnight) used by fixture
#: generators. Real deployments must supply their own shift rules.
DAY_START = 8 * 60    # 08:00
DAY_END = 17 * 60     # 17:00

#: Grid dimensions of the synthetic zone map (4 columns x 4 rows).
GRID_COLS = 4
GRID_ROWS = 4

#: Travel model: intra-zone base minutes + this many minutes per unit of
#: Manhattan distance. Deterministic and fully documented — a stand-in for
#: a routing engine, never presented as one.
INTRA_ZONE_MINUTES = 5
MINUTES_PER_GRID_STEP = 4

#: Hard constraints. Documented here and enforced by the solver; the test
#: suite asserts zero violations of each across thousands of synthetic
#: dispatches.
HARD_CONSTRAINTS = (
    "skill_match",        # tech.skills must contain job.skill
    "window_fit",         # [start, start+duration] inside job window
    "shift_fit",          # [start, start+duration] inside tech shift
    "no_overlap",         # no two bookings overlap on one tech
    "travel_consistent",  # travel allowances are honored between bookings
    "pin_compliance",     # dispatcher pins are honored or reported
)

#: Reason codes attached to every assignment for explainability.
REASON_SKILL_MATCH = "SKILL_MATCH"                 # tech holds the skill
REASON_ZONE_PROXIMITY = "ZONE_PROXIMITY"          # short travel (<=10 min)
REASON_LOAD_BALANCE = "LOAD_BALANCE"               # tech was under average load
REASON_PINNED = "PINNED"                           # dispatcher pinned it here
REASON_MIN_INCREMENTAL_COST = "MIN_INCREMENTAL_COST"  # cheapest incremental cost among candidates
REASON_LOCAL_IMPROVEMENT = "LOCAL_IMPROVEMENT"     # placed/moved by the local-improvement pass

REASON_CODES = (
    REASON_SKILL_MATCH,
    REASON_ZONE_PROXIMITY,
    REASON_LOAD_BALANCE,
    REASON_PINNED,
    REASON_MIN_INCREMENTAL_COST,
    REASON_LOCAL_IMPROVEMENT,
)

#: Infeasibility reason codes — explicit, per-job, never silent.
INF_NO_SKILLED_TECH = "NO_TECH_WITH_SKILL"
INF_PIN_SKILL_MISMATCH = "PIN_SKILL_MISMATCH"
INF_PIN_UNSATISFIABLE = "PIN_UNSATISFIABLE"
INF_WINDOW_TOO_SHORT = "WINDOW_TOO_SHORT_FOR_DURATION"
INF_NO_SHIFT_OVERLAP = "NO_SHIFT_OVERLAP_WITH_WINDOW"
INF_NO_FEASIBLE_SLOT = "NO_FEASIBLE_SLOT"

#: Override kinds recorded in the audit trail.
OVERRIDE_PIN = "pin"
OVERRIDE_REASSIGN = "reassign"
OVERRIDE_UNPIN = "unpin"
OVERRIDE_KINDS = (OVERRIDE_PIN, OVERRIDE_REASSIGN, OVERRIDE_UNPIN)

OVERRIDE_REASON_MIN_CHARS = 8

JOB_ID_MAX_CHARS = 64
TECH_NAME_MAX_CHARS = 120


def zones() -> list[str]:
    """All synthetic zone labels, e.g. ``['A1', 'A2', ..., 'D4']``."""
    return [
        f"{chr(ord('A') + row)}{col + 1}"
        for row in range(GRID_ROWS)
        for col in range(GRID_COLS)
    ]


_ZONE_SET = frozenset(zones())


def zone_coords(zone: str) -> tuple[int, int]:
    """(col, row) grid coordinates of a zone. Raises ValueError if unknown."""
    if zone not in _ZONE_SET:
        raise ValueError(f"Unknown zone {zone!r}.")
    row = ord(zone[0]) - ord("A")
    col = int(zone[1:]) - 1
    return col, row


def travel_minutes(from_zone: str, to_zone: str) -> int:
    """Deterministic synthetic travel time between two zones.

    5 minutes intra-zone + 4 minutes per Manhattan grid step. This is a
    *model* of travel for the demo — it is not a routing engine and is
    never presented as one.
    """
    c1, r1 = zone_coords(from_zone)
    c2, r2 = zone_coords(to_zone)
    return INTRA_ZONE_MINUTES + MINUTES_PER_GRID_STEP * (abs(c1 - c2) + abs(r1 - r2))


def fmt_clock(minutes: int) -> str:
    """Minutes-since-midnight -> 'HH:MM' (24h)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Commitment:
    """A pre-existing block on a tech's shift (the 'current load').

    ``label`` is free text (e.g. the source system's appointment name);
    synthetic only.
    """
    zone: str
    start: int
    end: int
    label: str = ""


@dataclass(frozen=True)
class Tech:
    external_id: str
    name: str
    skills: frozenset
    home_zone: str
    shift_start: int
    shift_end: int
    current_load: tuple = ()


@dataclass(frozen=True)
class Job:
    external_id: str
    zone: str
    skill: str
    duration_min: int
    priority: int
    window_start: int
    window_end: int


@dataclass
class Assignment:
    """One scheduled job inside a solver run."""
    job_id: str
    tech_id: str
    start: int
    travel_minutes: int
    reason_codes: list = field(default_factory=list)
    duration_min: int = 0  # filled in by the solver before returning

    @property
    def end(self) -> int:
        return self.start + self.duration_min


@dataclass
class InfeasibleJob:
    """A job the solver could not place, with explicit violated constraints."""
    job_id: str
    violated: list  # list of infeasibility codes
    detail: str = ""


@dataclass
class Solution:
    """Pure solver output (before persistence)."""
    assignments: list        # list[Assignment] with duration_min attached
    infeasible: list          # list[InfeasibleJob]
    total_travel: int
    total_lateness: int       # priority-weighted delay beyond window_start
    total_cost: float


def _check_int(value: Any, name: str, errors: dict, lo: int, hi: int) -> Optional[int]:
    if isinstance(value, bool):
        errors[name] = "Must be an integer."
        return None
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        errors[name] = "Must be an integer."
        return None
    if isinstance(value, float) and not value.is_integer():
        errors[name] = "Must be an integer."
        return None
    if not lo <= ivalue <= hi:
        errors[name] = f"Must be between {lo} and {hi}."
        return None
    return ivalue


def normalize_job(raw: Mapping[str, Any]) -> Job:
    """Validate and normalize one job payload. Raises ValidationError."""
    if not isinstance(raw, Mapping):
        raise ValidationError({"job": "Job must be an object."})
    errors: dict[str, str] = {}

    external_id = str(raw.get("external_id") or "").strip()
    if not external_id:
        errors["external_id"] = "External ID is required."
    elif len(external_id) > JOB_ID_MAX_CHARS:
        errors["external_id"] = f"Must be <= {JOB_ID_MAX_CHARS} chars."

    zone = str(raw.get("zone") or "").strip().upper()
    if zone not in _ZONE_SET:
        errors["zone"] = f"Must be one of {', '.join(zones())}."

    skill = str(raw.get("skill") or "").strip().lower()
    if skill not in DISPATCH_SKILLS:
        errors["skill"] = f"Must be one of {', '.join(DISPATCH_SKILLS)}."

    duration = _check_int(raw.get("duration_min"), "duration_min", errors, 15, 480)
    priority = _check_int(raw.get("priority"), "priority", errors,
                          PRIORITY_MIN, PRIORITY_MAX)
    wstart = _check_int(raw.get("window_start"), "window_start", errors, 0, 1439)
    wend = _check_int(raw.get("window_end"), "window_end", errors, 1, 1440)

    if wstart is not None and wend is not None:
        if wstart >= wend:
            errors["window"] = "window_start must be before window_end."
        elif duration is not None and (wend - wstart) < duration:
            # Window shorter than the job is NOT a creation error: it is a
            # dispatch-time infeasibility the solver must report explicitly.
            # Creation accepts it so the infeasibility path is exercisable.
            pass

    if errors:
        raise ValidationError(errors)
    return Job(external_id=external_id, zone=zone, skill=skill,
               duration_min=duration, priority=priority,
               window_start=wstart, window_end=wend)


def normalize_tech(raw: Mapping[str, Any]) -> Tech:
    """Validate and normalize one tech payload. Raises ValidationError."""
    if not isinstance(raw, Mapping):
        raise ValidationError({"tech": "Tech must be an object."})
    errors: dict[str, str] = {}

    external_id = str(raw.get("external_id") or "").strip()
    if not external_id:
        errors["external_id"] = "External ID is required."
    elif len(external_id) > JOB_ID_MAX_CHARS:
        errors["external_id"] = f"Must be <= {JOB_ID_MAX_CHARS} chars."

    name = str(raw.get("name") or "").strip()
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > TECH_NAME_MAX_CHARS:
        errors["name"] = f"Must be <= {TECH_NAME_MAX_CHARS} chars."

    raw_skills = raw.get("skills")
    if isinstance(raw_skills, str):
        raw_skills = [s.strip() for s in raw_skills.split(",")]
    skills: frozenset = frozenset()
    if not raw_skills:
        errors["skills"] = "At least one skill is required."
    else:
        cleaned = []
        for s in raw_skills:
            s = str(s).strip().lower()
            if s not in DISPATCH_SKILLS:
                errors["skills"] = (
                    f"Unknown skill {s!r}; must be one of "
                    f"{', '.join(DISPATCH_SKILLS)}."
                )
                break
            cleaned.append(s)
        else:
            skills = frozenset(cleaned)
            if not skills:
                errors["skills"] = "At least one skill is required."

    home_zone = str(raw.get("home_zone") or "").strip().upper()
    if home_zone not in _ZONE_SET:
        errors["home_zone"] = f"Must be one of {', '.join(zones())}."

    sstart = _check_int(raw.get("shift_start"), "shift_start", errors, 0, 1439)
    send = _check_int(raw.get("shift_end"), "shift_end", errors, 1, 1440)
    if sstart is not None and send is not None and sstart >= send:
        errors["shift"] = "shift_start must be before shift_end."

    load: list[Commitment] = []
    raw_load = raw.get("current_load") or []
    if not isinstance(raw_load, Sequence) or isinstance(raw_load, (str, bytes)):
        errors["current_load"] = "Must be a list of commitments."
    else:
        for i, item in enumerate(raw_load):
            if not isinstance(item, Mapping):
                errors[f"current_load[{i}]"] = "Must be an object."
                break
            z = str(item.get("zone") or "").strip().upper()
            if z not in _ZONE_SET:
                errors[f"current_load[{i}].zone"] = "Unknown zone."
                break
            cs = _check_int(item.get("start"), f"current_load[{i}].start",
                            errors, 0, 1439)
            ce = _check_int(item.get("end"), f"current_load[{i}].end",
                            errors, 1, 1440)
            if cs is None or ce is None:
                break
            if cs >= ce:
                errors[f"current_load[{i}]"] = "start must be before end."
                break
            if sstart is not None and send is not None and not (
                    sstart <= cs and ce <= send):
                errors[f"current_load[{i}]"] = (
                    "Commitment must lie within the tech's shift.")
                break
            load.append(Commitment(zone=z, start=cs, end=ce,
                                   label=str(item.get("label") or "")))
        else:
            ordered = sorted(load, key=lambda c: c.start)
            for a, b in zip(ordered, ordered[1:]):
                if a.end > b.start:
                    errors["current_load"] = (
                        "Commitments must not overlap.")
                    break

    if errors:
        raise ValidationError(errors)
    return Tech(external_id=external_id, name=name, skills=skills,
                home_zone=home_zone, shift_start=sstart, shift_end=send,
                current_load=tuple(load))


# ---------------------------------------------------------------------------
# Deterministic synthetic fixtures
# ---------------------------------------------------------------------------

_SYNTHETIC_NAMES = (
    "Alex Morgan", "Jordan Lee", "Taylor Kim", "Casey Rivera", "Riley Chen",
    "Avery Brooks", "Quinn Patel", "Dakota Smith", "Emerson Reed",
    "Finley Cruz", "Harper Lane", "Rowan Diaz", "Sage Moreno", "Ellis Ford",
    "Marlow Quinn", "Devon Hart", "Kai Bell", "Reese Cole", "Noor Haddad",
    "Sam Whitaker",
)
# All names above are invented for the demo; none are real people.


def synthetic_techs(seed: int, n: int) -> list[dict]:
    """Deterministic synthetic tech roster. ``seed`` makes it reproducible."""
    rng = random.Random(seed)
    zone_list = zones()
    out = []
    for i in range(n):
        n_skills = rng.choice([1, 1, 2, 2, 3])
        skills = rng.sample(list(DISPATCH_SKILLS), n_skills)
        home = rng.choice(zone_list)
        sstart = DAY_START + rng.choice([0, 0, 30, 60])
        send = DAY_END - rng.choice([0, 0, 30, 60])
        load = []
        # ~40% of techs start the day with one existing commitment.
        if rng.random() < 0.4:
            z = rng.choice(zone_list)
            dur = rng.choice([30, 45, 60, 90])
            cs = sstart + rng.choice([0, 30, 60, 90])
            if cs + dur <= send:
                load.append({"zone": z, "start": cs, "end": cs + dur,
                             "label": "existing appointment"})
        out.append({
            "external_id": f"tech-{seed}-{i + 1:02d}",
            "name": _SYNTHETIC_NAMES[i % len(_SYNTHETIC_NAMES)],
            "skills": skills,
            "home_zone": home,
            "shift_start": sstart,
            "shift_end": send,
            "current_load": load,
        })
    return out


def synthetic_jobs(seed: int, n: int, infeasible_fraction: float = 0.05) -> list[dict]:
    """Deterministic synthetic job list.

    A small ``infeasible_fraction`` of jobs are deliberately impossible
    (unknown-skill demand is impossible at creation, so these use windows
    shorter than the job duration) to exercise the infeasibility report.
    """
    rng = random.Random(10_000 + seed)
    zone_list = zones()
    out = []
    n_bad = max(1, int(n * infeasible_fraction)) if n >= 10 else 0
    bad_idx = set(rng.sample(range(n), n_bad)) if n_bad else set()
    for i in range(n):
        skill = rng.choice(list(DISPATCH_SKILLS))
        zone = rng.choice(zone_list)
        duration = rng.choice([30, 45, 60, 60, 90, 120])
        priority = rng.choices([1, 2, 3, 4, 5], weights=[10, 25, 30, 20, 15])[0]
        wstart = DAY_START + rng.choice([0, 60, 120, 180, 240, 300])
        span = rng.choice([180, 240, 300, 420, 480])
        wend = min(wstart + span, DAY_END)
        if i in bad_idx:
            # Deliberately infeasible: window shorter than the job itself.
            wstart, wend = DAY_START + 60, DAY_START + 60 + max(duration - 30, 15)
        out.append({
            "external_id": f"job-{seed}-{i + 1:03d}",
            "zone": zone,
            "skill": skill,
            "duration_min": duration,
            "priority": priority,
            "window_start": wstart,
            "window_end": wend,
        })
    return out


def synthetic_day(seed: int, n_techs: int = 6, n_jobs: int = 30) -> tuple[list[dict], list[dict]]:
    """One deterministic synthetic dispatch day: (tech dicts, job dicts)."""
    return synthetic_techs(seed, n_techs), synthetic_jobs(seed, n_jobs)
