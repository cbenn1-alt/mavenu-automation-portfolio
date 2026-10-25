"""Project Q08 — Review & Reputation Monitor: service layer.

Owns the review lifecycle: ingest (CSV + JSON event shapes), lexicon
tagging behind the ``ReviewTagger`` protocol, severity routing into triage
queues with UTC SLA timers, SLA breach escalation, and template-based
response drafts behind a human-approval gate.

Hard architectural rule: there is NO send/post path. ``generate_draft``
creates a draft; ``approve_draft`` / ``reject_draft`` record a human
decision. The ``review_drafts.status`` CHECK constraint only allows
``draft`` | ``approved`` | ``rejected`` — a "sent" state is unreachable,
which tests assert directly.

Severity routing (documented, deterministic):
  * stars == 1                       -> critical  -> owner_alert, SLA 4h
  * stars == 2                       -> high      -> owner_alert, SLA 12h
  * sentiment negative (conf >= 0.5) -> normal   -> owner_alert, SLA 24h
  * tagger uncertain                 -> normal   -> human_review, SLA 24h
                                        (default-to-alert: ambiguity is never
                                        auto-resolved, it is routed to a human)
  * stars <= 3 and sentiment negative -> high -> owner_alert (worst wins)
  * otherwise (positive, or confident neutral with stars >= 4 or no stars)
                                     -> no queue entry; review is just stored
                                        and tagged.

One queue row per review (worst queue/severity wins by re-routing: if a
re-tag would raise severity, the queue row is updated; downgrades require
a human resolving the queue entry).

Every state change writes a row to ``review_events`` (queryable audit
trail) plus a JSON stdout line via ``log_system_event``.

ALL DATA THIS MODULE PROCESSES IS SYNTHETIC DEMONSTRATION DATA. Review
bodies, author names, and ratings are fabricated fixtures; no real
business identities or platform data exist anywhere in this project.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .events import log_system_event
from .tagger import (
    LexiconTagger,
    ReviewTagger,
    seed_lexicons,
    summary_json,
)
from .validation import ValidationError

REVIEW_BODY_MAX_CHARS = 4000
TITLE_MAX_CHARS = 200

#: SLA hours by severity (UTC; tested against a frozen clock).
SLA_HOURS = {"critical": 4, "high": 12, "normal": 24}

#: Queues.
QUEUE_OWNER_ALERT = "owner_alert"
QUEUE_HUMAN_REVIEW = "human_review"

#: Draft transitions. 'sent' is deliberately absent: no send path exists.
DRAFT_TRANSITIONS = {"draft": ("approved", "rejected")}

#: Response-draft templates. They contain ONLY acknowledgment and a next
#: step — no factual claims about what happened, no dates, no amounts, no
#: numbers at all. Tested: templates must contain no digits, no '$', and
#: none of the forbidden claim words.
DRAFT_TEMPLATES: dict[str, dict[str, str]] = {
    "acknowledge_negative": {
        "professional": (
            "Thank you for taking the time to share your feedback. We take "
            "every review seriously and we would like to understand more "
            "about your experience. A member of our team will reach out to "
            "you directly so we can learn what happened and discuss a path "
            "forward."
        ),
        "warm": (
            "Thank you for letting us know — we genuinely appreciate the "
            "honest feedback, even when it is hard to hear. We want every "
            "customer to feel well looked after. Someone from our team will "
            "contact you personally to hear more about your experience and "
            "talk through next steps together."
        ),
        "brief": (
            "Thank you for your feedback. We take this seriously and a team "
            "member will reach out to you directly to discuss your "
            "experience."
        ),
    },
    "acknowledge_mixed": {
        "professional": (
            "Thank you for your detailed feedback — we appreciate both the "
            "positives you mentioned and the areas where we fell short. We "
            "would like to learn more about the parts of your experience "
            "that did not meet expectations. A member of our team will be in "
            "touch."
        ),
        "warm": (
            "Thank you for the thoughtful review. We are glad parts of the "
            "job went well, and we want to do better on the parts that did "
            "not. Someone from our team will reach out so we can hear more "
            "and make it right where we can."
        ),
        "brief": (
            "Thank you for the detailed review. We appreciate the kind "
            "words and take the concerns seriously — a team member will "
            "reach out."
        ),
    },
}

#: Words that imply a factual promise or claim; templates must not contain
#: them (asserted by tests).
FORBIDDEN_TEMPLATE_WORDS = (
    "refund", "discount", "free", "guarantee", "compensation",
    "credit", "warranty", "tomorrow", "today",
)

_TONES = ("professional", "warm", "brief")


class ReviewError(Exception):
    """Domain error for review-service problems."""


def _now_or(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _mask_author(author: str) -> str:
    """Mask an author name to first name + initial. Synthetic data only."""
    parts = (author or "").strip().split()
    if not parts:
        return ""
    if len(parts) == 1:
        name = parts[0]
        return name[0] + "\u2022" * max(len(name) - 1, 1)
    return f"{parts[0]} {parts[-1][0]}."


def normalize_event(raw: Mapping[str, Any]) -> dict:
    """Validate and normalize one review event. Raises ValidationError.

    Required: ``source`` (string), ``external_id`` (string), ``body``
    (string, 1..4000 chars), ``reviewed_at`` (ISO-8601). Optional:
    ``stars`` (1..5), ``title`` (<= 200 chars), ``author`` (masked at
    rest).
    """
    errors: dict[str, str] = {}
    if not isinstance(raw, Mapping):
        raise ValidationError({"event": "Event must be an object."})

    source = str(raw.get("source") or "").strip()
    if not source:
        errors["source"] = "Source is required."
    external_id = str(raw.get("external_id") or "").strip()
    if not external_id:
        errors["external_id"] = "External ID is required."

    body = raw.get("body")
    if not isinstance(body, str) or not body.strip():
        errors["body"] = "Review body is required."
    elif len(body) > REVIEW_BODY_MAX_CHARS:
        errors["body"] = f"Review body must be <= {REVIEW_BODY_MAX_CHARS} chars."

    try:
        reviewed_dt = _parse_ts(raw.get("reviewed_at"))
    except (ValueError, AttributeError):
        errors["reviewed_at"] = "Must be an ISO-8601 timestamp."
        reviewed_dt = None

    stars = raw.get("stars")
    stars_int: Optional[int] = None
    if stars is not None and stars != "":
        try:
            stars_int = int(stars)
        except (TypeError, ValueError):
            errors["stars"] = "Must be an integer 1..5."
        else:
            if not 1 <= stars_int <= 5:
                errors["stars"] = "Must be 1..5."

    title = str(raw.get("title") or "")
    if len(title) > TITLE_MAX_CHARS:
        errors["title"] = f"Title must be <= {TITLE_MAX_CHARS} chars."

    if errors:
        raise ValidationError(errors)
    return {
        "source": source,
        "external_id": external_id,
        "stars": stars_int,
        "title": title.strip(),
        "body": body.strip(),
        "reviewed_at": reviewed_dt.isoformat(timespec="seconds"),
        "author_mask": _mask_author(str(raw.get("author") or "")),
    }


def _record_event(
    conn: sqlite3.Connection,
    review_id: Optional[int],
    event_type: str,
    actor: str = "system",
    detail: Optional[dict] = None,
) -> None:
    created = utcnow_iso()
    conn.execute(
        """INSERT INTO review_events (review_id, event_type, actor, detail, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            review_id,
            event_type,
            actor,
            json.dumps(detail or {}, sort_keys=True),
            created,
        ),
    )
    log_system_event(
        f"reviews.{event_type}",
        {"review_id": review_id, "actor": actor, **(detail or {})},
    )


def route_decision(
    stars: Optional[int], tag_result
) -> Optional[dict]:
    """Pure routing decision. Returns dict(queue, severity, reason) or None.

    None means: no queue entry (positive or confident-neutral review).
    Uncertain reviews ALWAYS route to ``human_review`` (default-to-alert).
    """
    uncertain = tag_result.uncertain
    sentiment = tag_result.sentiment
    s_conf = tag_result.sentiment_confidence

    severities: list[tuple[str, str, str]] = []  # (queue, severity, reason)

    if stars is not None and stars == 1:
        severities.append(
            (QUEUE_OWNER_ALERT, "critical", "1-star rating")
        )
    if stars is not None and stars == 2:
        severities.append((QUEUE_OWNER_ALERT, "high", "2-star rating"))
    if stars is not None and stars <= 3 and sentiment == "negative":
        severities.append(
            (QUEUE_OWNER_ALERT, "high", "low rating with negative sentiment")
        )
    if sentiment == "negative" and s_conf >= 0.5:
        severities.append(
            (QUEUE_OWNER_ALERT, "normal", "negative sentiment in review text")
        )
    # Sarcasm / contradiction safety: a low-star review whose text reads
    # positive (e.g. "Oh fantastic — they never showed up") is still caught
    # by the stars<=2 rules above, so it lands in owner_alert and is never
    # missed. Uncertain text always adds a human_review entry; worst wins.
    if uncertain:
        severities.append(
            (QUEUE_HUMAN_REVIEW, "normal",
             "tagger uncertain (mixed or weak evidence) — routed to human, "
             "never auto-resolved")
        )

    if not severities:
        return None

    # Worst wins: owner_alert outranks human_review; critical > high > normal.
    rank_q = {QUEUE_OWNER_ALERT: 2, QUEUE_HUMAN_REVIEW: 1}
    rank_s = {"critical": 3, "high": 2, "normal": 1}
    severities.sort(key=lambda t: (rank_q[t[0]], rank_s[t[1]]))
    queue, severity, reason = severities[-1]
    return {"queue": queue, "severity": severity, "reason": reason}


def ingest_event(
    conn: sqlite3.Connection,
    raw: Mapping[str, Any],
    tagger: Optional[ReviewTagger] = None,
    actor: str = "api",
    now: Optional[datetime] = None,
) -> dict:
    """Ingest one review event: validate, tag, route, audit.

    Idempotent on the natural key (source, external_id): re-ingesting an
    already-stored event returns the existing review id and marks
    ``duplicate=True``. Returns dict(review_id, duplicate, queue).
    """
    norm = normalize_event(raw)
    tagger = tagger or LexiconTagger()
    now_dt = _now_or(now)
    ingested_at = now_dt.isoformat(timespec="seconds")

    existing = conn.execute(
        "SELECT id FROM reviews WHERE source = ? AND external_id = ?",
        (norm["source"], norm["external_id"]),
    ).fetchone()
    if existing:
        return {
            "review_id": existing["id"],
            "duplicate": True,
            "queue": _queue_for(existing["id"], conn),
        }

    cur = conn.execute(
        """INSERT INTO reviews (source, external_id, stars, title, body,
                                reviewed_at, author_mask, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            norm["source"], norm["external_id"], norm["stars"],
            norm["title"], norm["body"], norm["reviewed_at"],
            norm["author_mask"], ingested_at,
        ),
    )
    review_id = cur.lastrowid
    _record_event(conn, review_id, "ingested", actor,
                  {"source": norm["source"], "external_id": norm["external_id"]})

    result = tagger.tag(f"{norm['title']}\n{norm['body']}")
    created = ingested_at
    conn.execute(
        """INSERT INTO review_tags (review_id, kind, label, confidence,
                                    lexicon_version, detail, created_at)
           VALUES (?, 'sentiment', ?, ?, ?, ?, ?)""",
        (review_id, result.sentiment, result.sentiment_confidence,
         result.lexicon_version, summary_json(result), created),
    )
    for label, conf in result.topics:
        conn.execute(
            """INSERT INTO review_tags (review_id, kind, label, confidence,
                                        lexicon_version, detail, created_at)
               VALUES (?, 'topic', ?, ?, ?, ?, ?)""",
            (review_id, label, conf, result.lexicon_version,
             summary_json(result), created),
        )
    _record_event(conn, review_id, "tagged", "system",
                  {"sentiment": result.sentiment,
                   "confidence": result.sentiment_confidence,
                   "uncertain": result.uncertain,
                   "lexicon_version": result.lexicon_version})

    decision = route_decision(norm["stars"], result)
    queue_row = None
    if decision:
        sla_due = now_dt + timedelta(hours=SLA_HOURS[decision["severity"]])
        conn.execute(
            """INSERT INTO review_queues (review_id, queue, severity, sla_due_at,
                                          sla_hours, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (review_id, decision["queue"], decision["severity"],
             sla_due.isoformat(timespec="seconds"),
             SLA_HOURS[decision["severity"]], created),
        )
        _record_event(conn, review_id, "routed", "system", decision)
        queue_row = {
            "queue": decision["queue"],
            "severity": decision["severity"],
            "sla_due_at": sla_due.isoformat(timespec="seconds"),
        }
    else:
        _record_event(conn, review_id, "no_action", "system",
                      {"reason": "no negative signal; no queue entry"})
    conn.commit()
    return {"review_id": review_id, "duplicate": False, "queue": queue_row}


def _queue_for(review_id: int, conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(
        "SELECT queue, severity, sla_due_at, status FROM review_queues WHERE review_id = ?",
        (review_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def ingest_csv(
    conn: sqlite3.Connection,
    csv_text: str,
    source: str = "demo_csv",
    actor: str = "api",
    tagger: Optional[ReviewTagger] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Ingest a CSV of review events.

    Columns: external_id, stars, title, body, reviewed_at, author.
    Malformed rows are skipped and counted (with row numbers); valid rows
    are ingested idempotently. Returns stats.
    """
    stats = {"ingested": 0, "duplicates": 0, "skipped": 0, "errors": []}
    if not csv_text or not csv_text.strip():
        raise ReviewError("CSV text is empty.")
    reader = csv.DictReader(io.StringIO(csv_text))
    for lineno, row in enumerate(reader, start=2):
        raw = {"source": source}
        for key in ("external_id", "stars", "title", "body", "reviewed_at", "author"):
            raw[key] = (row.get(key) or "").strip()
        if raw["stars"] == "":
            raw["stars"] = None
        try:
            out = ingest_event(conn, raw, tagger=tagger, actor=actor, now=now)
        except (ValidationError, ReviewError) as exc:
            stats["skipped"] += 1
            stats["errors"].append({"row": lineno, "error": str(exc)})
            continue
        if out["duplicate"]:
            stats["duplicates"] += 1
        else:
            stats["ingested"] += 1
    return stats


def check_sla(conn: sqlite3.Connection, now: Optional[datetime] = None) -> dict:
    """Mark open queue entries past their SLA as breached and escalate.

    Records one ``review_escalations`` row + audit event per newly breached
    entry. Uses UTC throughout; ``now`` is injectable for frozen-clock
    tests. Returns {breached: [queue_ids]}.
    """
    now_dt = _now_or(now)
    now_iso = now_dt.isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT id, review_id, queue, severity, sla_due_at FROM review_queues
           WHERE status = 'open' AND sla_due_at < ?""",
        (now_iso,),
    ).fetchall()
    breached = []
    for row in rows:
        conn.execute(
            "UPDATE review_queues SET status = 'breached' WHERE id = ?",
            (row["id"],),
        )
        reason = (
            f"SLA breached: {row['severity']} review in '{row['queue']}' "
            f"unattended past {row['sla_due_at']} UTC"
        )
        conn.execute(
            """INSERT INTO review_escalations (queue_id, triggered_at, reason)
               VALUES (?, ?, ?)""",
            (row["id"], now_iso, reason),
        )
        _record_event(conn, row["review_id"], "sla_breached", "system",
                      {"queue_id": row["id"], "queue": row["queue"],
                       "severity": row["severity"], "reason": reason})
        breached.append(row["id"])
    conn.commit()
    return {"breached": breached}


def resolve_queue(conn: sqlite3.Connection, queue_id: int, actor: str) -> dict:
    """Human marks a queue entry resolved. Returns the updated row."""
    row = conn.execute(
        "SELECT id, review_id, status FROM review_queues WHERE id = ?",
        (queue_id,),
    ).fetchone()
    if not row:
        raise ReviewError(f"No queue entry {queue_id}.")
    if row["status"] == "resolved":
        raise ReviewError(f"Queue entry {queue_id} already resolved.")
    now_iso = utcnow_iso()
    conn.execute(
        """UPDATE review_queues
           SET status = 'resolved', claimed_by = ?, resolved_at = ?
           WHERE id = ?""",
        (actor, now_iso, queue_id),
    )
    _record_event(conn, row["review_id"], "queue_resolved", actor,
                  {"queue_id": queue_id, "previous_status": row["status"]})
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM review_queues WHERE id = ?", (queue_id,)).fetchone())


def generate_draft(
    conn: sqlite3.Connection,
    review_id: int,
    template_name: str = "acknowledge_negative",
    tone: str = "professional",
    created_by: str = "system",
) -> dict:
    """Generate a response draft from a template. Human approval required
    before anything could leave the system — and there is no send path, so
    a draft can never become "sent" (asserted by tests)."""
    if template_name not in DRAFT_TEMPLATES:
        raise ReviewError(f"Unknown template {template_name!r}.")
    if tone not in _TONES:
        raise ReviewError(f"Unknown tone {tone!r}; expected one of {_TONES}.")
    review = conn.execute(
        "SELECT id FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if not review:
        raise ReviewError(f"No review {review_id}.")
    body = DRAFT_TEMPLATES[template_name][tone]
    now_iso = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO review_drafts (review_id, template_name, tone, body,
                                      status, created_by, created_at)
           VALUES (?, ?, ?, ?, 'draft', ?, ?)""",
        (review_id, template_name, tone, body, created_by, now_iso),
    )
    _record_event(conn, review_id, "draft_generated", created_by,
                  {"draft_id": cur.lastrowid, "template": template_name,
                   "tone": tone})
    conn.commit()
    return {"draft_id": cur.lastrowid, "body": body, "status": "draft"}


def decide_draft(
    conn: sqlite3.Connection, draft_id: int, approve: bool, approver: str
) -> dict:
    """Human decision on a draft: approve or reject.

    The ONLY legal transitions are draft -> approved | rejected. There is
    no transition to "sent" — approving means "this draft is cleared for a
    human to copy and send manually", which is the whole point: the system
    never posts responses itself.
    """
    row = conn.execute(
        "SELECT id, review_id, status FROM review_drafts WHERE id = ?",
        (draft_id,),
    ).fetchone()
    if not row:
        raise ReviewError(f"No draft {draft_id}.")
    if row["status"] != "draft":
        raise ReviewError(
            f"Draft {draft_id} is already {row['status']!r}; only drafts can be decided."
        )
    new_status = "approved" if approve else "rejected"
    now_iso = utcnow_iso()
    conn.execute(
        """UPDATE review_drafts
           SET status = ?, approved_by = ?, decided_at = ?
           WHERE id = ?""",
        (new_status, approver, now_iso, draft_id),
    )
    _record_event(conn, row["review_id"], "draft_decided", approver,
                  {"draft_id": draft_id, "decision": new_status})
    conn.commit()
    return {"draft_id": draft_id, "status": new_status}


def template_sanity() -> dict:
    """Assert every draft template contains no factual claims.

    Checks: no digits, no '$', none of the forbidden claim words. Used by
    tests and exposed via the API for transparency.
    """
    problems = []
    for name, tones in DRAFT_TEMPLATES.items():
        for tone, text in tones.items():
            lowered = text.lower()
            if re.search(r"\d", text):
                problems.append(f"{name}/{tone}: contains a digit")
            if "$" in text:
                problems.append(f"{name}/{tone}: contains '$'")
            for word in FORBIDDEN_TEMPLATE_WORDS:
                if re.search(r"\b" + re.escape(word) + r"\b", lowered):
                    problems.append(f"{name}/{tone}: contains forbidden word {word!r}")
    return {"ok": not problems, "problems": problems}


def queue_summary(conn: sqlite3.Connection, now: Optional[datetime] = None) -> dict:
    """Triage queue summary with live SLA status (UTC)."""
    now_iso = _now_or(now).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT q.id, q.review_id, q.queue, q.severity, q.status, q.sla_due_at,
                  q.sla_hours, q.claimed_by, q.created_at, r.stars, r.title,
                  r.author_mask,
                  (q.sla_due_at < ?) AS overdue
           FROM review_queues q JOIN reviews r ON r.id = q.review_id
           ORDER BY q.severity = 'critical' DESC, q.severity = 'high' DESC,
                    q.created_at ASC""",
        (now_iso,),
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['queue']}/{row['status']}"
        counts[key] = counts.get(key, 0) + 1
    return {"queues": [dict(r) for r in rows], "counts": counts}


def sla_status(conn: sqlite3.Connection, now: Optional[datetime] = None) -> dict:
    """SLA overview: open, overdue (breached or past due), escalations."""
    now_iso = _now_or(now).isoformat(timespec="seconds")
    open_n = conn.execute(
        "SELECT COUNT(*) AS n FROM review_queues WHERE status = 'open'").fetchone()["n"]
    overdue = conn.execute(
        """SELECT COUNT(*) AS n FROM review_queues
           WHERE status IN ('open', 'breached') AND sla_due_at < ?""",
        (now_iso,)).fetchone()["n"]
    escalations = conn.execute(
        "SELECT COUNT(*) AS n FROM review_escalations").fetchone()["n"]
    by_severity = conn.execute(
        """SELECT severity, status, COUNT(*) AS n FROM review_queues
           GROUP BY severity, status""").fetchall()
    return {
        "open": open_n,
        "overdue": overdue,
        "escalations": escalations,
        "by_severity": [dict(r) for r in by_severity],
        "as_of_utc": now_iso,
    }


def ensure_lexicons(conn: sqlite3.Connection) -> int:
    """Seed bundled lexicons if the table is empty (idempotent)."""
    n = conn.execute("SELECT COUNT(*) AS n FROM review_lexicons").fetchone()["n"]
    if n == 0:
        return seed_lexicons(conn)
    return 0
