"""S04 — Forensic Evidence Management: Chain of Custody System.

=====================================================================
SYNTHETIC CASE ONLY. METHOD DEMONSTRATION — NOT LEGAL AUTHORITY.
=====================================================================

This module implements end-to-end evidence management on a **synthetic
case file**:

    intake -> tagging -> storage log -> access log -> transfer log
    -> disposition

Every record is actor-stamped and timestamped. The custody log is
append-only and hash-chained: each entry's ``entry_hash`` commits to the
previous entry's hash, a strict +1 sequence number, and a non-decreasing
timestamp. Tampering with ANY field of ANY entry — or inserting a
backdated entry — breaks :func:`verify_custody_chain` detectably.

Custody transfers use **dual hash verification**: a transfer completes
only when the sender's hash-out AND the receiver's hash-in are both
recorded and BOTH equal the item's acquisition SHA-256. A mismatch on
either side rejects the transfer and opens a quarantine incident. The
item's storage location changes only on a completed transfer — so,
structurally, there are zero transfers without dual hash verification.

NOT legal advice. This demonstrates a *system* for tracking who had an
item, when, why, and proof it didn't change — not legal authority. Real
admissibility depends on jurisdiction and counsel. Access controls in
this design assume a trusted-admin model (documented in SECURITY.md).

Status vocabulary: Implemented, Tested, Simulated, Demo.
The custody system is Implemented+Tested; the case file, evidence
items, actors, and hashes are Simulated/Synthetic.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .db import utcnow_iso
from .validation import ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64

EVENT_TYPES = (
    "intake",
    "tagging",
    "storage.logged",
    "access.logged",
    "transfer.initiated",
    "transfer.hash_out",
    "transfer.hash_in",
    "transfer.completed",
    "transfer.rejected",
    "disposition.recorded",
    "incident.opened",
    "incident.resolved",
)

TRANSFER_STATUSES = ("initiated", "completed", "rejected")
DISPOSITIONS = ("returned", "destroyed", "archived")
ITEM_STATUSES = ("in_custody", "returned", "destroyed", "archived")
INCIDENT_KINDS = ("hash_mismatch", "suspected_tampering", "lost_form", "other")
INCIDENT_STATUSES = ("open", "resolved")
ACCESS_ACTIONS = (
    "intake",
    "storage_check",
    "transfer_out",
    "transfer_in",
    "inventory",
    "disposition",
    "view",
)

_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{1,63}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# Synthetic actors used ONLY inside generated fixtures / docs / demo.
SYN_ACTORS = ("Case Officer A. Reyes", "Custodian J. Okafor",
              "Courier D. Mensah", "Lab Tech S. Park")

SYNTHETIC_CASE_REF = "CASE-2026-SYN-047"
SYNTHETIC_CASE_TITLE = "Synthetic training case — warehouse incident"
SYNTHETIC_CASE_DESCRIPTION = (
    "SYNTHETIC CASE FILE. All items, people, hashes, locations, dates, "
    "and authorizations are invented for method demonstration. This case "
    "exercises every S04 form and every transfer end to end."
)


class CustodyError(Exception):
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


def _check_sha256(value: str, field: str) -> str:
    if not (isinstance(value, str) and _HEX64_RE.fullmatch(value.strip().lower())):
        raise ValidationError({field: "Must be a 64-character lowercase SHA-256 hex digest."})
    return value.strip().lower()


def _require_text(value: Any, field: str, *, min_len: int = 1, max_len: int = 500) -> str:
    if not (isinstance(value, str) and min_len <= len(value.strip()) <= max_len):
        raise ValidationError(
            {field: f"Must be a non-empty string ({min_len}..{max_len} chars)."}
        )
    return value.strip()


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Hash-chained, append-only custody log
# ---------------------------------------------------------------------------

def _next_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(seq) AS m FROM custody_log").fetchone()
    return (row["m"] or 0) + 1


def _chain_entry(
    conn: sqlite3.Connection,
    item_id: int,
    event_type: str,
    payload: dict,
    actor: str,
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Append one hash-chained entry to the custody log.

    ``entry_hash = SHA-256(prev_hash : seq : item_id : created_at :
    event_type : payload : actor)``. ``seq`` is strict +1 and ``created_at`` must be
    non-decreasing — :func:`verify_custody_chain` enforces both.
    """
    if event_type not in EVENT_TYPES:
        raise ValidationError({"event_type": f"Unknown event type {event_type!r}."})
    actor = _require_text(actor, "actor")
    payload_json = _canonical(payload)
    row = conn.execute(
        "SELECT entry_hash FROM custody_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev = row["entry_hash"] if row else GENESIS_HASH
    seq = _next_seq(conn)
    created = now_iso(clock)
    entry_hash = _sha256_hex(
        f"{prev}:{seq}:{item_id}:{created}:{event_type}:{payload_json}:{actor}".encode("utf-8")
    )
    cur = conn.execute(
        "INSERT INTO custody_log "
        "(item_id, seq, event_type, payload_json, actor, prev_hash, entry_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, seq, event_type, payload_json, actor, prev, entry_hash, created),
    )
    conn.commit()
    return {
        "id": cur.lastrowid,
        "item_id": item_id,
        "seq": seq,
        "event_type": event_type,
        "payload": payload,
        "actor": actor,
        "prev_hash": prev,
        "entry_hash": entry_hash,
        "created_at": created,
    }


def get_item_log(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, item_id, seq, event_type, payload_json, actor, prev_hash, "
        "entry_hash, created_at FROM custody_log WHERE item_id = ? ORDER BY id",
        (item_id,),
    ).fetchall()
    out = []
    for row in rows:
        entry = dict(row)
        entry["payload"] = json.loads(entry.pop("payload_json"))
        out.append(entry)
    return out


def verify_custody_chain(conn: sqlite3.Connection) -> dict:
    """Verify the full append-only custody chain.

    Recomputes every entry hash and checks, in id order:
      1. ``prev_hash`` links to the previous entry's ``entry_hash``
         (genesis for the first entry),
      2. ``entry_hash`` recomputes exactly,
      3. ``seq`` increases by exactly 1 (detects deleted or inserted rows),
      4. ``created_at`` is non-decreasing (detects backdated insertion).

    Returns ``{"ok": True, "entries": n}`` or
    ``{"ok": False, "broken_at": id, "reason": ...}`` naming the first
    broken entry and the failed check.
    """
    prev_hash = GENESIS_HASH
    prev_seq: Optional[int] = None
    prev_ts: Optional[datetime] = None
    entries = 0
    rows = conn.execute(
        "SELECT id, item_id, seq, event_type, payload_json, actor, prev_hash, "
        "entry_hash, created_at FROM custody_log ORDER BY id"
    ).fetchall()
    for row in rows:
        entries += 1
        expected = _sha256_hex(
            f"{row['prev_hash']}:{row['seq']}:{row['item_id']}:{row['created_at']}:"
            f"{row['event_type']}:{row['payload_json']}:{row['actor']}".encode("utf-8")
        )
        if row["prev_hash"] != prev_hash:
            return {"ok": False, "broken_at": row["id"], "reason": "prev_hash_link",
                    "entries": entries}
        if row["entry_hash"] != expected:
            return {"ok": False, "broken_at": row["id"], "reason": "hash_mismatch",
                    "entries": entries}
        if prev_seq is not None and row["seq"] != prev_seq + 1:
            return {"ok": False, "broken_at": row["id"], "reason": "seq_gap",
                    "entries": entries}
        ts = _parse_ts(row["created_at"])
        if prev_ts is not None and ts < prev_ts:
            return {"ok": False, "broken_at": row["id"], "reason": "backdated_timestamp",
                    "entries": entries}
        prev_hash = row["entry_hash"]
        prev_seq = row["seq"]
        prev_ts = ts
    return {"ok": True, "broken_at": None, "reason": None, "entries": entries}


# ---------------------------------------------------------------------------
# Case management (the synthetic case file)
# ---------------------------------------------------------------------------

def open_case(conn: sqlite3.Connection, *, case_ref: str, title: str,
              description: str, clock: Optional[Callable[[], str]] = None) -> dict:
    case_ref = _require_text(case_ref, "case_ref", max_len=64)
    title = _require_text(title, "title", max_len=200)
    description = _require_text(description, "description", max_len=2000)
    created = now_iso(clock)
    try:
        cur = conn.execute(
            "INSERT INTO custody_cases (case_ref, title, description, created_at) "
            "VALUES (?, ?, ?, ?)",
            (case_ref, title, description, created),
        )
    except sqlite3.IntegrityError:
        raise CustodyError(f"Case ref {case_ref!r} already exists.")
    conn.commit()
    return get_case(conn, cur.lastrowid)


def get_case(conn: sqlite3.Connection, case_id: int) -> dict:
    row = conn.execute("SELECT * FROM custody_cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise CustodyError(f"No custody case with id {case_id}.")
    return dict(row)


def get_case_by_ref(conn: sqlite3.Connection, case_ref: str) -> dict:
    row = conn.execute(
        "SELECT * FROM custody_cases WHERE case_ref = ?", (case_ref,)
    ).fetchone()
    if row is None:
        raise CustodyError(f"No custody case with ref {case_ref!r}.")
    return dict(row)


def list_cases(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in
            conn.execute("SELECT * FROM custody_cases ORDER BY id").fetchall()]

# ---------------------------------------------------------------------------
# Evidence register: intake with SHA-256 capture, tagging, storage log
# ---------------------------------------------------------------------------

def intake_item(
    conn: sqlite3.Connection,
    *,
    case_id: int,
    tag: str,
    description: str,
    storage_location: str,
    acquisition_sha256: str,
    acquired_by: str,
    acquisition_ref: str,
    media_type: str = "placeholder",
    collected_at: Optional[str] = None,
    notes: str = "",
    clock: Optional[Callable[[], str]] = None,
) -> dict:
    """Intake an evidence item into the register.

    Captures the acquisition SHA-256 (the anchor for every later hash
    comparison), assigns the evidence tag, and logs the storage location.
    Emits chained entries ``intake`` and ``storage.logged``, and records
    an intake access row (every handling is actor-stamped).
    """
    get_case(conn, case_id)  # raises if the case does not exist
    tag = _require_text(tag, "tag", max_len=64)
    if not _TAG_RE.fullmatch(tag):
        raise ValidationError({"tag": "Tag must be 2-64 chars: letters, digits, '-' or '_'."})
    description = _require_text(description, "description", max_len=2000)
    storage_location = _require_text(storage_location, "storage_location", max_len=200)
    sha = _check_sha256(acquisition_sha256, "acquisition_sha256")
    acquired_by = _require_text(acquired_by, "acquired_by", max_len=200)
    acquisition_ref = _require_text(acquisition_ref, "acquisition_ref", max_len=100)
    media_type = _require_text(media_type, "media_type", max_len=100)
    created = now_iso(clock)
    collected = collected_at if collected_at is not None else created
    try:
        cur = conn.execute(
            "INSERT INTO custody_items "
            "(case_id, tag, description, media_type, acquisition_sha256, "
            " acquired_by, acquisition_ref, storage_location, collected_at, "
            " status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'in_custody', ?)",
            (case_id, tag, description, media_type, sha, acquired_by,
             acquisition_ref, storage_location, collected, created),
        )
    except sqlite3.IntegrityError:
        raise CustodyError(f"Evidence tag {tag!r} is already registered.")
    item_id = cur.lastrowid
    conn.commit()
    _chain_entry(conn, item_id, "intake",
                 {"tag": tag, "acquisition_ref": acquisition_ref,
                  "acquisition_sha256": sha,
                  "note": notes[:200] if notes else ""},
                 acquired_by, clock=clock)
    _chain_entry(conn, item_id, "storage.logged",
                 {"storage_location": storage_location,
                  "status": "in_custody"},
                 acquired_by, clock=clock)
    log_access(conn, item_id=item_id, actor=acquired_by, action="intake",
               purpose=f"Intake of {tag} under {acquisition_ref}", clock=clock)
    return get_item(conn, item_id)


def get_item(conn: sqlite3.Connection, item_id: int) -> dict:
    row = conn.execute("SELECT * FROM custody_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise CustodyError(f"No evidence item with id {item_id}.")
    return dict(row)


def get_item_by_tag(conn: sqlite3.Connection, tag: str) -> dict:
    row = conn.execute(
        "SELECT * FROM custody_items WHERE tag = ?", (tag,)
    ).fetchone()
    if row is None:
        raise CustodyError(f"No evidence item with tag {tag!r}.")
    return dict(row)


def list_items(conn: sqlite3.Connection, case_id: Optional[int] = None) -> list[dict]:
    if case_id is None:
        rows = conn.execute("SELECT * FROM custody_items ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custody_items WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_storage(conn: sqlite3.Connection, *, item_id: int, storage_location: str,
                actor: str, reason: str = "inventory",
                clock: Optional[Callable[[], str]] = None) -> dict:
    """Record a storage-location move or inventory check (no custody change)."""
    item = get_item(conn, item_id)
    if item["status"] != "in_custody":
        raise CustodyError(
            f"Item {item['tag']} has terminal status {item['status']!r}; "
            "storage changes are not allowed after disposition."
        )
    storage_location = _require_text(storage_location, "storage_location", max_len=200)
    reason = _require_text(reason, "reason", max_len=200)
    conn.execute(
        "UPDATE custody_items SET storage_location = ? WHERE id = ?",
        (storage_location, item_id),
    )
    conn.commit()
    log_access(conn, item_id=item_id, actor=actor, action="storage_check",
               purpose=f"Storage logged: {storage_location} ({reason})", clock=clock)
    return _chain_entry(conn, item_id, "storage.logged",
                        {"storage_location": storage_location, "reason": reason},
                        actor, clock=clock)


# ---------------------------------------------------------------------------
# Access log: every view/handling actor-stamped
# ---------------------------------------------------------------------------

def log_access(conn: sqlite3.Connection, *, item_id: int, actor: str,
               action: str, purpose: str,
               clock: Optional[Callable[[], str]] = None) -> dict:
    """Record an access/handling event. Every handling must pass through here."""
    get_item(conn, item_id)  # raises if the item does not exist
    actor = _require_text(actor, "actor", max_len=200)
    if action not in ACCESS_ACTIONS:
        raise ValidationError({"action": f"action must be one of {ACCESS_ACTIONS}."})
    purpose = _require_text(purpose, "purpose", max_len=500)
    created = now_iso(clock)
    cur = conn.execute(
        "INSERT INTO custody_access (item_id, actor, action, purpose, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (item_id, actor, action, purpose, created),
    )
    conn.commit()
    _chain_entry(conn, item_id, "access.logged",
                 {"action": action, "purpose": purpose[:200]}, actor, clock=clock)
    return {
        "id": cur.lastrowid, "item_id": item_id, "actor": actor,
        "action": action, "purpose": purpose, "created_at": created,
    }


def list_access(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM custody_access WHERE item_id = ? ORDER BY id",
        (item_id,)).fetchall()]


def audit_access_coverage(conn: sqlite3.Connection) -> dict:
    """Audit that every handling has a matching access record.

    Rules:
      * every item: an ``intake`` access row by its ``acquired_by``,
      * every completed transfer: a ``transfer_out`` access row by the
        sender and a ``transfer_in`` row by the receiver,
      * every initiated (not yet completed) transfer: a ``transfer_out``
        row by the sender,
      * every disposition: a ``disposition`` access row by the authorizer.
    Returns ``{"gaps": [...], "checked": n}``; ``gaps`` empty means full
    coverage. Transfers/dispositions recorded through this module auto-log
    their access rows, so any gap indicates out-of-band handling.
    """
    gaps: list[dict] = []
    checked = 0
    for item in list_items(conn):
        checked += 1
        rows = conn.execute(
            "SELECT actor, action FROM custody_access WHERE item_id = ?",
            (item["id"],)).fetchall()
        pairs = {(r["actor"], r["action"]) for r in rows}
        if (item["acquired_by"], "intake") not in pairs:
            gaps.append({"item": item["tag"], "missing": "intake access by acquirer"})
    for tr in conn.execute("SELECT * FROM custody_transfers").fetchall():
        checked += 1
        item = get_item(conn, tr["item_id"])
        pairs = {(r["actor"], r["action"]) for r in conn.execute(
            "SELECT actor, action FROM custody_access WHERE item_id = ?",
            (item["id"],)).fetchall()}
        if (tr["sender"], "transfer_out") not in pairs:
            gaps.append({"item": item["tag"], "transfer": tr["id"],
                         "missing": "transfer_out access by sender"})
        if tr["status"] == "completed" and (tr["receiver"], "transfer_in") not in pairs:
            gaps.append({"item": item["tag"], "transfer": tr["id"],
                         "missing": "transfer_in access by receiver"})
    for disp in conn.execute("SELECT * FROM custody_dispositions").fetchall():
        checked += 1
        item = get_item(conn, disp["item_id"])
        pairs = {(r["actor"], r["action"]) for r in conn.execute(
            "SELECT actor, action FROM custody_access WHERE item_id = ?",
            (item["id"],)).fetchall()}
        if (disp["authorized_by"], "disposition") not in pairs:
            gaps.append({"item": item["tag"], "missing": "disposition access by authorizer"})
    return {"gaps": gaps, "checked": checked}


# ---------------------------------------------------------------------------
# Incidents: quarantine procedure
# ---------------------------------------------------------------------------

def open_incident(conn: sqlite3.Connection, *, item_id: Optional[int],
                 kind: str, detail: str, opened_by: str,
                 clock: Optional[Callable[[], str]] = None) -> dict:
    """Open an incident (e.g. hash mismatch -> quarantine).

    Quarantine semantics: while an incident of kind ``hash_mismatch`` or
    ``suspected_tampering`` is OPEN against an item, :func:`initiate_transfer`
    refuses to move it. The item stays quarantined until the incident is
    resolved.
    """
    if item_id is not None:
        get_item(conn, item_id)
    if kind not in INCIDENT_KINDS:
        raise ValidationError({"kind": f"kind must be one of {INCIDENT_KINDS}."})
    detail = _require_text(detail, "detail", max_len=2000)
    opened_by = _require_text(opened_by, "opened_by", max_len=200)
    opened = now_iso(clock)
    cur = conn.execute(
        "INSERT INTO custody_incidents "
        "(item_id, kind, detail, status, opened_by, opened_at) "
        "VALUES (?, ?, ?, 'open', ?, ?)",
        (item_id, kind, detail, opened_by, opened),
    )
    incident_id = cur.lastrowid
    conn.commit()
    if item_id is not None:
        _chain_entry(conn, item_id, "incident.opened",
                     {"incident_id": incident_id, "kind": kind,
                      "detail": detail[:200]},
                     opened_by, clock=clock)
    return get_incident(conn, incident_id)


def get_incident(conn: sqlite3.Connection, incident_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM custody_incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise CustodyError(f"No incident with id {incident_id}.")
    return dict(row)


def list_incidents(conn: sqlite3.Connection,
                   status: Optional[str] = None) -> list[dict]:
    if status is None:
        rows = conn.execute("SELECT * FROM custody_incidents ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custody_incidents WHERE status = ? ORDER BY id",
            (status,)).fetchall()
    return [dict(r) for r in rows]


def resolve_incident(conn: sqlite3.Connection, incident_id: int, *,
                     resolved_by: str, resolution: str,
                     clock: Optional[Callable[[], str]] = None) -> dict:
    inc = get_incident(conn, incident_id)
    if inc["status"] == "resolved":
        raise CustodyError(f"Incident {incident_id} is already resolved.")
    resolved_by = _require_text(resolved_by, "resolved_by", max_len=200)
    resolution = _require_text(resolution, "resolution", max_len=2000)
    resolved = now_iso(clock)
    conn.execute(
        "UPDATE custody_incidents SET status = 'resolved', resolved_at = ? WHERE id = ?",
        (resolved, incident_id),
    )
    conn.commit()
    if inc["item_id"] is not None:
        _chain_entry(conn, inc["item_id"], "incident.resolved",
                     {"incident_id": incident_id, "resolution": resolution[:200]},
                     resolved_by, clock=clock)
    return get_incident(conn, incident_id)


def _quarantined(conn: sqlite3.Connection, item_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM custody_incidents WHERE item_id = ? AND status = 'open' "
        "AND kind IN ('hash_mismatch','suspected_tampering') ORDER BY id DESC LIMIT 1",
        (item_id,)).fetchone()
    return dict(row) if row else None

# ---------------------------------------------------------------------------
# Transfers: dual hash verification (hash-out AND hash-in must match
# the acquisition hash). A mismatch rejects the transfer and opens a
# quarantine incident. The item's storage_location changes ONLY on a
# completed transfer — zero transfers without dual hash verification,
# structurally.
# ---------------------------------------------------------------------------

def _transfer_open_for(conn: sqlite3.Connection, item_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM custody_transfers WHERE item_id = ? AND status = 'initiated' "
        "ORDER BY id DESC LIMIT 1",
        (item_id,)).fetchone()
    return dict(row) if row else None


def get_transfer(conn: sqlite3.Connection, transfer_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM custody_transfers WHERE id = ?", (transfer_id,)).fetchone()
    if row is None:
        raise CustodyError(f"No transfer with id {transfer_id}.")
    return dict(row)


def list_transfers(conn: sqlite3.Connection,
                   item_id: Optional[int] = None) -> list[dict]:
    if item_id is None:
        rows = conn.execute("SELECT * FROM custody_transfers ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custody_transfers WHERE item_id = ? ORDER BY id",
            (item_id,)).fetchall()
    return [dict(r) for r in rows]


def initiate_transfer(conn: sqlite3.Connection, *, item_id: int, sender: str,
                      receiver: str, purpose: str, destination_location: str,
                      clock: Optional[Callable[[], str]] = None) -> dict:
    """Begin a custody handoff. The transfer is NOT complete until BOTH
    :func:`record_hash_out` and :func:`record_hash_in` succeed."""
    item = get_item(conn, item_id)
    if item["status"] != "in_custody":
        raise CustodyError(
            f"Item {item['tag']} has terminal status {item['status']!r}; "
            "transfers are not allowed after disposition."
        )
    quarantine = _quarantined(conn, item_id)
    if quarantine is not None:
        raise CustodyError(
            f"Item {item['tag']} is QUARANTINED by open incident "
            f"#{quarantine['id']} ({quarantine['kind']}). Resolve the incident first."
        )
    if _transfer_open_for(conn, item_id) is not None:
        raise CustodyError(
            f"Item {item['tag']} already has an open transfer; complete or "
            "reject it before starting another."
        )
    sender = _require_text(sender, "sender", max_len=200)
    receiver = _require_text(receiver, "receiver", max_len=200)
    purpose = _require_text(purpose, "purpose", max_len=500)
    destination_location = _require_text(destination_location, "destination_location",
                                         max_len=200)
    initiated = now_iso(clock)
    cur = conn.execute(
        "INSERT INTO custody_transfers "
        "(item_id, sender, receiver, purpose, destination_location, status, initiated_at) "
        "VALUES (?, ?, ?, ?, ?, 'initiated', ?)",
        (item_id, sender, receiver, purpose, destination_location, initiated),
    )
    transfer_id = cur.lastrowid
    conn.commit()
    _chain_entry(conn, item_id, "transfer.initiated",
                 {"transfer_id": transfer_id, "sender": sender,
                  "receiver": receiver, "purpose": purpose[:200],
                  "destination_location": destination_location},
                 sender, clock=clock)
    return get_transfer(conn, transfer_id)


def _reject_transfer(conn: sqlite3.Connection, transfer: dict, *,
                     item: dict, side: str, provided: str,
                     opened_by: str, clock) -> dict:
    """Mark a transfer rejected and open a quarantine incident."""
    detail = (
        f"QUARANTINE — hash mismatch on transfer #{transfer['id']} "
        f"(item {item['tag']}). {side} presented {provided[:16]}... but the "
        f"acquisition hash is {item['acquisition_sha256'][:16]}.... The item is "
        f"quarantined: no further transfers until this incident is resolved."
    )
    incident = open_incident(conn, item_id=item["id"], kind="hash_mismatch",
                             detail=detail, opened_by=opened_by, clock=clock)
    conn.execute(
        "UPDATE custody_transfers SET status = 'rejected', incident_id = ? WHERE id = ?",
        (incident["id"], transfer["id"]),
    )
    conn.commit()
    _chain_entry(conn, item["id"], "transfer.rejected",
                 {"transfer_id": transfer["id"], "side": side,
                  "incident_id": incident["id"]},
                 opened_by, clock=clock)
    rejected = get_transfer(conn, transfer["id"])
    rejected["incident"] = incident
    return rejected


def record_hash_out(conn: sqlite3.Connection, transfer_id: int, *,
                    hash_out: str, clock: Optional[Callable[[], str]] = None) -> dict:
    """Sender records the hash of the item leaving their custody.

    The hash-out MUST equal the item's acquisition SHA-256. A mismatch
    rejects the transfer and opens a quarantine incident.
    """
    transfer = get_transfer(conn, transfer_id)
    if transfer["status"] != "initiated":
        raise CustodyError(
            f"Transfer #{transfer_id} has status {transfer['status']!r}; "
            "hash-out requires status 'initiated'."
        )
    if transfer["hash_out"] is not None:
        raise CustodyError(f"Transfer #{transfer_id} already recorded hash-out.")
    item = get_item(conn, transfer["item_id"])
    provided = _check_sha256(hash_out, "hash_out")
    if provided != item["acquisition_sha256"]:
        return _reject_transfer(conn, transfer, item=item, side="hash_out",
                                provided=provided, opened_by=transfer["sender"],
                                clock=clock)
    conn.execute(
        "UPDATE custody_transfers SET hash_out = ? WHERE id = ?",
        (provided, transfer_id),
    )
    conn.commit()
    log_access(conn, item_id=item["id"], actor=transfer["sender"],
               action="transfer_out",
               purpose=f"Transfer #{transfer_id} to {transfer['receiver']}: {transfer['purpose']}",
               clock=clock)
    _chain_entry(conn, item["id"], "transfer.hash_out",
                 {"transfer_id": transfer_id, "hash_out_match": True},
                 transfer["sender"], clock=clock)
    return get_transfer(conn, transfer_id)


def record_hash_in(conn: sqlite3.Connection, transfer_id: int, *,
                   hash_in: str, clock: Optional[Callable[[], str]] = None) -> dict:
    """Receiver records the hash of the item entering their custody.

    The hash-in MUST equal the item's acquisition SHA-256, and a hash-out
    must already be recorded — both sides are always verified. A mismatch
    rejects the transfer and opens a quarantine incident.
    """
    transfer = get_transfer(conn, transfer_id)
    if transfer["status"] != "initiated":
        raise CustodyError(
            f"Transfer #{transfer_id} has status {transfer['status']!r}; "
            "hash-in requires status 'initiated'."
        )
    if transfer["hash_out"] is None:
        raise CustodyError(
            f"Transfer #{transfer_id}: hash-out must be recorded before hash-in. "
            "Both sides are verified — always."
        )
    if transfer["hash_in"] is not None:
        raise CustodyError(f"Transfer #{transfer_id} already recorded hash-in.")
    item = get_item(conn, transfer["item_id"])
    provided = _check_sha256(hash_in, "hash_in")
    if provided != item["acquisition_sha256"]:
        return _reject_transfer(conn, transfer, item=item, side="hash_in",
                                provided=provided, opened_by=transfer["receiver"],
                                clock=clock)
    completed = now_iso(clock)
    conn.execute(
        "UPDATE custody_transfers SET hash_in = ?, status = 'completed', "
        "completed_at = ? WHERE id = ?",
        (provided, completed, transfer_id),
    )
    conn.execute(
        "UPDATE custody_items SET storage_location = ? WHERE id = ?",
        (transfer["destination_location"], item["id"]),
    )
    conn.commit()
    log_access(conn, item_id=item["id"], actor=transfer["receiver"],
               action="transfer_in",
               purpose=f"Transfer #{transfer_id} from {transfer['sender']}: {transfer['purpose']}",
               clock=clock)
    _chain_entry(conn, item["id"], "transfer.hash_in",
                 {"transfer_id": transfer_id, "hash_in_match": True},
                 transfer["receiver"], clock=clock)
    _chain_entry(conn, item["id"], "transfer.completed",
                 {"transfer_id": transfer_id,
                  "destination_location": transfer["destination_location"],
                  "dual_hash_verified": True},
                 transfer["receiver"], clock=clock)
    return get_transfer(conn, transfer_id)


def assert_dual_hash_verified(conn: sqlite3.Connection) -> dict:
    """Structural check: zero completed transfers without dual hash verification.

    Every completed transfer must have hash_out AND hash_in recorded, and
    both must equal the item's acquisition SHA-256. Returns
    ``{"violations": [...]}``; empty violations means the invariant holds.
    """
    violations = []
    rows = conn.execute(
        "SELECT t.*, i.tag, i.acquisition_sha256 AS anchor FROM custody_transfers t "
        "JOIN custody_items i ON i.id = t.item_id WHERE t.status = 'completed'"
    ).fetchall()
    for tr in rows:
        problems = []
        if tr["hash_out"] is None:
            problems.append("hash_out missing")
        elif tr["hash_out"] != tr["anchor"]:
            problems.append("hash_out != acquisition hash")
        if tr["hash_in"] is None:
            problems.append("hash_in missing")
        elif tr["hash_in"] != tr["anchor"]:
            problems.append("hash_in != acquisition hash")
        if problems:
            violations.append({"transfer_id": tr["id"], "item": tr["tag"],
                               "problems": problems})
    return {"violations": violations, "checked": len(rows)}


# ---------------------------------------------------------------------------
# Dispositions: returned / destroyed / archived (terminal)
# ---------------------------------------------------------------------------

def record_disposition(conn: sqlite3.Connection, *, item_id: int,
                       disposition: str, authorized_by: str,
                       authorization_ref: str, detail: str = "",
                       clock: Optional[Callable[[], str]] = None) -> dict:
    """Record the terminal disposition of an item.

    Requires a named authorizer and an authorization reference (synthetic
    record — procedural, not a legal instrument). After disposition the
    item's status is terminal: transfers, storage moves, and further
    dispositions are rejected.
    """
    item = get_item(conn, item_id)
    if item["status"] != "in_custody":
        raise CustodyError(
            f"Item {item['tag']} already has terminal status "
            f"{item['status']!r}; dispositions are one-way."
        )
    if _transfer_open_for(conn, item_id) is not None:
        raise CustodyError(
            f"Item {item['tag']} has an open transfer; it must complete or "
            "be rejected before disposition."
        )
    quarantine = _quarantined(conn, item_id)
    if quarantine is not None:
        raise CustodyError(
            f"Item {item['tag']} is QUARANTINED by open incident "
            f"#{quarantine['id']}; resolve the incident before disposition."
        )
    if disposition not in DISPOSITIONS:
        raise ValidationError({"disposition": f"disposition must be one of {DISPOSITIONS}."})
    authorized_by = _require_text(authorized_by, "authorized_by", max_len=200)
    authorization_ref = _require_text(authorization_ref, "authorization_ref", max_len=100)
    created = now_iso(clock)
    cur = conn.execute(
        "INSERT INTO custody_dispositions "
        "(item_id, disposition, authorized_by, authorization_ref, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, disposition, authorized_by, authorization_ref,
         detail[:2000] if detail else "", created),
    )
    conn.execute(
        "UPDATE custody_items SET status = ? WHERE id = ?", (disposition, item_id)
    )
    conn.commit()
    log_access(conn, item_id=item_id, actor=authorized_by, action="disposition",
               purpose=f"Disposition of {item['tag']}: {disposition} under {authorization_ref}",
               clock=clock)
    _chain_entry(conn, item_id, "disposition.recorded",
                 {"disposition": disposition, "authorized_by": authorized_by,
                  "authorization_ref": authorization_ref,
                  "detail": detail[:200] if detail else ""},
                 authorized_by, clock=clock)
    row = conn.execute(
        "SELECT * FROM custody_dispositions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_dispositions(conn: sqlite3.Connection,
                      item_id: Optional[int] = None) -> list[dict]:
    if item_id is None:
        rows = conn.execute("SELECT * FROM custody_dispositions ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custody_dispositions WHERE item_id = ? ORDER BY id",
            (item_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Verification: per-item chain check + spot-check procedure
# ---------------------------------------------------------------------------

def verify_item_chain(conn: sqlite3.Connection, item_id: int) -> dict:
    """Verify an item's custody story, entry by entry.

    Recomputes each of the item's entry hashes from its stored
    ``prev_hash`` (content check), then asserts lifecycle completeness:
    an ``intake`` entry exists; every initiated transfer has matching
    out/in/completed-or-rejected entries; a disposition entry exists iff
    the item's status is terminal; the stored storage_location matches the
    destination of the last completed transfer (or the intake location).
    """
    item = get_item(conn, item_id)
    entries = get_item_log(conn, item_id)
    for entry in entries:
        expected = _sha256_hex(
            f"{entry['prev_hash']}:{entry['seq']}:{entry['item_id']}:"
            f"{entry['created_at']}:{entry['event_type']}:"
            f"{_canonical(entry['payload'])}:{entry['actor']}".encode("utf-8")
        )
        if entry["entry_hash"] != expected:
            return {"ok": False, "item": item["tag"],
                    "reason": f"entry {entry['id']} hash recompute failed"}
    stages = [e["event_type"] for e in entries]
    problems: list[str] = []
    if "intake" not in stages:
        problems.append("no intake entry")
    for tr in list_transfers(conn, item_id):
        tids = {tr["id"]}
        got = {e["event_type"] for e in entries
               if e["payload"].get("transfer_id") in tids}
        if tr["status"] == "completed":
            for need in ("transfer.initiated", "transfer.hash_out",
                         "transfer.hash_in", "transfer.completed"):
                if need not in got:
                    problems.append(f"transfer #{tr['id']}: missing {need}")
        elif tr["status"] == "rejected":
            if "transfer.rejected" not in got:
                problems.append(f"transfer #{tr['id']}: missing transfer.rejected")
    if item["status"] != "in_custody" and "disposition.recorded" not in stages:
        problems.append("terminal status without disposition entry")
    completed = [t for t in list_transfers(conn, item_id)
                 if t["status"] == "completed"]
    if completed:
        expect_loc = completed[-1]["destination_location"]
    else:
        expect_loc = None
    if expect_loc is not None and item["storage_location"] != expect_loc:
        problems.append("storage_location does not match last completed transfer")
    return {
        "ok": not problems,
        "item": item["tag"],
        "status": item["status"],
        "entries": len(entries),
        "transfers": len(list_transfers(conn, item_id)),
        "problems": problems,
    }


def spot_check(conn: sqlite3.Connection, item_id: Optional[int] = None,
               seed: int = 0) -> dict:
    """The documented spot-check procedure, runnable against the data.

    Picks an item (by id, or deterministically by ``seed`` when omitted)
    and reports: chain verification verdict for the whole log, per-item
    entry check, lifecycle completeness, access coverage for the item,
    and acquisition-hash anchor status. This is the digital form of the
    paper "spot-check" procedure described in RUNBOOK.md.
    """
    chain = verify_custody_chain(conn)
    items = list_items(conn)
    if not items:
        return {"ok": False, "reason": "no items registered"}
    if item_id is None:
        item = items[seed % len(items)]
    else:
        item = get_item(conn, item_id)
    item_verdict = verify_item_chain(conn, item["id"])
    access = list_access(conn, item["id"])
    coverage = audit_access_coverage(conn)
    item_gaps = [g for g in coverage["gaps"] if g.get("item") == item["tag"]]
    return {
        "ok": chain["ok"] and item_verdict["ok"] and not item_gaps,
        "item": item["tag"],
        "chain": chain,
        "item_chain": item_verdict,
        "access_records": len(access),
        "access_gaps": item_gaps,
        "acquisition_anchor": item["acquisition_sha256"],
    }


def full_trace(conn: sqlite3.Connection, item_id: int) -> dict:
    """Every record for an item, in custody order: the traceability report."""
    item = get_item(conn, item_id)
    case = get_case(conn, item["case_id"])
    return {
        "case": case,
        "item": item,
        "custody_entries": get_item_log(conn, item_id),
        "transfers": list_transfers(conn, item_id),
        "access": list_access(conn, item_id),
        "dispositions": list_dispositions(conn, item_id),
        "incidents": [dict(r) for r in conn.execute(
            "SELECT * FROM custody_incidents WHERE item_id = ? ORDER BY id",
            (item_id,)).fetchall()],
        "chain_verdict": verify_item_chain(conn, item_id),
    }

# ---------------------------------------------------------------------------
# The five paper forms as printable HTML, generated from the same data
# model as the tracker. The digital tracker is the system of record;
# paper is backup (forms carry the tracker's entry hashes so a printed
# page can be reconciled to the database).
# ---------------------------------------------------------------------------

FORM_NAMES = (
    "intake",
    "custody_log",
    "access_log",
    "transfer_receipt",
    "disposition_record",
)

_PRINT_CSS = """
@media print {
  .noprint { display: none; }
  body { font-size: 11pt; }
}
body { font-family: Georgia, serif; max-width: 720px; margin: 2em auto;
       padding: 0 1em; color: #111; }
h1 { font-size: 20pt; border-bottom: 2px solid #111; padding-bottom: .3em; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #666; padding: .4em .6em; text-align: left;
         font-size: 10pt; }
th { background: #eee; }
.hash { font-family: monospace; font-size: 8.5pt; word-break: break-all; }
.sig { margin-top: 2.5em; }
.sig td { height: 3em; }
.banner { background: #fff3cd; border: 1px solid #999; padding: .6em;
          font-size: 9pt; margin-bottom: 1em; }
"""


def _form_doc(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        f"<style>{_PRINT_CSS}</style></head><body>"
        "<div class='banner'><strong>SYNTHETIC FORM — method demonstration.</strong> "
        "Generated from the digital custody tracker (the system of record); "
        "paper is backup. All data is invented. Not a legal instrument.</div>"
        f"<h1>{html.escape(title)}</h1>{body}"
        "<p class='noprint'><a href='javascript:window.print()'>Print this form</a></p>"
        "</body></html>"
    )


def _kv(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in rows
    )
    return f"<table>{body}</table>"


def form_intake(conn: sqlite3.Connection, item_id: int) -> str:
    item = get_item(conn, item_id)
    case = get_case(conn, item["case_id"])
    body = _kv([
        ("Case", f"{html.escape(case['case_ref'])} — {html.escape(case['title'])}"),
        ("Evidence tag", html.escape(item["tag"])),
        ("Description", html.escape(item["description"])),
        ("Media type", html.escape(item["media_type"])),
        ("Collected at", html.escape(item["collected_at"])),
        ("Acquired by", html.escape(item["acquired_by"])),
        ("Acquisition reference (synthetic)",
         html.escape(item["acquisition_ref"])),
        ("Acquisition SHA-256",
         f"<span class='hash'>{html.escape(item['acquisition_sha256'])}</span>"),
        ("Storage location", html.escape(item["storage_location"])),
        ("Status", html.escape(item["status"])),
    ])
    body += ("<table class='sig'><tr><th>Collected by (print / sign / date)</th>"
             "<th>Witness (print / sign / date)</th></tr>"
             "<tr><td></td><td></td></tr></table>")
    return _form_doc(f"Evidence Intake Form — {item['tag']}", body)


def form_custody_log(conn: sqlite3.Connection, item_id: int) -> str:
    item = get_item(conn, item_id)
    entries = get_item_log(conn, item_id)
    rows = ""
    for e in entries:
        rows += (
            f"<tr><td>{e['seq']}</td><td>{html.escape(e['created_at'])}</td>"
            f"<td>{html.escape(e['event_type'])}</td>"
            f"<td>{html.escape(e['actor'])}</td>"
            f"<td class='hash'>{html.escape(e['entry_hash'][:16])}…</td></tr>"
        )
    body = (f"<p>Item <strong>{html.escape(item['tag'])}</strong> — "
            f"{len(entries)} chained entries.</p>"
            "<table><tr><th>Seq</th><th>Timestamp (UTC)</th><th>Event</th>"
            "<th>Actor</th><th>Entry hash</th></tr>" + rows + "</table>"
            "<p>Each entry hash commits to the previous entry's hash "
            "(SHA-256). Altering any row breaks chain verification.</p>")
    return _form_doc(f"Chain-of-Custody Log — {item['tag']}", body)


def form_access_log(conn: sqlite3.Connection, item_id: int) -> str:
    item = get_item(conn, item_id)
    rows = ""
    for a in list_access(conn, item_id):
        rows += (
            f"<tr><td>{html.escape(a['created_at'])}</td>"
            f"<td>{html.escape(a['actor'])}</td>"
            f"<td>{html.escape(a['action'])}</td>"
            f"<td>{html.escape(a['purpose'])}</td></tr>"
        )
    body = (f"<p>Item <strong>{html.escape(item['tag'])}</strong> — "
            "every handling actor-stamped.</p>"
            "<table><tr><th>Timestamp (UTC)</th><th>Actor</th><th>Action</th>"
            "<th>Purpose</th></tr>" + rows + "</table>"
            "<table class='sig'><tr><th>Reviewer (print / sign / date)</th></tr>"
            "<tr><td></td></tr></table>")
    return _form_doc(f"Evidence Access Log — {item['tag']}", body)


def form_transfer_receipt(conn: sqlite3.Connection, transfer_id: int) -> str:
    tr = get_transfer(conn, transfer_id)
    item = get_item(conn, tr["item_id"])
    rows = [
        ("Transfer #", str(tr["id"])),
        ("Item", f"{html.escape(item['tag'])} — {html.escape(item['description'])}"),
        ("From (sender)", html.escape(tr["sender"])),
        ("To (receiver)", html.escape(tr["receiver"])),
        ("Purpose", html.escape(tr["purpose"])),
        ("Destination", html.escape(tr["destination_location"])),
        ("Initiated", html.escape(tr["initiated_at"])),
        ("Acquisition SHA-256 (anchor)",
         f"<span class='hash'>{html.escape(item['acquisition_sha256'])}</span>"),
        ("Hash-out (sender)",
         (f"<span class='hash'>{html.escape(tr['hash_out'])}</span>"
          if tr["hash_out"] else "<em>not recorded</em>")),
        ("Hash-in (receiver)",
         (f"<span class='hash'>{html.escape(tr['hash_in'])}</span>"
          if tr["hash_in"] else "<em>not recorded</em>")),
        ("Status", html.escape(tr["status"])),
    ]
    if tr["status"] == "rejected":
        rows.append(("Quarantine incident", f"#{tr['incident_id']} — item is quarantined "
                                           "until the incident is resolved."))
    body = _kv(rows)
    body += ("<p><strong>Dual hash verification:</strong> this transfer is valid "
             "only when hash-out AND hash-in both equal the acquisition SHA-256. "
             "Any mismatch rejects the transfer and opens a quarantine incident.</p>"
             "<table class='sig'><tr><th>Released by (print / sign / date)</th>"
             "<th>Received by (print / sign / date)</th></tr>"
             "<tr><td></td><td></td></tr></table>")
    return _form_doc(f"Transfer Receipt — #{transfer_id} / {item['tag']}", body)


def form_disposition(conn: sqlite3.Connection, item_id: int) -> str:
    item = get_item(conn, item_id)
    disps = list_dispositions(conn, item_id)
    if not disps:
        raise CustodyError(f"Item {item['tag']} has no disposition recorded.")
    d = disps[-1]
    body = _kv([
        ("Item", f"{html.escape(item['tag'])} — {html.escape(item['description'])}"),
        ("Disposition", html.escape(d["disposition"]).upper()),
        ("Detail", html.escape(d["detail"] or "—")),
        ("Authorized by", html.escape(d["authorized_by"])),
        ("Authorization reference (synthetic)",
         html.escape(d["authorization_ref"])),
        ("Recorded at", html.escape(d["created_at"])),
        ("Acquisition SHA-256 (final integrity anchor)",
         f"<span class='hash'>{html.escape(item['acquisition_sha256'])}</span>"),
    ])
    body += ("<p><strong>Terminal record:</strong> after disposition this item "
             "cannot be transferred or re-dispositioned.</p>"
             "<table class='sig'><tr><th>Authorized by (print / sign / date)</th>"
             "<th>Witness (print / sign / date)</th></tr>"
             "<tr><td></td><td></td></tr></table>")
    return _form_doc(f"Disposition Record — {item['tag']}", body)


def render_form(conn: sqlite3.Connection, form: str, **ids) -> str:
    """Render one of the five forms from the data model."""
    if form not in FORM_NAMES:
        raise ValidationError({"form": f"form must be one of {FORM_NAMES}."})
    if form == "intake":
        return form_intake(conn, ids["item_id"])
    if form == "custody_log":
        return form_custody_log(conn, ids["item_id"])
    if form == "access_log":
        return form_access_log(conn, ids["item_id"])
    if form == "transfer_receipt":
        return form_transfer_receipt(conn, ids["transfer_id"])
    return form_disposition(conn, ids["item_id"])

# ---------------------------------------------------------------------------
# Synthetic case file — exercises every form and every transfer end to end.
# All items, people, hashes, locations, and authorizations are invented.
# ---------------------------------------------------------------------------

def _synthetic_hash(label: str) -> str:
    return _sha256_hex(f"SYNTHETIC-S04|{label}|invented-bytes".encode("utf-8"))


def seed_synthetic_case(conn: sqlite3.Connection,
                        clock: Optional[Callable[[], str]] = None) -> dict:
    """Build the synthetic case CASE-2026-SYN-047 end to end.

    Intake (4 items) -> tagging -> storage log -> access log -> transfers
    (2 clean completions + 1 rejected hash-mismatch drill with quarantine
    incident, then a clean re-transfer) -> dispositions (archived,
    returned, destroyed; one item remains in custody). Every step is
    actor-stamped and chained into the custody log.
    """
    case = open_case(
        conn, case_ref=SYNTHETIC_CASE_REF, title=SYNTHETIC_CASE_TITLE,
        description=SYNTHETIC_CASE_DESCRIPTION, clock=clock)
    cid = case["id"]
    A, C, M, S = SYN_ACTORS  # A. Reyes, J. Okafor, D. Mensah, S. Park

    items: dict[str, dict] = {}
    for tag, desc, locker in (
        ("EV-047-001", "Sealed manila envelope — incident report pages "
         "(synthetic placeholder)", "Locker A-3"),
        ("EV-047-002", "USB drive — synthetic image manifest "
         "(hash of invented bytes)", "Locker A-3"),
        ("EV-047-003", "Printed photograph set, 3 pages "
         "(synthetic placeholder)", "Locker A-4"),
        ("EV-047-004", "Recovered access badge in evidence bag "
         "(synthetic placeholder)", "Locker A-4"),
    ):
        items[tag] = intake_item(
            conn, case_id=cid, tag=tag, description=desc,
            storage_location=locker,
            acquisition_sha256=_synthetic_hash(tag),
            acquired_by=A, acquisition_ref=f"ACQ-SYN-047-{tag[-3:]}",
            media_type="placeholder", clock=clock)

    # Storage log (inventory check on EV-047-001) + access log entries.
    log_storage(conn, item_id=items["EV-047-001"]["id"],
                storage_location="Locker A-3", actor=C,
                reason="inventory verification", clock=clock)
    log_access(conn, item_id=items["EV-047-002"]["id"], actor=C,
               action="inventory",
               purpose="Inventory verification of Locker A-3", clock=clock)
    log_access(conn, item_id=items["EV-047-003"]["id"], actor=S,
               action="view",
               purpose="Photograph set preview for case review", clock=clock)

    # Transfer 1: clean completion, EV-047-002 Locker A-3 -> Analysis Room.
    t1 = initiate_transfer(conn, item_id=items["EV-047-002"]["id"],
                           sender=A, receiver=C,
                           purpose="Secure transport to analysis room",
                           destination_location="Analysis Room Safe-2",
                           clock=clock)
    record_hash_out(conn, t1["id"],
                    hash_out=items["EV-047-002"]["acquisition_sha256"],
                    clock=clock)
    record_hash_in(conn, t1["id"],
                   hash_in=items["EV-047-002"]["acquisition_sha256"],
                   clock=clock)

    # Transfer 2: clean completion, EV-047-003 Locker A-4 -> Lab Intake.
    t2 = initiate_transfer(conn, item_id=items["EV-047-003"]["id"],
                           sender=A, receiver=M,
                           purpose="Courier transport to lab intake",
                           destination_location="Lab Intake Shelf-1",
                           clock=clock)
    record_hash_out(conn, t2["id"],
                    hash_out=items["EV-047-003"]["acquisition_sha256"],
                    clock=clock)
    record_hash_in(conn, t2["id"],
                   hash_in=items["EV-047-003"]["acquisition_sha256"],
                   clock=clock)

    # Hash-mismatch DRILL on EV-047-004: wrong hash-out -> rejected +
    # quarantine incident. A retry while quarantined is refused (asserted
    # in tests); after drill resolution a clean re-transfer completes.
    drill = initiate_transfer(conn, item_id=items["EV-047-004"]["id"],
                              sender=A, receiver=S,
                              purpose="DRILL: transport to exam bench",
                              destination_location="Exam Bench 2",
                              clock=clock)
    wrong_hash = _synthetic_hash("DRILL-WRONG-HASH")
    rejected = record_hash_out(conn, drill["id"], hash_out=wrong_hash,
                               clock=clock)
    incident_id = rejected["incident"]["id"]
    resolve_incident(conn, incident_id, resolved_by=A,
                     resolution="Drill review complete: acquisition hash "
                     "re-verified against intake record; hash-out entry was "
                     "deliberately incorrect (training). Quarantine lifted.",
                     clock=clock)

    t4 = initiate_transfer(conn, item_id=items["EV-047-004"]["id"],
                           sender=A, receiver=S,
                           purpose="Transport to exam bench",
                           destination_location="Exam Bench 2",
                           clock=clock)
    record_hash_out(conn, t4["id"],
                    hash_out=items["EV-047-004"]["acquisition_sha256"],
                    clock=clock)
    record_hash_in(conn, t4["id"],
                   hash_in=items["EV-047-004"]["acquisition_sha256"],
                   clock=clock)

    # Dispositions: archived, returned, destroyed. EV-047-004 stays in custody.
    record_disposition(conn, item_id=items["EV-047-001"]["id"],
                       disposition="archived", authorized_by=A,
                       authorization_ref="AUTH-SYN-047-A",
                       detail="Case file closed to long-term synthetic archive.",
                       clock=clock)
    record_disposition(conn, item_id=items["EV-047-002"]["id"],
                       disposition="returned", authorized_by=A,
                       authorization_ref="AUTH-SYN-047-B",
                       detail="Returned to synthetic custodian of origin.",
                       clock=clock)
    record_disposition(conn, item_id=items["EV-047-003"]["id"],
                       disposition="destroyed", authorized_by=A,
                       authorization_ref="AUTH-SYN-047-C",
                       detail="Synthetic placeholder destroyed per drill "
                       "authorization (no real media).",
                       clock=clock)

    return {
        "case_id": cid,
        "case_ref": case["case_ref"],
        "item_tags": list(items),
        "completed_transfers": [t1["id"], t2["id"], t4["id"]],
        "drill_transfer": drill["id"],
        "drill_incident": incident_id,
        "chain": verify_custody_chain(conn),
        "dual_hash": assert_dual_hash_verified(conn),
        "access_coverage": audit_access_coverage(conn),
    }
