"""Tests for Q08 — review ingest, routing, SLA timers, and draft gate.

All data is synthetic fixture data. The frozen clock makes every SLA
assertion deterministic.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mavenu import reviews
from mavenu.db import get_connection, rollback_migration, run_migrations
from mavenu.reviews import (
    DRAFT_TRANSITIONS,
    DRAFT_TEMPLATES,
    SLA_HOURS,
    ReviewError,
    check_sla,
    decide_draft,
    ensure_lexicons,
    generate_draft,
    ingest_csv,
    ingest_event,
    normalize_event,
    queue_summary,
    resolve_queue,
    route_decision,
    sla_status,
    template_sanity,
)
from mavenu.tagger import LexiconTagger, TagResult
from mavenu.validation import ValidationError

from tests.q08_review_fixtures import FIXTURE, adversarial_fixture

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    c = get_connection(str(tmp_path / "q08.db"))
    run_migrations(c)
    ensure_lexicons(c)
    yield c
    c.close()


def _event(external_id, stars=5, body="Great service.", **kw):
    raw = {
        "source": "test",
        "external_id": external_id,
        "stars": stars,
        "title": kw.get("title", "Test review"),
        "body": body,
        "reviewed_at": "2026-10-23T11:00:00Z",
        "author": "Test Person",
    }
    raw.update(kw)
    return raw


# -- normalization -------------------------------------------------------

def test_normalize_event_ok():
    norm = normalize_event(_event("e1"))
    assert norm["stars"] == 5
    assert norm["author_mask"].startswith("Test")
    assert "Test Person" not in norm["author_mask"]  # masked at rest


def test_normalize_event_missing_fields():
    with pytest.raises(ValidationError) as exc:
        normalize_event({"source": "test"})
    assert "external_id" in exc.value.field_errors
    assert "body" in exc.value.field_errors
    assert "reviewed_at" in exc.value.field_errors


def test_normalize_event_bad_stars_and_timestamp():
    with pytest.raises(ValidationError) as exc:
        normalize_event(_event("e2", stars=9, reviewed_at="not-a-date"))
    assert "stars" in exc.value.field_errors
    assert "reviewed_at" in exc.value.field_errors


def test_normalize_event_body_too_long():
    with pytest.raises(ValidationError):
        normalize_event(_event("e3", body="x" * 4001))


# -- ingest ---------------------------------------------------------------

def test_ingest_event_stores_and_tags(conn):
    out = ingest_event(conn, _event("e1", body="Terrible mess, late and overpriced."),
                       now=T0)
    assert out["duplicate"] is False
    row = conn.execute("SELECT stars, author_mask FROM reviews WHERE id = ?",
                       (out["review_id"],)).fetchone()
    assert row["stars"] == 5
    tags = conn.execute(
        "SELECT kind, label FROM review_tags WHERE review_id = ?",
        (out["review_id"],)).fetchall()
    kinds = {(t["kind"], t["label"]) for t in tags}
    assert ("sentiment", "negative") in kinds
    assert any(k == "topic" for k, _ in kinds)


def test_ingest_idempotent_on_natural_key(conn):
    first = ingest_event(conn, _event("e1"), now=T0)
    second = ingest_event(conn, _event("e1", body="different body"), now=T0)
    assert second["duplicate"] is True
    assert second["review_id"] == first["review_id"]
    n = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
    assert n == 1


def test_ingest_csv_stats_and_skips(conn):
    csv_text = (
        "external_id,stars,title,body,reviewed_at,author\n"
        "c1,5,Good,Great service.,2026-10-23T10:00:00Z,Alice\n"
        "c2,notanint,Bad,,2026-10-23T10:00:00Z,Bob\n"
        "c1,5,Good,Great service.,2026-10-23T10:00:00Z,Alice\n"
    )
    stats = ingest_csv(conn, csv_text, actor="test", now=T0)
    assert stats["ingested"] == 1
    assert stats["duplicates"] == 1
    assert stats["skipped"] == 1
    assert len(stats["errors"]) == 1


def test_ingest_csv_empty_rejected(conn):
    with pytest.raises(ReviewError):
        ingest_csv(conn, "   ")


def test_ingest_records_audit_events(conn):
    out = ingest_event(
        conn,
        _event("e1", stars=1, body="Terrible, awful, horrible experience."),
        now=T0,
    )
    types = [
        r["event_type"]
        for r in conn.execute(
            "SELECT event_type FROM review_events WHERE review_id = ? ORDER BY id",
            (out["review_id"],))
    ]
    assert types == ["ingested", "tagged", "routed"]


def test_replaceable_tagger_protocol_drives_ingest(conn):
    class StubTagger:
        name = "stub-v0"

        def tag(self, text: str) -> TagResult:
            return TagResult(
                sentiment="neutral", sentiment_confidence=0.0, topics=(),
                uncertain=True, matched_terms=(),
                explanation="stub", lexicon_version="stub",
            )

    out = ingest_event(conn, _event("e1"), tagger=StubTagger(), now=T0)
    row = conn.execute(
        "SELECT lexicon_version FROM review_tags WHERE review_id = ? LIMIT 1",
        (out["review_id"],)).fetchone()
    assert row["lexicon_version"] == "stub"
    # Uncertain stub tag -> routed to human_review (default-to-alert).
    q = conn.execute(
        "SELECT queue FROM review_queues WHERE review_id = ?",
        (out["review_id"],)).fetchone()
    assert q["queue"] == "human_review"


# -- routing ---------------------------------------------------------------

def _tag(text):
    return LexiconTagger().tag(text)


def test_critical_routing_recall_100_percent_on_fixture(conn):
    """Every 1-star fixture row must land in owner_alert as critical."""
    critical = [r for r in FIXTURE if r["stars"] == 1]
    assert len(critical) >= 30, "fixture must contain critical rows"
    missed = []
    for row in critical:
        out = ingest_event(
            conn,
            _event(row["external_id"], stars=row["stars"],
                   title=row["title"], body=row["body"]),
            now=T0,
        )
        q = conn.execute(
            "SELECT queue, severity FROM review_queues WHERE review_id = ?",
            (out["review_id"],)).fetchone()
        if q is None or q["queue"] != "owner_alert" or q["severity"] != "critical":
            missed.append(row["external_id"])
    print(f"\ncritical routing recall: {len(critical) - len(missed)}/{len(critical)}")
    assert missed == [], missed


def test_fixture_routing_matches_expectations(conn):
    """Every one of the 200 fixture rows routes to its expected queue."""
    mismatches = []
    for row in FIXTURE:
        out = ingest_event(
            conn,
            _event("rt-" + row["external_id"], stars=row["stars"],
                   title=row["title"], body=row["body"]),
            now=T0,
        )
        q = conn.execute(
            "SELECT queue FROM review_queues WHERE review_id = ?",
            (out["review_id"],)).fetchone()
        got = q["queue"] if q else None
        if got != row["expected_queue"]:
            mismatches.append((row["external_id"], row["expected_queue"], got))
    assert mismatches == [], mismatches[:10]


def test_default_to_alert_on_uncertainty():
    """Ambiguous reviews are never auto-resolved: no decision returns None
    for them; they always land in a human-attended queue."""
    for row in adversarial_fixture():
        result = _tag(row["title"] + "\n" + row["body"])
        decision = route_decision(row["stars"], result)
        assert decision is not None, row["external_id"]
        assert decision["queue"] in ("owner_alert", "human_review")


def test_sarcasm_reaches_owner_not_silenced(conn):
    """Sarcastic 1-star: text reads positive to the lexicon, but the star
    rules still raise it as critical — a severe review is never missed."""
    out = ingest_event(
        conn,
        _event("sarc1", stars=1, body="Oh fantastic — they never showed up. Wonderful!"),
        now=T0,
    )
    q = conn.execute(
        "SELECT queue, severity FROM review_queues WHERE review_id = ?",
        (out["review_id"],)).fetchone()
    assert q["queue"] == "owner_alert"
    assert q["severity"] == "critical"


def test_positive_review_gets_no_queue(conn):
    out = ingest_event(
        conn,
        _event("pos1", stars=5,
               body="Excellent work, the crew was friendly and professional."),
        now=T0,
    )
    assert out["queue"] is None
    types = [
        r["event_type"]
        for r in conn.execute(
            "SELECT event_type FROM review_events WHERE review_id = ?",
            (out["review_id"],))
    ]
    assert "no_action" in types


def test_route_decision_pure_function():
    neg = TagResult("negative", 0.9, (), False, (), "", "1.0")
    assert route_decision(1, neg)["severity"] == "critical"
    assert route_decision(2, neg)["severity"] == "high"
    pos = TagResult("positive", 0.95, (), False, (), "", "1.0")
    assert route_decision(5, pos) is None
    unc = TagResult("neutral", 0.0, (), True, (), "", "1.0")
    assert route_decision(None, unc)["queue"] == "human_review"


def test_sla_hours_documented():
    assert SLA_HOURS == {"critical": 4, "high": 12, "normal": 24}


# -- SLA --------------------------------------------------------------------

def test_sla_due_is_utc_and_correct(conn):
    out = ingest_event(
        conn, _event("sla1", stars=1, body="Terrible."), now=T0)
    q = conn.execute(
        "SELECT sla_due_at, sla_hours FROM review_queues WHERE review_id = ?",
        (out["review_id"],)).fetchone()
    assert q["sla_hours"] == 4
    assert q["sla_due_at"] == "2026-10-23T16:00:00+00:00"


def test_sla_breach_escalates_on_frozen_clock(conn):
    crit = ingest_event(conn, _event("b1", stars=1, body="Terrible."), now=T0)
    norm = ingest_event(
        conn, _event("b2", stars=4, body="The price was not fair at all."),
        now=T0)
    # 5 hours later: the 4h critical SLA is breached, the 24h normal is not.
    result = check_sla(conn, now=T0 + timedelta(hours=5))
    assert len(result["breached"]) == 1
    status = conn.execute(
        "SELECT status FROM review_queues WHERE review_id = ?",
        (crit["review_id"],)).fetchone()["status"]
    assert status == "breached"
    status2 = conn.execute(
        "SELECT status FROM review_queues WHERE review_id = ?",
        (norm["review_id"],)).fetchone()["status"]
    assert status2 == "open"
    esc = conn.execute("SELECT reason FROM review_escalations").fetchall()
    assert len(esc) == 1
    assert "SLA breached" in esc[0]["reason"]
    events = conn.execute(
        "SELECT event_type FROM review_events WHERE review_id = ?",
        (crit["review_id"],)).fetchall()
    assert "sla_breached" in {e["event_type"] for e in events}


def test_sla_check_idempotent(conn):
    ingest_event(conn, _event("b1", stars=1, body="Terrible."), now=T0)
    first = check_sla(conn, now=T0 + timedelta(hours=5))
    second = check_sla(conn, now=T0 + timedelta(hours=6))
    assert len(first["breached"]) == 1
    assert second["breached"] == []  # already breached: no duplicate escalation


def test_resolve_queue(conn):
    out = ingest_event(conn, _event("r1", stars=1, body="Terrible."), now=T0)
    qid = conn.execute(
        "SELECT id FROM review_queues WHERE review_id = ?",
        (out["review_id"],)).fetchone()["id"]
    updated = resolve_queue(conn, qid, actor="owner@example.com")
    assert updated["status"] == "resolved"
    assert updated["claimed_by"] == "owner@example.com"
    with pytest.raises(ReviewError):
        resolve_queue(conn, qid, actor="owner@example.com")
    with pytest.raises(ReviewError):
        resolve_queue(conn, 99999, actor="owner@example.com")


def test_queue_summary_and_sla_status(conn):
    ingest_event(conn, _event("q1", stars=1, body="Terrible."), now=T0)
    ingest_event(conn, _event("q2", stars=5, body="Excellent, wonderful!"),
                 now=T0)
    summary = queue_summary(conn, now=T0)
    assert summary["counts"] == {"owner_alert/open": 1}
    assert summary["queues"][0]["overdue"] == 0
    status = sla_status(conn, now=T0 + timedelta(hours=5))
    assert status["open"] == 1
    # Past due but not yet escalated: check_sla has not run, so the entry is
    # 'open' and overdue, with zero recorded escalations — the exact gap the
    # SLA sweep closes.
    assert status["overdue"] == 1
    assert status["escalations"] == 0
    assert status["as_of_utc"].endswith("+00:00")


# -- drafts -----------------------------------------------------------------

def test_templates_contain_no_factual_claims():
    report = template_sanity()
    assert report["ok"], report["problems"]


def test_templates_have_all_tones():
    for name, tones in DRAFT_TEMPLATES.items():
        assert set(tones) == {"professional", "warm", "brief"}, name


def test_generate_draft(conn):
    out = ingest_event(conn, _event("d1", stars=1, body="Terrible."), now=T0)
    draft = generate_draft(conn, out["review_id"], tone="warm")
    assert draft["status"] == "draft"
    assert draft["body"] == DRAFT_TEMPLATES["acknowledge_negative"]["warm"]
    with pytest.raises(ReviewError):
        generate_draft(conn, out["review_id"], template_name="nope")
    with pytest.raises(ReviewError):
        generate_draft(conn, out["review_id"], tone="sarcastic")
    with pytest.raises(ReviewError):
        generate_draft(conn, 99999)


def test_human_approval_gate(conn):
    out = ingest_event(conn, _event("d2", stars=2, body="Late and sloppy."),
                       now=T0)
    draft = generate_draft(conn, out["review_id"])
    decided = decide_draft(conn, draft["draft_id"], approve=True,
                           approver="owner@example.com")
    assert decided["status"] == "approved"
    row = conn.execute(
        "SELECT status, approved_by FROM review_drafts WHERE id = ?",
        (draft["draft_id"],)).fetchone()
    assert row["approved_by"] == "owner@example.com"
    # Decided drafts cannot be decided again.
    with pytest.raises(ReviewError):
        decide_draft(conn, draft["draft_id"], approve=False,
                     approver="owner@example.com")


def test_reject_path(conn):
    out = ingest_event(conn, _event("d3", stars=2, body="Late and sloppy."),
                       now=T0)
    draft = generate_draft(conn, out["review_id"])
    decided = decide_draft(conn, draft["draft_id"], approve=False,
                           approver="owner@example.com")
    assert decided["status"] == "rejected"


def test_sent_state_is_unreachable():
    """There is no 'sent' state anywhere: not in the transition map, not
    in the DB CHECK constraint, and no send/post function exists."""
    assert "sent" not in DRAFT_TRANSITIONS["draft"]
    assert "sent" not in str(DRAFT_TRANSITIONS)
    send_like = [n for n in dir(reviews)
                 if "send" in n.lower() or "post" in n.lower()]
    assert send_like == [], send_like
    src_names = [n for n, v in vars(reviews).items() if callable(v)]
    assert "send_draft" not in src_names


def test_db_check_constraint_rejects_sent(conn):
    out = ingest_event(conn, _event("d4", stars=2, body="Late."), now=T0)
    draft = generate_draft(conn, out["review_id"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE review_drafts SET status = 'sent' WHERE id = ?",
                     (draft["draft_id"],))


def test_approve_nonexistent_draft(conn):
    with pytest.raises(ReviewError):
        decide_draft(conn, 99999, approve=True, approver="x")


# -- lexicons ---------------------------------------------------------------

def test_ensure_lexicons_idempotent(conn):
    assert ensure_lexicons(conn) == 0  # seeded by fixture


# -- rollback -----------------------------------------------------------------

def test_migration_011_down_step_rolls_back_for_real(tmp_path):
    db_path = str(tmp_path / "rollback.db")
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
        assert "011_reviews.sql" in {
            r["name"] for r in
            conn.execute("SELECT name FROM schema_migrations")
        }
        # Put real Q08 data in.
        ensure_lexicons(conn)
        out = ingest_event(conn, _event("rb1", stars=1, body="Terrible."),
                           now=T0)
        generate_draft(conn, out["review_id"])
        check_sla(conn, now=T0 + timedelta(hours=5))

        assert rollback_migration(conn, "011_reviews.sql") is True

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("reviews", "review_tags", "review_queues", "review_drafts",
                  "review_escalations", "review_events", "review_lexicons"):
            assert t not in tables, t
        # Other projects' tables survive.
        assert "leads" in tables
        assert "011_reviews.sql" not in {
            r["name"] for r in
            conn.execute("SELECT name FROM schema_migrations")
        }
        # Re-apply works.
        applied = run_migrations(conn)
        assert "011_reviews.sql" in applied
        assert "reviews" in {
            r["name"] for r in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
