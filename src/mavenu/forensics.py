"""S03 — Digital Forensic Applications: Acquisition to Report.

=====================================================================
SYNTHETIC DATA ONLY. METHOD DEMONSTRATION — NOT CASEWORK EXPERIENCE.
=====================================================================

This module implements a *repeatable, defensible* digital-evidence
workflow on **synthetic fixtures only**:

    preparation  ->  acquisition (hashed)  ->  examination  ->
    analysis (timeline + hypotheses)  ->  reporting (facts vs inference)

The "disk image" is never a real device. It is a synthetic directory
tree plus a manifest the module itself generates
(:func:`generate_synthetic_case`), or an equivalent fixture tree the
caller provides. Nothing in this module may be used to image, access,
or examine a real person's device, and it provides no mechanism to
bypass encryption or access controls. Authorization is a *synthetic
record* (a required intake field), not a legal instrument.

Discipline controls (the actual product of this project):

* **Integrity:** every handoff is hash-chained (SHA-256, stdlib
  ``hashlib``). Acquisition captures a start hash (directory listing
  snapshot) and an end hash (manifest hash); any post-acquisition
  modification of the source tree is detectable via
  :func:`verify_acquisition` / :func:`verify_chain`.
* **Confirmation bias:** a hypothesis is rejected unless it names BOTH
  supporting AND contradicting evidence.
* **Overclaiming attribution:** every inference in a report must carry
  an explicit confidence level (``low`` / ``medium`` / ``high``);
  ``unresolved`` is an allowed finding; facts must cite evidence.
* **Read-only handling:** the source tree is opened read-only
  (``'rb'``) and is never written to. This module documents the
  write-blocking *concept*; the fixture generator never needs it.

Status vocabulary: Implemented, Tested, Simulated, Demo.
The acquisition/examination/timeline/reporting workflow is
Implemented+Tested; the "disk image" itself is Simulated.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .db import utcnow_iso
from .validation import ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGES = ("intake", "acquired", "examined", "analyzed", "reported")
CONFIDENCE_LEVELS = ("low", "medium", "high")
TIMELINE_TOLERANCE_SECONDS = 60
LOG_LINE_RE = re.compile(r"^(?P<ts>\S+)\s+(?P<body>.*)$")
KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
GENESIS_HASH = "0" * 64

# Synthetic-usernames used ONLY inside generated fixtures / docs.
SYNTHETIC_USER = "demo-user"
SYNTHETIC_HOST = "WS-07"


class ForensicsError(Exception):
    """Workflow/state error (as opposed to a validation error)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_iso(clock: Optional[Callable[[], str]] = None) -> str:
    """Injectable clock: ``clock()`` must return an ISO-8601 string."""
    return clock() if clock is not None else utcnow_iso()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """SHA-256 of a file's bytes, streamed in 64 KiB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:  # read-only: never writes to the source
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_ts(ts: str) -> datetime:
    text = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Chain of custody (hash chain across every handoff)
# ---------------------------------------------------------------------------

def chain_step(
    conn: sqlite3.Connection,
    case_id: int,
    step: str,
    payload: str,
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Append a hash-chained custody entry.

    ``payload_hash = SHA-256(prev_hash + ":" + step + ":" + payload)``.
    Any gap or rewrite in the sequence breaks :func:`verify_chain`.
    """
    if not step or not isinstance(step, str):
        raise ValidationError({"step": "step name is required."})
    row = conn.execute(
        "SELECT payload_hash FROM forensics_hashchain "
        "WHERE case_id = ? ORDER BY id DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    prev = row["payload_hash"] if row else GENESIS_HASH
    payload_hash = _sha256_hex(f"{prev}:{step}:{payload}".encode("utf-8"))
    created = now_iso(clock)
    cur = conn.execute(
        "INSERT INTO forensics_hashchain "
        "(case_id, step, payload, payload_hash, prev_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, step, payload, payload_hash, prev, created),
    )
    conn.commit()
    return {
        "id": cur.lastrowid,
        "case_id": case_id,
        "step": step,
        "payload": payload,
        "payload_hash": payload_hash,
        "prev_hash": prev,
        "created_at": created,
    }


def get_chain(conn: sqlite3.Connection, case_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM forensics_hashchain WHERE case_id = ? ORDER BY id",
        (case_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def verify_chain(conn: sqlite3.Connection, case_id: int) -> dict:
    """Recompute the whole chain; report the first break, if any."""
    prev = GENESIS_HASH
    for entry in get_chain(conn, case_id):
        expected = _sha256_hex(
            f"{prev}:{entry['step']}:{entry['payload']}".encode("utf-8")
        )
        if entry["prev_hash"] != prev or entry["payload_hash"] != expected:
            return {"ok": False, "broken_at": entry["id"], "step": entry["step"]}
        prev = entry["payload_hash"]
    return {"ok": True, "broken_at": None, "step": None, "entries": len(get_chain(conn, case_id))}


# ---------------------------------------------------------------------------
# Preparation: case intake + synthetic authorization record
# ---------------------------------------------------------------------------

def _validate_intake(
    title: str,
    description: str,
    authorizer_name: str,
    authorization_ref: str,
    handling_plan: list,
) -> dict:
    errors: dict[str, str] = {}
    if not (isinstance(title, str) and title.strip()):
        errors["title"] = "Case title is required."
    if not (isinstance(description, str) and description.strip()):
        errors["description"] = "Case description is required."
    if not (isinstance(authorizer_name, str) and authorizer_name.strip()):
        errors["authorizer_name"] = (
            "Authorizer name is required (synthetic authorization record)."
        )
    if not (
        isinstance(authorization_ref, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-_/]{2,63}", authorization_ref.strip())
    ):
        errors["authorization_ref"] = (
            "Authorization reference is required (e.g. 'AUTH-2026-0142')."
        )
    if not isinstance(handling_plan, list) or len(handling_plan) < 3 or not all(
        isinstance(s, str) and s.strip() for s in handling_plan
    ):
        errors["handling_plan"] = (
            "Handling plan must be a list of at least 3 non-empty steps."
        )
    if errors:
        raise ValidationError(errors)
    return {
        "title": title.strip(),
        "description": description.strip(),
        "authorizer_name": authorizer_name.strip(),
        "authorization_ref": authorization_ref.strip(),
        "handling_plan": [s.strip() for s in handling_plan],
    }


def open_case(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str,
    authorizer_name: str,
    authorization_ref: str,
    handling_plan: list,
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Intake a new synthetic case.

    The authorization record is *synthetic*: it documents that the intake
    procedure requires written authorization before any acquisition, but it
    is not itself a legal instrument.
    """
    clean = _validate_intake(
        title, description, authorizer_name, authorization_ref, handling_plan
    )
    created = now_iso(clock)
    cur = conn.execute(
        "INSERT INTO forensics_cases "
        "(case_ref, title, description, authorizer_name, authorization_ref, "
        " handling_plan_json, status, created_at) "
        "VALUES ('PENDING', ?, ?, ?, ?, ?, 'intake', ?)",
        (
            clean["title"],
            clean["description"],
            clean["authorizer_name"],
            clean["authorization_ref"],
            json.dumps(clean["handling_plan"]),
            created,
        ),
    )
    case_id = cur.lastrowid
    case_ref = f"FOR-{case_id:06d}"
    conn.execute(
        "UPDATE forensics_cases SET case_ref = ? WHERE id = ?", (case_ref, case_id)
    )
    conn.commit()
    chain_step(conn, case_id, "case.opened", case_ref, clock=clock)
    return get_case(conn, case_id)


def get_case(conn: sqlite3.Connection, case_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM forensics_cases WHERE id = ?", (case_id,)
    ).fetchone()
    if row is None:
        raise ForensicsError(f"No case with id {case_id}.")
    case = dict(row)
    case["handling_plan"] = json.loads(case["handling_plan_json"])
    return case


def list_cases(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM forensics_cases ORDER BY id").fetchall()
    cases = []
    for row in rows:
        case = dict(row)
        case["handling_plan"] = json.loads(case["handling_plan_json"])
        cases.append(case)
    return cases


def _set_status(conn: sqlite3.Connection, case_id: int, status: str) -> None:
    if status not in STAGES:
        raise ValidationError({"status": f"Unknown stage {status!r}."})
    conn.execute("UPDATE forensics_cases SET status = ? WHERE id = ?", (status, case_id))
    conn.commit()

# ---------------------------------------------------------------------------
# Acquisition: hashed, read-only walk of the synthetic tree
# ---------------------------------------------------------------------------

def _walk_tree(source_dir: str) -> list[str]:
    """Sorted relative paths of all regular files under ``source_dir``."""
    rels: list[str] = []
    for root, dirs, files in os.walk(source_dir):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.isfile(full) and not os.path.islink(full):
                rels.append(os.path.relpath(full, source_dir))
    return rels


def build_manifest(source_dir: str) -> dict:
    """Per-file manifest: ``{rel_path: {"sha256": ..., "size": ...}}``.

    Read-only: files are opened ``'rb'`` and never written.
    """
    manifest: dict[str, dict] = {}
    for rel in _walk_tree(source_dir):
        full = os.path.join(source_dir, rel)
        manifest[rel] = {
            "sha256": sha256_file(full),
            "size": os.path.getsize(full),
        }
    return manifest


def manifest_hash(manifest: dict) -> str:
    """Case-level integrity hash of the canonical manifest."""
    return _sha256_hex(_canonical(manifest).encode("utf-8"))


def run_acquisition(
    conn: sqlite3.Connection,
    case_id: int,
    source_dir: str,
    *,
    method: str = "synthetic-walk",
    source_label: str = "synthetic-fixture",
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Acquire the synthetic tree: hash capture at start and end.

    * ``start_hash`` — SHA-256 of the canonical sorted file list
      (directory snapshot before reading content).
    * ``manifest_hash`` — SHA-256 of the canonical per-file manifest
      after all bytes are read.

    Stores the acquisition row, appends hash-chain steps, and moves the
    case to the ``acquired`` stage. Raises :class:`ForensicsError` if the
    case is not in the ``intake`` stage (repeat acquisitions would fork
    the chain of custody; open a new case instead).
    """
    case = get_case(conn, case_id)
    if case["status"] != "intake":
        raise ForensicsError(
            f"Case {case['case_ref']} is at stage {case['status']!r}; "
            "acquisition requires stage 'intake'."
        )
    if not os.path.isdir(source_dir):
        raise ValidationError({"source_dir": f"Not a directory: {source_dir}"})

    started = now_iso(clock)
    rel_paths = _walk_tree(source_dir)
    start_hash = _sha256_hex(_canonical(rel_paths).encode("utf-8"))
    chain_step(conn, case_id, "acquisition.start", start_hash, clock=clock)

    manifest = build_manifest(source_dir)
    mhash = manifest_hash(manifest)
    finished = now_iso(clock)
    total_bytes = sum(entry["size"] for entry in manifest.values())

    cur = conn.execute(
        "INSERT INTO forensics_acquisitions "
        "(case_id, method, source_label, started_at, finished_at, start_hash, "
        " manifest_json, manifest_hash, file_count, total_bytes, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'complete')",
        (
            case_id,
            method,
            source_label,
            started,
            finished,
            start_hash,
            _canonical(manifest),
            mhash,
            len(manifest),
            total_bytes,
        ),
    )
    acq_id = cur.lastrowid
    conn.commit()
    chain_step(conn, case_id, "acquisition.complete", mhash, clock=clock)
    _set_status(conn, case_id, "acquired")
    return get_acquisition(conn, acq_id)


def get_acquisition(conn: sqlite3.Connection, acquisition_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM forensics_acquisitions WHERE id = ?", (acquisition_id,)
    ).fetchone()
    if row is None:
        raise ForensicsError(f"No acquisition with id {acquisition_id}.")
    acq = dict(row)
    acq["manifest"] = json.loads(acq["manifest_json"])
    return acq


def verify_acquisition(
    conn: sqlite3.Connection, acquisition_id: int, source_dir: str
) -> dict:
    """Re-hash the source tree and compare against the stored manifest.

    Returns ``ok=True`` only when there are zero mismatches, zero missing
    files, zero extra files, and the manifest hash matches. Any
    post-acquisition modification of the fixture tree is reported.
    """
    acq = get_acquisition(conn, acquisition_id)
    stored: dict = acq["manifest"]
    current = build_manifest(source_dir) if os.path.isdir(source_dir) else {}
    mismatches = [
        rel
        for rel in stored
        if rel in current and current[rel]["sha256"] != stored[rel]["sha256"]
    ]
    missing = [rel for rel in stored if rel not in current]
    extra = [rel for rel in current if rel not in stored]
    manifest_ok = manifest_hash(current) == acq["manifest_hash"]
    ok = not mismatches and not missing and not extra and manifest_ok
    return {
        "ok": ok,
        "acquisition_id": acquisition_id,
        "manifest_match": manifest_ok,
        "mismatches": sorted(mismatches),
        "missing": sorted(missing),
        "extra": sorted(extra),
    }


# ---------------------------------------------------------------------------
# Examination: artifact extractors
# ---------------------------------------------------------------------------

def _record_artifact(
    conn: sqlite3.Connection,
    acquisition_id: int,
    kind: str,
    ref_path: str,
    detail: dict,
    sha256: Optional[str] = None,
    clock: Optional[Callable[[], str]] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO forensics_artifacts "
        "(acquisition_id, kind, ref_path, detail_json, sha256, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (acquisition_id, kind, ref_path, _canonical(detail), sha256, now_iso(clock)),
    )
    conn.commit()
    return cur.lastrowid


def extract_file_listing(
    conn: sqlite3.Connection,
    acquisition_id: int,
    meta: dict,
    clock: Optional[Callable[[], str]] = None,
) -> list[dict]:
    """File listing with MAC times.

    ``meta`` is the synthetic filesystem-metadata layer (the analogue of
    inode/MFT records): ``{rel_path: {"mtime":..., "atime":..., "ctime":...,
    "owner":..., "mode":...}}``. It is *evidence*, not answers — ground
    truth is never read here.
    """
    acq = get_acquisition(conn, acquisition_id)
    manifest: dict = acq["manifest"]
    artifacts = []
    for rel in sorted(manifest):
        entry = meta.get(rel, {})
        detail = {
            "size": manifest[rel]["size"],
            "sha256": manifest[rel]["sha256"],
            "mtime": entry.get("mtime"),
            "atime": entry.get("atime"),
            "ctime": entry.get("ctime"),
            "owner": entry.get("owner"),
            "mode": entry.get("mode"),
        }
        aid = _record_artifact(conn, acquisition_id, "file", rel, detail,
                              manifest[rel]["sha256"], clock=clock)
        artifacts.append({"id": aid, "ref_path": rel, **detail})
    chain_step(conn, acq["case_id"], "examination.file_listing",
               f"{len(artifacts)} files", clock=clock)
    case = get_case(conn, acq["case_id"])
    if case["status"] == "acquired":
        _set_status(conn, acq["case_id"], "examined")
    return artifacts


def parse_log_line(line: str) -> Optional[dict]:
    """Parse one synthetic log line into an event dict.

    Format: ``<ISO-8601-ts> key=value key=value ...`` with a required
    ``event=`` key. Returns ``None`` for blank or unparsable lines.
    """
    line = line.strip()
    if not line:
        return None
    m = LOG_LINE_RE.match(line)
    if not m:
        return None
    try:
        ts = _parse_ts(m.group("ts"))
    except (ValueError, OverflowError):
        return None
    attrs = dict(KV_RE.findall(m.group("body")))
    event_type = attrs.get("event")
    if not event_type:
        return None
    summary_bits = [f"{k}={v}" for k, v in attrs.items() if k != "event"]
    return {
        "ts": ts.isoformat(),
        "source": attrs.get("app", "log"),
        "event_type": event_type,
        "summary": f"{event_type} {' '.join(summary_bits)}".strip(),
        "attrs": attrs,
    }


def parse_log(text: str) -> list[dict]:
    """Parse a whole synthetic log; skips blank/unparsable lines."""
    events = []
    for line in text.splitlines():
        parsed = parse_log_line(line)
        if parsed is not None:
            events.append(parsed)
    return events


def extract_log_events(
    conn: sqlite3.Connection,
    acquisition_id: int,
    log_text: str,
    source_name: str = "app.log",
    clock: Optional[Callable[[], str]] = None,
) -> list[dict]:
    """Parse a synthetic log and store each event as an artifact."""
    acq = get_acquisition(conn, acquisition_id)
    events = parse_log(log_text)
    artifacts = []
    for i, event in enumerate(events):
        aid = _record_artifact(
            conn, acquisition_id, "log_event",
            f"{source_name}#L{i + 1}", event, clock=clock,
        )
        artifacts.append({"id": aid, **event})
    chain_step(conn, acq["case_id"], "examination.log_parse",
               f"{len(artifacts)} events from {source_name}", clock=clock)
    return artifacts


def carve_deleted(
    conn: sqlite3.Connection,
    acquisition_id: int,
    blob: bytes,
    free_list: list[dict],
    clock: Optional[Callable[[], str]] = None,
) -> list[dict]:
    """Simple file carving on synthetic data.

    Each ``free_list`` entry names a "deleted" region of the synthetic
    unallocated blob: ``{"name", "offset", "size", "expected_sha256",
    "deleted_at"}``. The carver slices the blob and verifies the slice
    against the expected hash — a recovered entry whose hash does not
    match is reported as corrupt, not silently accepted.
    """
    acq = get_acquisition(conn, acquisition_id)
    recovered = []
    for entry in free_list:
        for field in ("name", "offset", "size", "expected_sha256"):
            if field not in entry:
                raise ValidationError(
                    {"free_list": f"Entry missing required field {field!r}."}
                )
        start, end = int(entry["offset"]), int(entry["offset"]) + int(entry["size"])
        if start < 0 or end > len(blob):
            raise ValidationError(
                {"free_list": f"Entry {entry['name']!r} is out of blob bounds."}
            )
        content = blob[start:end]
        digest = _sha256_hex(content)
        match = digest == entry["expected_sha256"]
        detail = {
            "offset": start,
            "size": len(content),
            "deleted_at": entry.get("deleted_at"),
            "expected_sha256": entry["expected_sha256"],
            "recovered_sha256": digest,
            "hash_match": match,
            "preview": content[:64].decode("utf-8", errors="replace"),
        }
        aid = _record_artifact(conn, acquisition_id, "carved",
                              entry["name"], detail, digest, clock=clock)
        recovered.append({"id": aid, "ref_path": entry["name"], **detail})
    chain_step(conn, acq["case_id"], "examination.carving",
               f"{len(recovered)} carved entries", clock=clock)
    return recovered


def list_artifacts(conn: sqlite3.Connection, acquisition_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM forensics_artifacts WHERE acquisition_id = ? ORDER BY id",
        (acquisition_id,),
    ).fetchall()
    out = []
    for row in rows:
        art = dict(row)
        art["detail"] = json.loads(art["detail_json"])
        out.append(art)
    return out


# ---------------------------------------------------------------------------
# Analysis: merged timeline + hypotheses
# ---------------------------------------------------------------------------

def build_timeline(events: list[dict]) -> list[dict]:
    """Merge artifact events into one chronological timeline.

    Each event needs ``ts`` (ISO-8601), ``source``, ``event_type``,
    ``summary``; an optional ``ref`` links back to the artifact.
    """
    timeline = []
    for event in events:
        for field in ("ts", "source", "event_type", "summary"):
            if field not in event:
                raise ValidationError(
                    {"timeline": f"Event missing required field {field!r}."}
                )
        timeline.append({
            "ts": _parse_ts(event["ts"]).isoformat(),
            "source": event["source"],
            "event_type": event["event_type"],
            "summary": event["summary"],
            "ref": event.get("ref", ""),
        })
    timeline.sort(key=lambda e: (e["ts"], e["source"], e["event_type"]))
    return timeline


def record_timeline(
    conn: sqlite3.Connection,
    case_id: int,
    events: list[dict],
    clock: Optional[Callable[[], str]] = None,
) -> list[dict]:
    timeline = build_timeline(events)
    for event in timeline:
        conn.execute(
            "INSERT INTO forensics_timeline_events "
            "(case_id, ts, source, event_type, summary, ref) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, event["ts"], event["source"], event["event_type"],
             event["summary"], event["ref"]),
        )
    conn.commit()
    chain_step(conn, case_id, "analysis.timeline", f"{len(timeline)} events",
               clock=clock)
    _set_status(conn, case_id, "analyzed")
    return timeline


def get_timeline(conn: sqlite3.Connection, case_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, source, event_type, summary, ref "
        "FROM forensics_timeline_events WHERE case_id = ? ORDER BY ts, source",
        (case_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def score_timeline(
    built: list[dict],
    ground_truth: list[dict],
    tolerance_seconds: int = TIMELINE_TOLERANCE_SECONDS,
) -> dict:
    """Score a built timeline against ground truth.

    Each ground-truth event (``ts`` + ``event_type``) must match an
    *unused* built event of the same type within ``tolerance_seconds``.
    Returns matched/total, the score, and per-event detail.
    """
    remaining = list(built)
    details = []
    matched = 0
    for gt in ground_truth:
        gt_ts = _parse_ts(gt["ts"])
        best = None
        best_gap = None
        for cand in remaining:
            if cand["event_type"] != gt["event_type"]:
                continue
            gap = abs((_parse_ts(cand["ts"]) - gt_ts).total_seconds())
            if gap <= tolerance_seconds and (best_gap is None or gap < best_gap):
                best, best_gap = cand, gap
        if best is not None:
            remaining.remove(best)
            matched += 1
            details.append({"gt": gt, "match": best, "gap_seconds": best_gap,
                            "matched": True})
        else:
            details.append({"gt": gt, "match": None, "gap_seconds": None,
                            "matched": False})
    total = len(ground_truth)
    return {
        "matched": matched,
        "total": total,
        "score": (matched / total) if total else 1.0,
        "tolerance_seconds": tolerance_seconds,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Analysis: hypotheses with confirmation-bias control
# ---------------------------------------------------------------------------

HYPOTHESIS_STATUSES = ("open", "supported", "refuted", "unresolved")


def add_hypothesis(
    conn: sqlite3.Connection,
    case_id: int,
    *,
    statement: str,
    supporting: list,
    contradicting: list,
    status: str = "open",
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Record a hypothesis. Requires BOTH supporting and contradicting evidence.

    This is the confirmation-bias control: a hypothesis that names only
    evidence in its favor is rejected. ``contradicting`` must be a
    non-empty list of evidence references (artifact refs, timeline refs,
    or the explicit string ``"none-found-after-review"`` when the
    examiner documents that a contradicting search was performed).
    """
    get_case(conn, case_id)  # raises if the case does not exist
    errors: dict[str, str] = {}
    if not (isinstance(statement, str) and statement.strip()):
        errors["statement"] = "Hypothesis statement is required."
    if not (isinstance(supporting, list) and supporting
            and all(isinstance(s, str) and s.strip() for s in supporting)):
        errors["supporting"] = (
            "At least one supporting evidence reference is required."
        )
    if not (isinstance(contradicting, list) and contradicting
            and all(isinstance(s, str) and s.strip() for s in contradicting)):
        errors["contradicting"] = (
            "Confirmation-bias control: at least one contradicting evidence "
            "reference is required (use 'none-found-after-review' only when a "
            "contradicting search was actually performed and documented)."
        )
    if status not in HYPOTHESIS_STATUSES:
        errors["status"] = f"status must be one of {HYPOTHESIS_STATUSES}."
    if errors:
        raise ValidationError(errors)
    cur = conn.execute(
        "INSERT INTO forensics_hypotheses "
        "(case_id, statement, supporting_json, contradicting_json, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            case_id,
            statement.strip(),
            json.dumps([s.strip() for s in supporting]),
            json.dumps([s.strip() for s in contradicting]),
            status,
            now_iso(clock),
        ),
    )
    conn.commit()
    chain_step(conn, case_id, "analysis.hypothesis", f"hypothesis {cur.lastrowid}",
               clock=clock)
    return get_hypothesis(conn, cur.lastrowid)


def get_hypothesis(conn: sqlite3.Connection, hypothesis_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM forensics_hypotheses WHERE id = ?", (hypothesis_id,)
    ).fetchone()
    if row is None:
        raise ForensicsError(f"No hypothesis with id {hypothesis_id}.")
    hyp = dict(row)
    hyp["supporting"] = json.loads(hyp["supporting_json"])
    hyp["contradicting"] = json.loads(hyp["contradicting_json"])
    return hyp


def list_hypotheses(conn: sqlite3.Connection, case_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM forensics_hypotheses WHERE case_id = ? ORDER BY id",
        (case_id,),
    ).fetchall()
    out = []
    for row in rows:
        hyp = dict(row)
        hyp["supporting"] = json.loads(hyp["supporting_json"])
        hyp["contradicting"] = json.loads(hyp["contradicting_json"])
        out.append(hyp)
    return out


def set_hypothesis_status(
    conn: sqlite3.Connection, hypothesis_id: int, status: str,
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    if status not in HYPOTHESIS_STATUSES:
        raise ValidationError({"status": f"status must be one of {HYPOTHESIS_STATUSES}."})
    hyp = get_hypothesis(conn, hypothesis_id)
    conn.execute(
        "UPDATE forensics_hypotheses SET status = ? WHERE id = ?",
        (status, hypothesis_id),
    )
    conn.commit()
    chain_step(conn, hyp["case_id"], "analysis.hypothesis_status",
               f"hypothesis {hypothesis_id} -> {status}", clock=clock)
    return get_hypothesis(conn, hypothesis_id)


# ---------------------------------------------------------------------------
# Reporting: facts vs inference, confidence levels enforced
# ---------------------------------------------------------------------------

def audit_findings(findings: list) -> list[dict]:
    """Audit a findings list for facts/inference separation.

    Returns issues: ``{"severity": "error"|"warning", "index": i, "message"}``.
    Errors: inference without a valid confidence level; fact without
    evidence; unknown kind; missing text. Warnings: fact carrying a
    confidence level (facts should not need one).
    """
    issues = []
    for i, finding in enumerate(findings):
        if not isinstance(finding, dict):
            issues.append({"severity": "error", "index": i,
                           "message": "Finding must be an object."})
            continue
        kind = finding.get("kind")
        text = finding.get("text")
        evidence = finding.get("evidence")
        confidence = finding.get("confidence")
        if kind not in ("fact", "inference"):
            issues.append({"severity": "error", "index": i,
                           "message": "kind must be 'fact' or 'inference'."})
            continue
        if not (isinstance(text, str) and text.strip()):
            issues.append({"severity": "error", "index": i,
                           "message": "Finding text is required."})
        if not (isinstance(evidence, list) and evidence
                and all(isinstance(e, str) and e.strip() for e in evidence)):
            issues.append({"severity": "error", "index": i,
                           "message": f"{kind} must cite at least one evidence reference."})
        if kind == "inference":
            if confidence not in CONFIDENCE_LEVELS:
                issues.append({"severity": "error", "index": i,
                               "message": "Inference requires a confidence level: "
                                          + "/".join(CONFIDENCE_LEVELS) + "."})
        elif confidence is not None:
            issues.append({"severity": "warning", "index": i,
                           "message": "Facts should not carry a confidence level."})
    return issues


def render_report(
    case: dict,
    acquisition: dict,
    findings: list,
    hypotheses: list,
    chain_verdict: dict,
) -> str:
    """Render the findings report as Markdown with facts/inference separated."""
    facts = [f for f in findings if f["kind"] == "fact"]
    inferences = [f for f in findings if f["kind"] == "inference"]
    lines = [
        f"# Forensic Findings Report — {case['case_ref']}",
        "",
        "> SYNTHETIC CASE — method demonstration only. No real device, person,",
        "> or system is represented. All artifacts are generated fixtures.",
        "",
        f"**Case:** {case['title']}",
        f"**Authorization (synthetic record):** {case['authorizer_name']} "
        f"({case['authorization_ref']})",
        f"**Acquisition:** {acquisition['file_count']} files, "
        f"{acquisition['total_bytes']} bytes, manifest "
        f"`{acquisition['manifest_hash'][:16]}…`",
        f"**Chain of custody:** {'VERIFIED' if chain_verdict['ok'] else 'BROKEN'} "
        f"({chain_verdict.get('entries', 0)} chained handoffs)",
        "",
        "## Facts (observed, evidence-cited)",
        "",
    ]
    for i, f in enumerate(facts, 1):
        lines.append(f"{i}. {f['text']}")
        lines.append(f"   Evidence: {', '.join(f['evidence'])}")
    lines += ["", "## Inferences (interpretation, confidence-stated)", ""]
    for i, f in enumerate(inferences, 1):
        lines.append(f"{i}. {f['text']} **[confidence: {f['confidence']}]**")
        lines.append(f"   Evidence: {', '.join(f['evidence'])}")
    if hypotheses:
        lines += ["", "## Hypotheses considered", ""]
        for h in hypotheses:
            lines.append(f"- H{h['id']} [{h['status']}]: {h['statement']}")
            lines.append(f"  Supporting: {', '.join(h['supporting'])}")
            lines.append(f"  Contradicting: {', '.join(h['contradicting'])}")
    lines += [
        "",
        "## Limitations",
        "",
        "- Synthetic fixtures only: findings demonstrate method, not casework.",
        "- 'Unresolved' is a valid finding; absence of contradicting evidence",
        "  must be documented, never assumed.",
        "",
    ]
    return "\n".join(lines)


def draft_report(
    conn: sqlite3.Connection,
    case_id: int,
    findings: list,
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Validate, audit, and store the findings report.

    Any audit *error* (e.g. inference without a confidence level) rejects
    the report outright. Warnings are stored with the report.
    """
    case = get_case(conn, case_id)
    if case["status"] != "analyzed":
        raise ForensicsError(
            f"Case {case['case_ref']} is at stage {case['status']!r}; "
            "reporting requires stage 'analyzed'."
        )
    if not isinstance(findings, list) or not findings:
        raise ValidationError({"findings": "At least one finding is required."})
    audit = audit_findings(findings)
    errors = [i for i in audit if i["severity"] == "error"]
    if errors:
        raise ValidationError(
            {"findings": "; ".join(i["message"] for i in errors)}
        )
    acq = conn.execute(
        "SELECT * FROM forensics_acquisitions WHERE case_id = ? ORDER BY id DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    if acq is None:
        raise ForensicsError("No acquisition recorded for this case.")
    acquisition = dict(acq)
    hypotheses = list_hypotheses(conn, case_id)
    chain_verdict = verify_chain(conn, case_id)
    text = render_report(case, acquisition, findings, hypotheses, chain_verdict)
    cur = conn.execute(
        "INSERT INTO forensics_reports "
        "(case_id, findings_json, audit_json, report_text, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (case_id, _canonical(findings), _canonical(audit), text, now_iso(clock)),
    )
    conn.commit()
    chain_step(conn, case_id, "reporting.drafted", f"report {cur.lastrowid}",
               clock=clock)
    _set_status(conn, case_id, "reported")
    return {"report_id": cur.lastrowid, "audit": audit, "text": text}


def get_report(conn: sqlite3.Connection, report_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM forensics_reports WHERE id = ?", (report_id,)
    ).fetchone()
    if row is None:
        raise ForensicsError(f"No report with id {report_id}.")
    report = dict(row)
    report["findings"] = json.loads(report["findings_json"])
    report["audit"] = json.loads(report["audit_json"])
    return report

# ---------------------------------------------------------------------------
# Synthetic case generator — the "disk image" is a directory tree + manifest
# ---------------------------------------------------------------------------

_SYNTHETIC_SCENARIO = (
    "Synthetic workstation {host}: user {user} downloads an installer, "
    "runs it, then deletes a notes file. All people, hosts, files, and "
    "timestamps are invented for method demonstration."
)


def generate_synthetic_case(
    target_dir: str,
    *,
    base_date: str = "2026-10-20",
) -> dict:
    """Generate a synthetic forensic fixture: tree + metadata + ground truth.

    Layout under ``target_dir``::

        tree/                      <- the "disk image" (acquired read-only)
          home/alvarez/docs/report_final.docx
          home/alvarez/downloads/installer_update.exe
          var/log/app.log
        _meta.json                 <- synthetic filesystem metadata (MAC times)
        _unallocated.bin           <- synthetic unallocated space (text)
        _freelist.json             <- planted "deleted" entries
        _ground_truth.json         <- answers (tests only; the module never reads this)

    Every file is UTF-8 text. No real device, person, or system is
    represented. Returns the paths of each layer.
    """
    tree = os.path.join(target_dir, "tree")
    os.makedirs(tree, exist_ok=True)
    d = base_date
    scenario = _SYNTHETIC_SCENARIO.format(host=SYNTHETIC_HOST, user=SYNTHETIC_USER)

    files = {
        "home/alvarez/docs/report_final.docx":
            "SYNTHETIC DOCUMENT — quarterly report draft (fixture).\n"
            "All content invented for forensic-method demonstration.\n",
        "home/alvarez/downloads/installer_update.exe":
            "SYNTHETIC EXECUTABLE PLACEHOLDER (text fixture, not a binary).\n"
            "Represents a downloaded installer in the training scenario.\n",
        "var/log/app.log": "\n".join([
            f"{d}T09:12:00Z app=demo-agent event=login user={SYNTHETIC_USER} result=ok",
            f"{d}T14:02:11Z app=demo-agent event=download "
            "path=/home/alvarez/downloads/installer_update.exe result=ok bytes=48210",
            f"{d}T14:03:47Z app=demo-agent event=execute "
            "path=/home/alvarez/downloads/installer_update.exe result=ok pid=4217",
            f"{d}T16:20:05Z app=demo-agent event=file_delete "
            "path=/home/alvarez/docs/secret_notes.txt result=ok",
            f"{d}T18:01:00Z app=demo-agent event=logout user={SYNTHETIC_USER} result=ok",
            "",
        ]),
    }
    for rel, content in files.items():
        full = os.path.join(tree, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)

    meta = {
        "home/alvarez/docs/report_final.docx": {
            "mtime": f"{d}T17:45:30+00:00",
            "atime": f"{d}T17:50:00+00:00",
            "ctime": f"{d}T09:12:00+00:00",
            "owner": SYNTHETIC_USER,
            "mode": "0644",
        },
        "home/alvarez/downloads/installer_update.exe": {
            "mtime": f"{d}T14:02:11+00:00",
            "atime": f"{d}T14:03:47+00:00",
            "ctime": f"{d}T14:02:11+00:00",
            "owner": SYNTHETIC_USER,
            "mode": "0755",
        },
        "var/log/app.log": {
            "mtime": f"{d}T18:01:00+00:00",
            "atime": f"{d}T18:01:00+00:00",
            "ctime": f"{d}T09:11:58+00:00",
            "owner": "root",
            "mode": "0644",
        },
    }

    deleted_content = (
        "SYNTHETIC DELETED FILE — secret_notes.txt (fixture).\n"
        "Planted in unallocated space so the carver can recover it.\n"
    ).encode("utf-8")
    pad_before = b"." * 128
    pad_after = b"." * 64
    blob = pad_before + deleted_content + pad_after
    free_list = [{
        "name": "home/alvarez/docs/secret_notes.txt",
        "offset": len(pad_before),
        "size": len(deleted_content),
        "expected_sha256": _sha256_hex(deleted_content),
        "deleted_at": f"{d}T16:20:05+00:00",
    }]

    ground_truth = {
        "scenario": scenario,
        "planted_files": sorted(files),
        "deleted_files": [e["name"] for e in free_list],
        "events": [
            {"ts": f"{d}T09:12:00+00:00", "event_type": "file_created",
             "ref": "home/alvarez/docs/report_final.docx"},
            {"ts": f"{d}T14:02:11+00:00", "event_type": "download",
             "ref": "var/log/app.log#L2"},
            {"ts": f"{d}T14:03:47+00:00", "event_type": "execute",
             "ref": "var/log/app.log#L3"},
            {"ts": f"{d}T16:20:05+00:00", "event_type": "file_deleted",
             "ref": "home/alvarez/docs/secret_notes.txt"},
            {"ts": f"{d}T17:45:30+00:00", "event_type": "file_modified",
             "ref": "home/alvarez/docs/report_final.docx"},
        ],
    }

    meta_path = os.path.join(target_dir, "_meta.json")
    blob_path = os.path.join(target_dir, "_unallocated.bin")
    freelist_path = os.path.join(target_dir, "_freelist.json")
    truth_path = os.path.join(target_dir, "_ground_truth.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
    with open(blob_path, "wb") as fh:
        fh.write(blob)
    with open(freelist_path, "w", encoding="utf-8") as fh:
        json.dump(free_list, fh, indent=2)
    with open(truth_path, "w", encoding="utf-8") as fh:
        json.dump(ground_truth, fh, indent=2)

    return {
        "target_dir": target_dir,
        "tree": tree,
        "meta_path": meta_path,
        "blob_path": blob_path,
        "freelist_path": freelist_path,
        "ground_truth_path": truth_path,
        "scenario": scenario,
    }


def events_from_fixture(case_dir: str) -> list[dict]:
    """Build examination events from a generated fixture's evidence layers.

    Reads ONLY the evidence layers (tree, ``_meta.json``, logs,
    ``_freelist.json``) — never ``_ground_truth.json``. Emits one event
    per file creation/modification (MAC times), per parsed log line, and
    per planted deleted entry.
    """
    with open(os.path.join(case_dir, "_meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    with open(os.path.join(case_dir, "_freelist.json"), encoding="utf-8") as fh:
        free_list = json.load(fh)
    events: list[dict] = []
    for rel in sorted(meta):
        entry = meta[rel]
        events.append({
            "ts": entry["ctime"],
            "source": "filesystem",
            "event_type": "file_created",
            "summary": f"created {rel}",
            "ref": rel,
        })
        events.append({
            "ts": entry["mtime"],
            "source": "filesystem",
            "event_type": "file_modified",
            "summary": f"modified {rel}",
            "ref": rel,
        })
    log_path = os.path.join(case_dir, "tree", "var", "log", "app.log")
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            log_text = fh.read()
        for i, event in enumerate(parse_log(log_text), 1):
            events.append({
                "ts": event["ts"],
                "source": event["source"],
                "event_type": event["event_type"],
                "summary": event["summary"],
                "ref": f"var/log/app.log#L{i}",
            })
    for entry in free_list:
        events.append({
            "ts": entry["deleted_at"],
            "source": "carving",
            "event_type": "file_deleted",
            "summary": f"deleted {entry['name']} (recovered from unallocated space)",
            "ref": entry["name"],
        })
    return events
