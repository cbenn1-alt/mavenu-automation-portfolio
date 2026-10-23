"""Q10 — Webhook Integration Hub: ingest, HMAC verification, envelope normalization.

Synthetic demo service. All events are invented; stub endpoints are
in-process callables (never real HTTP, never real SaaS).

Security posture (honest):
  * HMAC-SHA256 signature verification is REAL and TESTED (``hmac``
    + ``hmac.compare_digest``). In strict mode (default) unsigned or
    invalid events are rejected and never routed.
  * The bundled verifier uses DOCUMENTED TEST-ONLY secrets
    (``TEST_WEBHOOK_SECRETS``). A real deployment MUST supply per-source
    secrets via the ``MAVENU_WEBHOOK_SECRETS`` environment variable (JSON
    object) or a secret manager — never from code. SECURITY.md documents
    this requirement.
  * Full payloads are NEVER written to stdout logs or API responses.
    ``redacted_summary()`` exposes key names + value types only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from .db import utcnow_iso

ENVELOPE_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Demo verifier secrets.
#
# TEST-ONLY. These exist so the demo and the test suite can sign webhook
# bodies without any real credential. They must NEVER be treated as real
# secrets: a real deployment ignores these and reads MAVENU_WEBHOOK_SECRETS
# (JSON: {"source-name": "secret", ...}) from the environment instead.
# ---------------------------------------------------------------------------
TEST_WEBHOOK_SECRETS = {
    "demo-form": "test-secret-demo-form-001",
    "demo-calendar": "test-secret-demo-calendar-002",
    "demo-sheet": "test-secret-demo-sheet-003",
}

SIGNATURE_HEADER_PREFIX = "sha256="

TERMINAL_STATES = frozenset({"delivered", "dead_lettered", "rejected"})


class EnvelopeError(ValueError):
    """Raised when a received body cannot be normalized to a canonical envelope."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_secrets() -> dict[str, str]:
    """Per-source HMAC secrets: test-only defaults, overridden by env."""
    secrets: dict[str, str] = dict(TEST_WEBHOOK_SECRETS)
    raw = os.environ.get("MAVENU_WEBHOOK_SECRETS")
    if raw:
        try:
            extra = json.loads(raw)
        except ValueError:
            extra = None
        if isinstance(extra, dict):
            for k, v in extra.items():
                secrets[str(k)] = str(v)
    return secrets


def strict_mode() -> bool:
    """Strict mode rejects unsigned/invalid events. Default ON."""
    return os.environ.get("MAVENU_WEBHOOK_STRICT", "1") != "0"


# ---------------------------------------------------------------------------
# HMAC signature verification (real, tested)
# ---------------------------------------------------------------------------
def sign(secret: str, body: bytes) -> str:
    """Compute the ``sha256=<hex>`` signature a sender would attach."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return SIGNATURE_HEADER_PREFIX + digest


def verify_signature(secret: str, body: bytes, signature: Optional[str]) -> bool:
    """True iff ``signature`` is a valid HMAC-SHA256 of ``body``.

    Constant-time comparison via ``hmac.compare_digest`` (timing side-channel
    resistant, per S05 guidance). Empty/malformed signatures are False —
    never an exception.
    """
    if not signature or not isinstance(signature, str):
        return False
    if not signature.startswith(SIGNATURE_HEADER_PREFIX):
        return False
    expected = sign(secret, body)
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Canonical event envelope
# ---------------------------------------------------------------------------
def normalize_envelope(data: Any, source_hint: Optional[str] = None) -> dict[str, Any]:
    """Normalize a parsed JSON body to the canonical event envelope.

    Envelope:
        {"envelope_version": "1.0", "event_id": ..., "source": ...,
         "event_type": ..., "occurred_at": ..., "payload": {...}}

    Raises EnvelopeError on anything malformed — callers must route the
    failure to the dead-letter store, never let it halt a processing loop.
    """
    if not isinstance(data, dict):
        raise EnvelopeError("webhook body must be a JSON object")
    source = data.get("source") or source_hint
    if not source or not isinstance(source, str):
        raise EnvelopeError("missing or invalid 'source' (string required)")
    event_type = data.get("event_type")
    if not event_type or not isinstance(event_type, str):
        raise EnvelopeError("missing or invalid 'event_type' (string required)")
    payload = data.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise EnvelopeError("'payload' must be a JSON object")
    event_id = data.get("event_id") or f"evt-{uuid.uuid4().hex[:16]}"
    if not isinstance(event_id, str) or not event_id:
        raise EnvelopeError("'event_id' must be a non-empty string")
    occurred_at = data.get("occurred_at") or utcnow_iso()
    if not isinstance(occurred_at, str):
        raise EnvelopeError("'occurred_at' must be a string")
    return {
        "envelope_version": ENVELOPE_VERSION,
        "event_id": event_id,
        "source": source,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload": payload,
    }


def redacted_summary(payload: Any) -> dict[str, Any]:
    """PII-safe summary of a payload: key names + value types, never values.

    This is the ONLY payload-derived content that may reach stdout logs,
    lineage detail, dead-letter detail, or API responses.
    """
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__, "keys": []}
    return {
        "keys": sorted(str(k) for k in payload.keys()),
        "types": {str(k): type(v).__name__ for k, v in payload.items()},
    }


# ---------------------------------------------------------------------------
# Append-only event store + lineage
# ---------------------------------------------------------------------------
def _next_public_id(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) AS c FROM webhook_events").fetchone()["c"]
    return f"EVT-{n + 1:06d}"


def record_lineage(
    conn: sqlite3.Connection,
    event_id: str,
    to_state: str,
    *,
    from_state: Optional[str] = None,
    actor: str = "hub",
    detail: Optional[dict[str, Any]] = None,
    created: Optional[str] = None,
) -> int:
    """Append one lineage row. The lineage log is never updated or deleted."""
    cur = conn.execute(
        """
        INSERT INTO webhook_lineage (event_id, from_state, to_state, actor, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            from_state,
            to_state,
            actor,
            json.dumps(detail, sort_keys=True) if detail is not None else None,
            created or utcnow_iso(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def event_status(conn: sqlite3.Connection, event_id: str) -> Optional[str]:
    """Current status of an event, derived from its lineage (latest to_state)."""
    row = conn.execute(
        """
        SELECT to_state FROM webhook_lineage
        WHERE event_id = ? ORDER BY id DESC LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    return row["to_state"] if row else None


def get_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM webhook_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown event_id {event_id!r}")
    return dict(row)


def get_lineage(conn: sqlite3.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM webhook_lineage WHERE event_id = ? ORDER BY id",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_events(
    conn: sqlite3.Connection, *, status: Optional[str] = None, limit: int = 100
) -> list[dict[str, Any]]:
    """List events with current status derived from latest lineage row."""
    rows = conn.execute(
        """
        SELECT e.*, (
            SELECT to_state FROM webhook_lineage l
            WHERE l.event_id = e.event_id ORDER BY l.id DESC LIMIT 1
        ) AS status
        FROM webhook_events e
        ORDER BY e.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    events = [dict(r) for r in rows]
    if status:
        events = [e for e in events if e["status"] == status]
    return events


def _store_event(
    conn: sqlite3.Connection,
    envelope: dict[str, Any],
    *,
    signature_ok: bool,
    created: Optional[str] = None,
) -> dict[str, Any]:
    public_id = _next_public_id(conn)
    created = created or utcnow_iso()
    conn.execute(
        """
        INSERT INTO webhook_events
            (public_id, event_id, source, event_type, envelope_json, signature_ok, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            public_id,
            envelope["event_id"],
            envelope["source"],
            envelope["event_type"],
            json.dumps(envelope, sort_keys=True),
            1 if signature_ok else 0,
            created,
        ),
    )
    conn.commit()
    return {
        "public_id": public_id,
        "event_id": envelope["event_id"],
        "source": envelope["source"],
        "event_type": envelope["event_type"],
        "envelope": envelope,
        "signature_ok": signature_ok,
    }


# ---------------------------------------------------------------------------
# Ingest: verify → normalize → store (idempotent on event_id)
# ---------------------------------------------------------------------------
def ingest_event(
    conn: sqlite3.Connection,
    *,
    body: bytes,
    signature: Optional[str],
    secrets: Mapping[str, str],
    strict: bool = True,
    source_hint: Optional[str] = None,
    now: Optional[datetime] = None,
    actor: str = "ingest",
) -> dict[str, Any]:
    """Run the ingest pipeline for one raw webhook body.

    Returns a dict with keys: accepted, duplicate, event_id, public_id,
    envelope (or None), verified, rejection_reason (or None).

    * Strict mode: missing/unknown-source/invalid signature → the event is
      stored with lineage ``rejected`` and ``accepted=False``. It is never
      routed or delivered. (Measurable: 100% of unsigned events rejected.)
    * Non-strict mode: unsigned events are accepted but flagged
      ``signature_ok=0`` / ``verified=False`` in the lineage detail.
    * Malformed envelopes (valid JSON, bad shape) → stored as a poison
      event and immediately dead-lettered (reason ``malformed_envelope``).
    * Duplicate ``event_id`` → idempotent no-op returning the stored event.
    """
    created = (now or utcnow()).isoformat()
    # 1. Parse. (Invalid JSON is a 422 at the HTTP layer; here it is a
    #    malformed envelope → dead letter, so batch loops never crash.)
    try:
        data = json.loads(body.decode("utf-8")) if body.strip() else {}
    except (ValueError, UnicodeDecodeError) as exc:
        return _ingest_poison(
            conn, body, source_hint or "unknown", f"invalid JSON: {exc}",
            created=created, actor=actor,
        )
    # 2. Normalize first (cheap), so we know the source for secret lookup.
    #    Normalization failures are poison — signature cannot be checked
    #    without a source, and a poison row is the honest record.
    try:
        envelope = normalize_envelope(data, source_hint=source_hint)
    except EnvelopeError as exc:
        preview_source = source_hint
        if isinstance(data, dict) and isinstance(data.get("source"), str):
            preview_source = data["source"]
        return _ingest_poison(
            conn, body, preview_source or "unknown", str(exc),
            created=created, actor=actor,
        )
    # 3. Idempotency FIRST: same event_id → return the stored event, route
    #    nothing. This must precede the strict-rejection store below so a
    #    re-sent event_id never violates the UNIQUE(event_id) constraint.
    existing = conn.execute(
        "SELECT public_id, event_id, source, event_type, envelope_json, signature_ok"
        " FROM webhook_events WHERE event_id = ?",
        (envelope["event_id"],),
    ).fetchone()
    if existing is not None:
        return {
            "accepted": True, "duplicate": True,
            "event_id": existing["event_id"], "public_id": existing["public_id"],
            "envelope": json.loads(existing["envelope_json"]),
            "verified": bool(existing["signature_ok"]),
            "rejection_reason": None,
        }
    # 4. Verify signature against the per-source secret.
    secret = secrets.get(envelope["source"])
    verified = verify_signature(secret or "", body, signature) if secret else False
    if strict and not verified:
        reason = (
            "missing_signature" if not signature
            else "unknown_source" if not secret
            else "invalid_signature"
        )
        stored = _store_event(conn, envelope, signature_ok=False, created=created)
        record_lineage(
            conn, envelope["event_id"], "rejected",
            from_state=None, actor=actor, created=created,
            detail={"reason": reason, "verified": False},
        )
        return {
            "accepted": False, "duplicate": False,
            "event_id": envelope["event_id"], "public_id": stored["public_id"],
            "envelope": envelope, "verified": False,
            "rejection_reason": reason,
        }
    # 5. New event: store (append-only) + lineage 'received'.
    stored = _store_event(conn, envelope, signature_ok=verified, created=created)
    record_lineage(
        conn, envelope["event_id"], "received",
        from_state=None, actor=actor, created=created,
        detail={"verified": verified, "payload": redacted_summary(envelope["payload"])},
    )
    return {
        "accepted": True, "duplicate": False,
        "event_id": envelope["event_id"], "public_id": stored["public_id"],
        "envelope": envelope, "verified": verified,
        "rejection_reason": None,
    }


def _ingest_poison(
    conn: sqlite3.Connection,
    body: bytes,
    source: str,
    error: str,
    *,
    created: str,
    actor: str,
) -> dict[str, Any]:
    """Store a malformed body as a poison event and dead-letter it."""
    event_id = f"evt-{uuid.uuid4().hex[:16]}"
    try:
        preview = body[:2048].decode("utf-8", errors="replace")
    except Exception:
        preview = "<undecodable>"
    envelope = {
        "envelope_version": ENVELOPE_VERSION,
        "event_id": event_id,
        "source": source,
        "event_type": "unknown",
        "occurred_at": created,
        "payload": {},
        "_raw_preview": preview[:500],
    }
    stored = _store_event(conn, envelope, signature_ok=False, created=created)
    record_lineage(conn, event_id, "received", from_state=None, actor=actor, created=created,
                   detail={"verified": False, "poison": True})
    from . import delivery as _delivery  # local import: delivery imports router, not webhooks
    _delivery.dead_letter(
        conn, event_id, "malformed_envelope", actor=actor, created=created,
        detail={"error": error[:300], "payload": redacted_summary({})},
    )
    return {
        "accepted": True, "duplicate": False, "poison": True,
        "event_id": event_id, "public_id": stored["public_id"],
        "envelope": envelope, "verified": False,
        "rejection_reason": None,
    }


# ---------------------------------------------------------------------------
# Batch processing: the loop that must never halt
# ---------------------------------------------------------------------------
def process_envelope(
    conn: sqlite3.Connection,
    envelope: dict[str, Any],
    endpoints: Mapping[str, Callable[..., Any]],
    *,
    actor: str = "hub",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Route one accepted envelope with per-event isolation.

    Any exception from routing (a poison rule, a bad transform, a rogue
    action) is caught and converted to a dead-letter — the loop continues.
    Returns the routing plan, or {"error": ...} when dead-lettered.
    """
    from . import router as _router
    event_id = envelope["event_id"]
    try:
        plan = _router.apply_routes(conn, envelope, endpoints, actor=actor, now=now)
        return {"ok": True, "plan": plan}
    except Exception as exc:  # never let one event halt the loop
        from . import delivery as _delivery
        _delivery.dead_letter(
            conn, event_id, "routing_error", actor=actor,
            detail={"error": f"{type(exc).__name__}: {str(exc)[:300]}"},
        )
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def process_batch(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    *,
    secrets: Mapping[str, str],
    strict: bool,
    endpoints: Mapping[str, Callable[..., Any]],
    actor: str = "hub",
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Process a batch of raw webhook items; the loop never halts.

    Each item: {"body": bytes, "signature": str|None, "source_hint": str|None}.
    Every exception is converted to a dead-letter or a rejection — the
    batch always completes and returns per-outcome counts.
    """
    stats = {
        "accepted": 0, "rejected": 0, "duplicate": 0,
        "poison": 0, "routed": 0, "routing_failed": 0,
    }
    for item in items:
        try:
            result = ingest_event(
                conn, body=item.get("body", b""),
                signature=item.get("signature"),
                secrets=secrets, strict=strict,
                source_hint=item.get("source_hint"),
                now=now, actor=actor,
            )
        except Exception:
            # Last-resort guard: ingest itself must not kill the batch.
            # (ingest_event already converts all known failures to rows.)
            stats["routing_failed"] += 1
            continue
        if not result["accepted"]:
            stats["rejected"] += 1
            continue
        stats["accepted"] += 1
        if result.get("duplicate"):
            stats["duplicate"] += 1
            continue
        if result.get("poison"):
            stats["poison"] += 1
            continue
        outcome = process_envelope(conn, result["envelope"], endpoints, actor=actor, now=now)
        if outcome["ok"]:
            stats["routed"] += 1
        else:
            stats["routing_failed"] += 1
    return stats
