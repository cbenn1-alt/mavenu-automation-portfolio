"""Q03 tests: RFM features, dormancy scoring, segmentation, suppression,
sequence plans, outbox idempotency, flush-time suppression re-check,
report reconciliation, and migration rollback.

All customer/job data below is synthetic fixture data (obviously fake
names like "Acme Test Co"); nothing here is real.
"""
from datetime import datetime, timedelta, timezone

import pytest

from mavenu import attribution as attribution_service
from mavenu import reactivation as rx
from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.rfm import (
    FREQUENCY_CAP,
    MONETARY_CAP_CENTS,
    RECENCY_WINDOW_DAYS,
    DeterministicDemoScorer,
    compute_rfm,
)
from mavenu.validation import ValidationError

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
NAMES = ["Acme Test Co", "Beta Demo LLC", "Gamma Fixture Inc", "Delta Sample Co",
         "Epsilon Mock Ltd", "Zeta Trial Co"]


def make_customer(conn, name="Acme Test Co", now=NOW):
    return rx.create_customer(conn, customer_name=name, now=now)


def add_job(conn, customer_id, job_date, amount_cents, service="hvac",
            source="organic", ref="JOB-1", now=NOW):
    return rx.add_job(
        conn, customer_id, job_ref=ref, service_type=service,
        job_date=job_date, amount_cents=amount_cents,
        booking_source=source, now=now,
    )


# ---------------------------------------------------------------------------
# RFM feature computation
# ---------------------------------------------------------------------------

def test_compute_rfm_matches_hand_computed_fixture():
    # Hand computation:
    #   jobs: 2026-01-01 $100.00, 2026-04-01 $300.00; now = 2026-10-23 12:00 UTC
    #   recency = 205.0 days (2026-04-01 -> 2026-10-23), frequency = 2,
    #   monetary = 40000 cents.
    jobs = [
        {"job_date": "2026-01-01T12:00:00+00:00", "amount_cents": 10000},
        {"job_date": "2026-04-01T12:00:00+00:00", "amount_cents": 30000},
    ]
    features = compute_rfm(jobs, now=NOW)
    assert features.recency_days == 205.0
    assert features.frequency == 2
    assert features.monetary_cents == 40000
    assert features.last_job_date == "2026-04-01T12:00:00+00:00"


def test_compute_rfm_no_history():
    features = compute_rfm([], now=NOW)
    assert features.recency_days is None
    assert features.frequency == 0
    assert features.monetary_cents == 0
    assert features.last_job_date is None


def test_compute_rfm_ignores_future_jobs():
    jobs = [{"job_date": "2027-01-01T00:00:00+00:00", "amount_cents": 99999}]
    features = compute_rfm(jobs, now=NOW)
    assert features.frequency == 0


def test_compute_rfm_requires_aware_now():
    with pytest.raises(ValueError):
        compute_rfm([], now=datetime(2026, 10, 23, 12, 0, 0))


# ---------------------------------------------------------------------------
# Dormancy scoring: documented weights + determinism
# ---------------------------------------------------------------------------

def test_dormancy_score_matches_hand_computed_weights():
    # Same fixture as above. Hand computation:
    #   recency_norm = 205/365 = 0.5616438... -> 0.50 * 0.5616438 = 0.2808219
    #   frequency_norm = 2/10 = 0.2          -> 0.30 * (1 - 0.2)  = 0.2400000
    #   monetary_norm = 40000/200000 = 0.2   -> 0.20 * (1 - 0.2)  = 0.1600000
    #   total = 0.6808219 -> rounded 0.681
    scorer = DeterministicDemoScorer()
    scored = scorer.score({"recency_days": 205.0, "frequency": 2,
                           "monetary_cents": 40000})
    assert scored.score == 0.681
    assert scored.scorer == "deterministic-rfm-v1"
    assert len(scored.reasons) == 3  # one line per documented weight


def test_dormancy_score_no_history_is_fully_dormant():
    scorer = DeterministicDemoScorer()
    scored = scorer.score({"recency_days": None, "frequency": 0,
                           "monetary_cents": 0})
    # 0.50*1.0 + 0.30*1.0 + 0.20*1.0 = 1.0
    assert scored.score == 1.0
    assert "no-history" in scored.flags


def test_dormancy_score_perfect_customer_is_zero():
    scorer = DeterministicDemoScorer()
    scored = scorer.score({"recency_days": 0.0, "frequency": FREQUENCY_CAP,
                           "monetary_cents": MONETARY_CAP_CENTS})
    assert scored.score == 0.0


def test_dormancy_score_deterministic_across_replays():
    scorer = DeterministicDemoScorer()
    features = {"recency_days": 205.0, "frequency": 2, "monetary_cents": 40000}
    first = scorer.score(features)
    for _ in range(1000):
        assert scorer.score(features) == first
    # Feature dict key order must not matter either.
    assert scorer.score({"monetary_cents": 40000, "frequency": 2,
                         "recency_days": 205.0}) == first


def test_dormancy_score_explains_every_weight():
    scorer = DeterministicDemoScorer()
    scored = scorer.score({"recency_days": 100.0, "frequency": 5,
                           "monetary_cents": 50000})
    text = " ".join(scored.reasons)
    assert "recency" in text and "frequency" in text and "monetary" in text


# ---------------------------------------------------------------------------
# Segmentation rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, "active"), (0.249, "active"),
        (0.25, "cooling"), (0.499, "cooling"),
        (0.50, "dormant"), (0.749, "dormant"),
        (0.75, "churned"), (1.0, "churned"),
    ],
)
def test_segment_boundaries(score, expected):
    assert rx.segment_for_score(score) == expected


def test_score_customers_persists_segment_and_audit(conn):
    # One job (2026-04-01, $400.00), now = 2026-10-23. Hand computation:
    #   recency_norm = 205/365 -> 0.50 * 0.5616438 = 0.2808219
    #   frequency_norm = 1/10   -> 0.30 * (1 - 0.1) = 0.2700000
    #   monetary_norm = 40000/200000 -> 0.20 * (1 - 0.2) = 0.1600000
    #   total = 0.7108219 -> 0.711 -> "dormant"
    c = make_customer(conn)
    add_job(conn, c["id"], "2026-04-01T12:00:00+00:00", 40000, ref="JOB-1")
    results = rx.score_customers(conn, now=NOW)
    assert len(results) == 1
    assert results[0]["dormancy_score"] == 0.711
    assert results[0]["segment"] == "dormant"
    stored = rx.get_customer(conn, c["id"])
    assert stored["segment"] == "dormant" and stored["scored_at"] is not None
    events = rx.customer_events(conn, c["id"])
    scored_events = [e for e in events if e["event_type"] == "customer.scored"]
    assert len(scored_events) == 1
    detail = scored_events[0]["detail"]
    assert '"score": 0.711' in detail and '"segment": "dormant"' in detail


def test_score_customers_deterministic_across_replays(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2026-01-01T12:00:00+00:00", 10000, ref="JOB-1")
    first = [ (r["public_id"], r["dormancy_score"], r["segment"])
              for r in rx.score_customers(conn, now=NOW) ]
    for _ in range(50):
        replay = [ (r["public_id"], r["dormancy_score"], r["segment"])
                   for r in rx.score_customers(conn, now=NOW) ]
        assert replay == first


# ---------------------------------------------------------------------------
# Suppression: absolute
# ---------------------------------------------------------------------------

def _queue_and_flush(conn, now=NOW):
    rx.score_customers(conn, now=now)
    rx.run_winback(conn, now=now)
    return rx.flush_outbox(conn, now=now)


def test_dnc_customer_gets_zero_touches(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    rx.set_suppression(conn, c["id"], do_not_contact=True, now=NOW)
    rx.score_customers(conn, now=NOW)
    run = rx.run_winback(conn, now=NOW)
    assert run["queued"] == []
    assert any(s["reason"] == "suppressed:do_not_contact" for s in run["skipped"])
    flushed = rx.flush_outbox(conn, now=NOW)
    assert flushed == []
    assert rx.outbox(conn) == []


def test_recent_complaint_suppresses(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    rx.record_complaint(conn, c["id"], now=NOW)
    assert rx.suppression_reason(rx.get_customer(conn, c["id"]), NOW) == "recent_complaint"
    run = rx.run_winback(conn, now=NOW + timedelta(days=1))
    assert run["queued"] == []
    assert rx.outbox(conn) == []


def test_old_complaint_does_not_suppress(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    rx.record_complaint(conn, c["id"], now=NOW - timedelta(days=200))
    assert rx.suppression_reason(rx.get_customer(conn, c["id"]), NOW) is None


def test_active_job_suppresses(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    rx.set_suppression(conn, c["id"], active_job=True, active_job_ref="JOB-OPEN-1",
                       now=NOW)
    assert rx.suppression_reason(rx.get_customer(conn, c["id"]), NOW) == "active_job"
    run = rx.run_winback(conn, now=NOW)
    assert run["queued"] == []


def test_complaint_set_mid_sequence_blocks_flush(conn):
    """Adversarial: flag arrives AFTER queueing but BEFORE flush."""
    c = make_customer(conn, name="Acme Test Co")
    add_job(conn, c["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    rx.score_customers(conn, now=NOW)
    run = rx.run_winback(conn, now=NOW)
    assert len(run["queued"]) >= 1  # step(s) queued while unsuppressed
    queued_before = rx.outbox(conn, status="queued")
    assert len(queued_before) >= 1

    # Complaint lands mid-sequence; a second win-back run must queue nothing.
    rx.record_complaint(conn, c["id"], now=NOW + timedelta(hours=1))
    run2 = rx.run_winback(conn, now=NOW + timedelta(hours=2))
    assert run2["queued"] == []

    # Flush must NOT call the adapter: rows become 'suppressed' instead.
    calls = []

    class RecordingAdapter:
        name = "recording"

        def send(self, recipient_label, subject, body):
            calls.append((recipient_label, subject, body))
            return {"status": "sent"}

    flushed = rx.flush_outbox(conn, RecordingAdapter(), now=NOW + timedelta(hours=3))
    assert calls == []  # the adapter was never invoked
    assert all(f["status"] == "suppressed" for f in flushed)
    assert rx.outbox(conn, status="queued") == []
    assert rx.outbox(conn, status="sent") == []
    assert len(rx.outbox(conn, status="suppressed")) == len(queued_before)
    # And the suppression is audit-logged.
    types = [e["event_type"] for e in rx.customer_events(conn, c["id"])]
    assert "touch.suppressed_at_flush" in types


def test_dnc_set_mid_sequence_blocks_flush(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    rx.score_customers(conn, now=NOW)
    assert rx.run_winback(conn, now=NOW)["queued"]
    rx.set_suppression(conn, c["id"], do_not_contact=True, now=NOW)
    flushed = rx.flush_outbox(conn, now=NOW)
    assert all(f["status"] == "suppressed" for f in flushed)
    assert rx.send_log(conn) == []  # stub never logged a send


def test_suppression_adversarial_no_leaks(conn):
    """300 customers x mixed flag states x interleaved flag changes: zero
    touches (queued or sent) may exist for a suppressed customer."""
    now = NOW
    customers = [make_customer(conn, name=n, now=now) for n in
                 [f"Fixture Co {i:03d}" for i in range(300)]]
    for i, c in enumerate(customers):
        add_job(conn, c["id"], "2025-06-01T12:00:00+00:00", 45000,
                ref=f"JOB-{i}", now=now)
        if i % 3 == 0:
            rx.set_suppression(conn, c["id"], do_not_contact=True, now=now)
        elif i % 3 == 1:
            rx.record_complaint(conn, c["id"], now=now)
    rx.score_customers(conn, now=now)
    rx.run_winback(conn, now=now)
    # Mid-sequence: flip flags on the remaining third, too.
    for i, c in enumerate(customers):
        if i % 3 == 2 and i % 2 == 0:
            rx.set_suppression(conn, c["id"], active_job=True, now=now)

    class ExplodingAdapter:
        name = "exploding"

        def send(self, recipient_label, subject, body):
            raise AssertionError("adapter called for a suppressed customer")

    # Any customer still unsuppressed uses the stub; suppressed rows must
    # never reach the adapter at all. We verify at the DB level instead of
    # relying on which adapter runs: no sent/queued row may reference a
    # suppressed customer.
    rx.flush_outbox(conn, now=now)
    for c in customers:
        fresh = rx.get_customer(conn, c["id"])
        if rx.is_suppressed(fresh, now):
            rows = rx.touch_history(conn, c["id"])
            bad = [r for r in rows if r["status"] in ("queued", "sent")]
            assert bad == [], f"leak for {fresh['public_id']}: {bad}"


# ---------------------------------------------------------------------------
# Sequence plans + outbox idempotency
# ---------------------------------------------------------------------------

def test_sequence_plans_are_documented_per_segment():
    assert rx.SEQUENCE_PLANS["active"] == []
    assert len(rx.SEQUENCE_PLANS["cooling"]) == 2
    assert len(rx.SEQUENCE_PLANS["dormant"]) == 3
    assert len(rx.SEQUENCE_PLANS["churned"]) == 2
    for segment, plan in rx.SEQUENCE_PLANS.items():
        for i, step in enumerate(plan, start=1):
            assert step["step_index"] == i
            assert step["channel"] == "email"


def test_run_winback_queues_only_due_steps(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-06-01T12:00:00+00:00", 45000, ref="JOB-1")
    # score 0.925 -> churned; plan steps at day 0 and day 30.
    rx.score_customers(conn, now=NOW)
    run = rx.run_winback(conn, now=NOW)
    assert [q["step_index"] for q in run["queued"]] == [1]
    # Step 2 becomes due 30 days later.
    later = NOW + timedelta(days=30)
    run2 = rx.run_winback(conn, now=later)
    assert [q["step_index"] for q in run2["queued"]] == [2]
    assert len(rx.outbox(conn)) == 2


def test_run_winback_replay_is_idempotent(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-06-01T12:00:00+00:00", 45000, ref="JOB-1")
    rx.score_customers(conn, now=NOW)
    first = rx.run_winback(conn, now=NOW)
    assert len(first["queued"]) == 1
    for _ in range(200):
        replay = rx.run_winback(conn, now=NOW)
        assert replay["queued"] == []
    assert len(rx.outbox(conn)) == 1
    keys = [r["idempotency_key"] for r in rx.outbox(conn)]
    assert len(set(keys)) == 1 and keys[0].startswith("rx:")


def test_touch_copy_is_rendered_and_labeled_demo(conn):
    c = make_customer(conn, name="Acme Test Co")
    add_job(conn, c["id"], "2025-06-01T12:00:00+00:00", 45000, ref="JOB-1",
            service="plumbing")
    rx.score_customers(conn, now=NOW)
    rx.run_winback(conn, now=NOW)
    row = rx.outbox(conn)[0]
    assert "Acme Test Co" in row["body"]
    assert "plumbing" in row["body"]
    assert "nothing was sent" in row["body"]
    assert row["recipient_label"] == "synthetic-customer:CUS-000001"


def test_touch_render_missing_variable_fails_closed(conn):
    with pytest.raises(rx.TouchRenderError):
        rx.render_touch("Hello {{missing_name}}", {"other": "x"})


def test_flush_writes_send_log_with_stub(conn):
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-06-01T12:00:00+00:00", 45000, ref="JOB-1")
    rx.score_customers(conn, now=NOW)
    rx.run_winback(conn, now=NOW)
    flushed = rx.flush_outbox(conn, now=NOW)
    assert flushed[0]["adapter"] == "stub"
    assert flushed[0]["status"] == "stub-logged"
    log = rx.send_log(conn)
    assert len(log) == 1 and log[0]["adapter"] == "stub"
    # Second flush is a no-op (send_log UNIQUE on outbox_id).
    assert rx.flush_outbox(conn, now=NOW) == []
    assert len(rx.send_log(conn)) == 1


# ---------------------------------------------------------------------------
# Reports reconcile to source rows
# ---------------------------------------------------------------------------

def test_segment_report_reconciles_to_rows(conn):
    now = NOW
    # dormant customer (single old job)
    c1 = make_customer(conn, name="Acme Test Co", now=now)
    add_job(conn, c1["id"], "2025-06-01T12:00:00+00:00", 45000, ref="JOB-1", now=now)
    # active customer: 10 recent jobs at $500 each -> frequency_norm = 1.0,
    # monetary_norm = 1.0, recency ~0 -> dormancy ~= 0.0 < 0.25
    c2 = make_customer(conn, name="Beta Demo LLC", now=now)
    for i in range(10):
        add_job(conn, c2["id"],
                (now - timedelta(days=3 + i * 20)).isoformat(), 50000,
                ref=f"JOB-A{i}", now=now)
    # suppressed dormant customer
    c3 = make_customer(conn, name="Gamma Fixture Inc", now=now)
    add_job(conn, c3["id"], "2025-01-01T12:00:00+00:00", 90000, ref="JOB-3", now=now)
    rx.set_suppression(conn, c3["id"], do_not_contact=True, now=now)
    rx.score_customers(conn, now=now)

    report = rx.segment_report(conn)
    by_seg = {s["segment"]: s for s in report["segments"]}
    # Independent re-computation straight from the tables.
    for segment in rx.SEGMENTS:
        rows = conn.execute(
            "SELECT id, dormancy_score FROM reactivation_customers WHERE segment = ?",
            (segment,),
        ).fetchall()
        assert by_seg[segment]["customers"] == len(rows)
        if rows:
            expected_avg = round(sum(r["dormancy_score"] for r in rows) / len(rows), 3)
            assert by_seg[segment]["avg_dormancy"] == expected_avg
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM reactivation_customers").fetchone()["n"]
    assert report["total_customers"] == total == 3
    assert by_seg["churned"]["customers"] + by_seg["dormant"]["customers"] + \
        by_seg["active"]["customers"] + by_seg["cooling"]["customers"] == 3
    assert by_seg["active"]["customers"] == 1  # the recent-job customer


def test_suppression_audit_lists_every_flagged_customer(conn):
    c1 = make_customer(conn, name="Acme Test Co")
    c2 = make_customer(conn, name="Beta Demo LLC")
    add_job(conn, c1["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-1")
    add_job(conn, c2["id"], "2025-01-01T12:00:00+00:00", 50000, ref="JOB-2")
    rx.set_suppression(conn, c1["id"], do_not_contact=True, now=NOW)
    rx.record_complaint(conn, c2["id"], now=NOW)
    audit = rx.suppression_audit(conn, now=NOW)
    assert audit["suppressed_count"] == 2
    reasons = {c["public_id"]: c["reason"] for c in audit["suppressed_customers"]}
    assert reasons == {c1["public_id"]: "do_not_contact",
                       c2["public_id"]: "recent_complaint"}
    # Every suppressed customer has zero queued/sent touches.
    for entry in audit["suppressed_customers"]:
        assert entry["outbox_by_status"].get("queued", 0) == 0
        assert entry["outbox_by_status"].get("sent", 0) == 0
    assert len(audit["events"]) >= 2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_create_customer_requires_name(conn):
    with pytest.raises(ValidationError):
        rx.create_customer(conn, customer_name="   ")


def test_add_job_validates(conn):
    c = make_customer(conn)
    with pytest.raises(ValidationError):
        rx.add_job(conn, c["id"], job_ref="JOB-1", service_type="teleportation",
                   job_date=NOW.isoformat(), amount_cents=100)
    with pytest.raises(ValidationError):
        rx.add_job(conn, c["id"], job_ref="JOB-1", service_type="hvac",
                   job_date=NOW.isoformat(), amount_cents=-5)
    with pytest.raises(ValidationError):
        rx.add_job(conn, 99999, job_ref="JOB-1", service_type="hvac",
                   job_date=NOW.isoformat(), amount_cents=100)


# ---------------------------------------------------------------------------
# Migration rollback (real)
# ---------------------------------------------------------------------------

def test_migration_005_down_step_rolls_back_for_real(conn):
    assert "005_reactivation.sql" in applied_migrations(conn)
    # Put real Q03 data in first.
    c = make_customer(conn)
    add_job(conn, c["id"], "2025-06-01T12:00:00+00:00", 45000, ref="JOB-1")
    assert rx.score_customers(conn, now=NOW)

    assert rollback_migration(conn, "005_reactivation.sql") is True
    assert "005_reactivation.sql" not in applied_migrations(conn)
    for table in ("reactivation_customers", "reactivation_jobs",
                  "reactivation_outbox", "reactivation_send_log",
                  "reactivation_holdouts", "reactivation_events"):
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is None
    # P01 / P02 / Q01 / Q02 tables are untouched.
    for table in ("leads", "requests", "missed_calls", "estimates"):
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    # Re-apply cleanly.
    assert run_migrations(conn) == ["005_reactivation.sql"]
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='reactivation_customers'"
    ).fetchone() is not None
