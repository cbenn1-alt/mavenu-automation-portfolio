"""Q02 cadence scheduler tests: due computation, stop rules, idempotency,
expiry sweep, outbox flushing, rule configuration.

Clock: T0 = 2026-10-23T12:00:00Z is passed explicitly everywhere time
matters, so assertions are equality checks, not ranges. All fixture data
is synthetic.
"""
from datetime import datetime, timedelta, timezone

import pytest

from mavenu import cadence as ca
from mavenu import estimates as es
from mavenu import templates as tp
from mavenu.validation import ValidationError

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def sent_estimate(conn, days_ago, **overrides):
    """An estimate sent exactly ``days_ago`` before T0 (frozen clock)."""
    payload = {
        "customer_name": "Acme Test Co",
        "service_type": "hvac",
        "estimator": "Rosa",
        "amount_cents": 125000,
    }
    payload.update(overrides)
    sent_at = T0 - timedelta(days=days_ago)
    e = es.create_estimate(conn, payload, actor="test", now=sent_at)
    return es.transition_estimate(conn, e["public_id"], "sent", "test", now=sent_at)


# -- rule configuration ------------------------------------------------------------

def test_default_rules_seeded(conn):
    rules = ca.list_rules(conn)
    assert [(r["step_index"], r["days_after_sent"], r["template_name"]) for r in rules] == [
        (1, 2.0, "followup_step1"),
        (2, 7.0, "followup_step2"),
        (3, 14.0, "followup_step3"),
    ]


def test_replace_rules_rejects_gapped_steps(conn):
    with pytest.raises(ValidationError) as exc:
        ca.replace_rules(conn, [
            {"step_index": 1, "days_after_sent": 1, "template_name": "followup_step1"},
            {"step_index": 3, "days_after_sent": 5, "template_name": "followup_step2"},
        ])
    assert "rules" in exc.value.field_errors


def test_replace_rules_rejects_unknown_template(conn):
    with pytest.raises(ValidationError) as exc:
        ca.replace_rules(conn, [
            {"step_index": 1, "days_after_sent": 1, "template_name": "nope"},
        ])
    assert "rules[0].template_name" in exc.value.field_errors


def test_replace_rules_applies_atomically(conn):
    rules = ca.replace_rules(conn, [
        {"step_index": 1, "days_after_sent": 1, "template_name": "followup_step2"},
        {"step_index": 2, "days_after_sent": 3, "template_name": "followup_step1"},
    ], actor="test", now=T0)
    assert [r["template_name"] for r in rules] == ["followup_step2", "followup_step1"]
    # Old rule rows are deactivated, not deleted (history preserved).
    assert conn.execute("SELECT COUNT(*) c FROM cadence_rules").fetchone()["c"] == 5


# -- due computation (frozen clock) ---------------------------------------------------

def test_only_due_steps_are_queued(conn):
    e = sent_estimate(conn, days_ago=10)  # steps 1 (day 2) and 2 (day 7) due
    result = ca.run_cadence(conn, now=T0)
    assert sorted(q["step_index"] for q in result["queued"]) == [1, 2]
    assert result["skipped"] == []
    moved = es.get_estimate(conn, e["public_id"])
    assert moved["state"] == "followed_up"
    assert moved["followup_count"] == 2
    assert moved["last_followup_at"] == T0.isoformat()


def test_nothing_due_for_fresh_estimate(conn):
    sent_estimate(conn, days_ago=1)
    result = ca.run_cadence(conn, now=T0)
    assert result["queued"] == []


def test_boundary_step_becomes_due_exactly_on_its_day(conn):
    sent_estimate(conn, days_ago=2)
    result = ca.run_cadence(conn, now=T0)
    assert [q["step_index"] for q in result["queued"]] == [1]


def test_outbox_row_carries_rendered_template_and_idempotency_key(conn):
    e = sent_estimate(conn, days_ago=3)
    ca.run_cadence(conn, now=T0)
    rows = ca.outbox(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["idempotency_key"] == f"est:{e['id']}:step:1"
    assert row["template_name"] == "followup_step1"
    assert row["template_version"] == 1
    assert row["status"] == "queued"
    assert "EST-" in row["subject"] and "$1,250.00" in row["body"]
    assert row["recipient_label"] == f"synthetic-customer:{e['public_id']}"


def test_followup_queued_event_is_actor_stamped(conn):
    e = sent_estimate(conn, days_ago=3)
    ca.run_cadence(conn, now=T0)
    events = es.estimate_events(conn, e["id"])
    queued = [ev for ev in events if ev["event_type"] == "estimate.followup_queued"]
    assert len(queued) == 1
    assert queued[0]["from_state"] == "sent"
    assert queued[0]["to_state"] == "followed_up"
    assert queued[0]["created_at"] == T0.isoformat()


# -- idempotency: scheduler replays ----------------------------------------------------

def test_scheduler_run_twice_queues_each_step_once(conn):
    sent_estimate(conn, days_ago=20)  # all three steps due
    first = ca.run_cadence(conn, now=T0)
    second = ca.run_cadence(conn, now=T0)
    assert len(first["queued"]) == 3
    assert second["queued"] == []
    assert conn.execute("SELECT COUNT(*) c FROM estimate_outbox").fetchone()["c"] == 3


def test_1000_scheduler_replays_produce_zero_duplicates(conn):
    sent_estimate(conn, days_ago=20)
    ca.run_cadence(conn, now=T0)
    for _ in range(1000):
        result = ca.run_cadence(conn, now=T0)
        assert result["queued"] == []
    rows = conn.execute("SELECT idempotency_key FROM estimate_outbox").fetchall()
    keys = [r["idempotency_key"] for r in rows]
    assert len(keys) == 3
    assert len(set(keys)) == 3  # UNIQUE constraint held across 1001 runs


# -- stop rules --------------------------------------------------------------------------

@pytest.mark.parametrize("terminal", ["accepted", "declined", "expired"])
def test_terminal_estimates_are_never_queued(conn, terminal):
    e = sent_estimate(conn, days_ago=20)
    kwargs = {"decline_reason": "price"} if terminal == "declined" else {}
    es.transition_estimate(conn, e["public_id"], terminal, "test", now=T0, **kwargs)
    result = ca.run_cadence(conn, now=T0)
    assert result["queued"] == []


def test_unsubscribed_estimate_is_never_queued(conn):
    e = sent_estimate(conn, days_ago=20)
    es.set_unsubscribed(conn, e["public_id"], "test", now=T0)
    result = ca.run_cadence(conn, now=T0)
    assert result["queued"] == []


def test_draft_estimate_is_never_queued(conn):
    es.create_estimate(conn, {"customer_name": "Acme Test Co", "service_type": "hvac",
                              "estimator": "Rosa", "amount_cents": 500}, now=T0)
    result = ca.run_cadence(conn, now=T0)
    assert result["queued"] == []


# -- failure analysis ----------------------------------------------------------------------

def test_broken_template_skips_fail_closed_with_event(conn):
    tp.create_template(conn, "broken_step", "Hi {{customer_name}}",
                       "Owes {{mystery_variable}}.", now=T0)
    ca.replace_rules(conn, [
        {"step_index": 1, "days_after_sent": 0, "template_name": "broken_step"},
    ], now=T0)
    e = sent_estimate(conn, days_ago=5)
    result = ca.run_cadence(conn, now=T0)
    assert result["queued"] == []
    assert len(result["skipped"]) == 1
    assert "mystery_variable" in result["skipped"][0]["reason"]
    assert es.get_estimate(conn, e["public_id"])["state"] == "sent"  # unchanged
    events = es.estimate_events(conn, e["id"])
    assert events[-1]["event_type"] == "estimate.followup_skipped"


def test_cadence_is_timezone_independent(conn):
    """Same elapsed time, different absolute wall clocks (across a US DST
    change) -> identical due steps. All computation is in UTC."""
    spring_forward = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)  # DST day
    sent_at_1 = spring_forward - timedelta(days=10)
    e = es.create_estimate(conn, {
        "customer_name": "Acme Test Co", "service_type": "hvac",
        "estimator": "Rosa", "amount_cents": 125000}, actor="test", now=sent_at_1)
    e = es.transition_estimate(conn, e["public_id"], "sent", "test", now=sent_at_1)
    r1 = ca.run_cadence(conn, now=spring_forward)
    steps1 = sorted(q["step_index"] for q in r1["queued"])
    assert steps1 == [1, 2]
    # Same 10-day elapsed age, different wall clock -> same due steps.
    sent_at_2 = T0 - timedelta(days=10)
    conn.execute("DELETE FROM estimate_outbox")
    conn.execute(
        "UPDATE estimates SET state = 'sent', followup_count = 0, sent_at = ?, "
        "updated_at = ? WHERE id = ?",
        (sent_at_2.isoformat(), T0.isoformat(), e["id"]),
    )
    conn.commit()
    r2 = ca.run_cadence(conn, now=T0)
    assert sorted(q["step_index"] for q in r2["queued"]) == steps1


# -- expiry sweep ------------------------------------------------------------------------------

def test_sweep_expired_moves_only_aging_open_estimates(conn):
    old = sent_estimate(conn, days_ago=40)
    fresh = sent_estimate(conn, days_ago=10)
    done = sent_estimate(conn, days_ago=40)
    es.transition_estimate(conn, done["public_id"], "accepted", "test", now=T0)
    expired = ca.sweep_expired(conn, now=T0, expiry_days=30)
    assert [e["public_id"] for e in expired] == [old["public_id"]]
    assert es.get_estimate(conn, old["public_id"])["state"] == "expired"
    assert es.get_estimate(conn, old["public_id"])["expired_at"] == T0.isoformat()
    assert es.get_estimate(conn, fresh["public_id"])["state"] == "sent"
    # Idempotent: a second sweep moves nothing.
    assert ca.sweep_expired(conn, now=T0, expiry_days=30) == []


# -- outbox flushing (stub adapter) ------------------------------------------------------------------

def test_flush_sends_through_stub_adapter_and_logs(conn):
    sent_estimate(conn, days_ago=20)
    ca.run_cadence(conn, now=T0)
    flushed = ca.flush_outbox(conn, now=T0)
    assert len(flushed) == 3
    assert all(f["adapter"] == "stub" and f["status"] == "stub-logged" for f in flushed)
    assert all(r["status"] == "sent" for r in ca.outbox(conn))
    log = ca.send_log(conn)
    assert len(log) == 3
    assert {r["outbox_id"] for r in log} == {1, 2, 3}
    # Flushing again is a no-op: no double send-log rows.
    assert ca.flush_outbox(conn, now=T0) == []
    assert conn.execute("SELECT COUNT(*) c FROM send_log").fetchone()["c"] == 3


def test_flush_with_empty_outbox_is_noop(conn):
    assert ca.flush_outbox(conn, now=T0) == []
