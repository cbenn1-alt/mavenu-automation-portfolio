"""Q02 estimate service tests: validation, CRUD, full lifecycle matrix.

All customer names and data below are synthetic fixtures.
"""
from datetime import datetime, timezone

import pytest

from mavenu import estimates as es
from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.validation import ValidationError
from mavenu.workflow import ESTIMATE_TRANSITIONS, ESTIMATE_WORKFLOW, InvalidTransition

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

GOOD = {
    "customer_name": "Acme Test Co",
    "service_type": "hvac",
    "estimator": "Rosa",
    "amount_cents": 125000,
    "notes": "Second-floor unit replacement.",
}

# Legal walk from draft to every state (decline needs a reason).
_WALK = {
    "draft": [],
    "sent": ["sent"],
    "viewed": ["sent", "viewed"],
    "followed_up": ["sent", "followed_up"],
    "accepted": ["sent", "accepted"],
    "declined": ["sent", "declined"],
    "expired": ["sent", "expired"],
}


def make_estimate(conn, target="draft", now=T0, **overrides):
    payload = dict(GOOD)
    payload.update(overrides)
    e = es.create_estimate(conn, payload, actor="test", now=now)
    for state in _WALK[target]:
        kwargs = {"decline_reason": "price"} if state == "declined" else {}
        es.transition_estimate(conn, e["public_id"], state, "test", now=now, **kwargs)
    return es.get_estimate(conn, e["public_id"])


# -- validation ------------------------------------------------------------------

def test_create_rejects_missing_customer_name(conn):
    with pytest.raises(ValidationError) as exc:
        es.create_estimate(conn, {**GOOD, "customer_name": "  "})
    assert "customer_name" in exc.value.field_errors


def test_create_rejects_unknown_service(conn):
    with pytest.raises(ValidationError) as exc:
        es.create_estimate(conn, {**GOOD, "service_type": "spaceships"})
    assert "service_type" in exc.value.field_errors


def test_create_rejects_non_positive_amount(conn):
    for bad in (0, -500, "lots"):
        with pytest.raises(ValidationError):
            es.create_estimate(conn, {**GOOD, "amount_cents": bad})


def test_create_rejects_oversize_notes(conn):
    with pytest.raises(ValidationError) as exc:
        es.create_estimate(conn, {**GOOD, "notes": "x" * 2001})
    assert "notes" in exc.value.field_errors


def test_create_rejects_missing_estimator(conn):
    with pytest.raises(ValidationError) as exc:
        es.create_estimate(conn, {**GOOD, "estimator": ""})
    assert "estimator" in exc.value.field_errors


# -- create ----------------------------------------------------------------------

def test_create_assigns_sequential_public_id_in_draft(conn):
    e = make_estimate(conn)
    assert e["public_id"] == "EST-000001"
    assert e["state"] == "draft"
    assert e["followup_count"] == 0
    assert e["unsubscribed"] == 0


def test_create_writes_audit_event(conn):
    e = make_estimate(conn)
    events = es.estimate_events(conn, e["id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "estimate.created"
    assert events[0]["actor"] == "test"
    assert events[0]["to_state"] == "draft"


def test_list_estimates_newest_first(conn):
    make_estimate(conn, customer_name="One")
    make_estimate(conn, customer_name="Two")
    rows = es.list_estimates(conn)
    assert [r["customer_name"] for r in rows] == ["Two", "One"]


# -- full transition matrix (7 x 7 = 49 pairs) ------------------------------------

@pytest.mark.parametrize("from_state", sorted(ESTIMATE_TRANSITIONS))
@pytest.mark.parametrize("to_state", sorted(ESTIMATE_TRANSITIONS))
def test_transition_matrix(conn, from_state, to_state):
    e = make_estimate(conn, from_state)
    legal = to_state in ESTIMATE_TRANSITIONS[from_state]
    if legal:
        moved = es.transition_estimate(conn, e["public_id"], to_state, "agent",
                                       decline_reason="timing", now=T0)
        assert moved["state"] == to_state
    else:
        with pytest.raises(InvalidTransition):
            es.transition_estimate(conn, e["public_id"], to_state, "agent",
                                   decline_reason="timing", now=T0)
        # Illegal moves change nothing.
        assert es.get_estimate(conn, e["public_id"])["state"] == from_state


def test_legal_transition_count_matches_spec():
    legal = sum(len(v) for v in ESTIMATE_TRANSITIONS.values())
    assert legal == 15  # 1 + 5 + 4 + 5


def test_terminal_states_have_no_outgoing_moves():
    for state in ("accepted", "declined", "expired"):
        assert ESTIMATE_WORKFLOW.allowed_from(state) == set()


# -- decline reasons ---------------------------------------------------------------

def test_decline_requires_a_reason(conn):
    e = make_estimate(conn, "sent")
    with pytest.raises(ValidationError) as exc:
        es.transition_estimate(conn, e["public_id"], "declined", "agent")
    assert "decline_reason" in exc.value.field_errors
    assert es.get_estimate(conn, e["public_id"])["state"] == "sent"


def test_decline_rejects_unknown_reason(conn):
    e = make_estimate(conn, "sent")
    with pytest.raises(ValidationError):
        es.transition_estimate(conn, e["public_id"], "declined", "agent",
                               decline_reason="aliens")


@pytest.mark.parametrize("reason", es.DECLINE_REASONS)
def test_decline_accepts_every_documented_reason(conn, reason):
    e = make_estimate(conn, "sent")
    moved = es.transition_estimate(conn, e["public_id"], "declined", "agent",
                                   decline_reason=reason, decline_note="n",
                                   now=T0)
    assert moved["state"] == "declined"
    assert moved["decline_reason"] == reason
    assert moved["declined_at"] == T0.isoformat()


# -- timestamp + actor stamps -------------------------------------------------------

def test_state_timestamps_are_stamped(conn):
    e = make_estimate(conn, "sent", now=T0)
    assert es.get_estimate(conn, e["public_id"])["sent_at"] == T0.isoformat()
    moved = es.transition_estimate(conn, e["public_id"], "viewed", "agent:k", now=T0)
    assert moved["viewed_at"] == T0.isoformat()
    events = es.estimate_events(conn, e["id"])
    assert events[-1]["actor"] == "agent:k"
    assert events[-1]["from_state"] == "sent"
    assert events[-1]["to_state"] == "viewed"


def test_transition_unknown_estimate_raises_key_error(conn):
    with pytest.raises(KeyError):
        es.transition_estimate(conn, "EST-999999", "sent", "agent")


# -- unsubscribe (stop rule) ---------------------------------------------------------

def test_set_unsubscribed_flags_and_logs(conn):
    e = make_estimate(conn, "sent")
    out = es.set_unsubscribed(conn, e["public_id"], "agent", now=T0)
    assert out["unsubscribed"] == 1
    events = es.estimate_events(conn, e["id"])
    assert events[-1]["event_type"] == "estimate.unsubscribed"


def test_set_unsubscribed_unknown_estimate_raises(conn):
    with pytest.raises(KeyError):
        es.set_unsubscribed(conn, "EST-999999", "agent")


# -- idempotency ---------------------------------------------------------------------

def test_create_idempotency_key_replays_without_duplicate(conn):
    r1 = es.create_with_idempotency(conn, GOOD, idempotency_key="k1", actor="api", now=T0)
    r2 = es.create_with_idempotency(conn, GOOD, idempotency_key="k1", actor="api", now=T0)
    assert r1["replayed"] is False and r2["replayed"] is True
    assert r2["body"]["public_id"] == r1["body"]["public_id"]
    assert conn.execute("SELECT COUNT(*) c FROM estimates").fetchone()["c"] == 1


# -- migration rollback ----------------------------------------------------------------

def test_migration_004_down_step_rolls_back_for_real(conn):
    assert "004_estimates.sql" in applied_migrations(conn)
    assert rollback_migration(conn, "004_estimates.sql") is True
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    for t in ("estimates", "estimate_events", "cadence_rules", "message_templates",
              "estimate_outbox", "send_log", "estimate_idempotency_keys"):
        assert t not in tables
    assert "004_estimates.sql" not in applied_migrations(conn)
    # P01 / P02 / Q01 tables are untouched.
    for t in ("leads", "requests", "missed_calls"):
        assert t in tables
    # Re-apply works cleanly.
    assert run_migrations(conn) == ["004_estimates.sql"]
    assert conn.execute("SELECT COUNT(*) c FROM cadence_rules").fetchone()["c"] == 3


def test_rollback_unapplied_migration_is_noop(conn):
    rollback_migration(conn, "004_estimates.sql")
    assert rollback_migration(conn, "004_estimates.sql") is False
