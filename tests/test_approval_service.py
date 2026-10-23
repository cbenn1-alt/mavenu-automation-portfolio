"""Service-layer tests: routing, decisions, SLA escalation, audit, dashboard.

The clock is injected (``now=``) so SLA behavior is deterministic.
All names, emails, and amounts below are synthetic fixtures.
"""
from datetime import datetime, timedelta, timezone

import pytest

from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.requests_approval import (
    ApprovalRoleError,
    InvalidDecision,
    approval_chain_for,
    cancel,
    fulfill,
    get_request,
    list_requests,
    record_decision,
    request_events,
    request_stats,
    resubmit,
    submit_for_review,
    submit_request,
    sweep_sla,
)
from mavenu.validation import ValidationError
from mavenu.workflow import InvalidTransition
from .test_request_validation import GOOD_REQUEST

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def _create(conn, **overrides):
    payload = dict(GOOD_REQUEST)
    payload.update(overrides)
    result = submit_request(conn, payload, actor="public-form", now=T0)
    return result["body"]["public_id"]


def _submit(conn, public_id, **kwargs):
    return submit_for_review(conn, public_id, "requester:dana", now=T0, **kwargs)


# -- intake -------------------------------------------------------------------

def test_submit_request_creates_draft(conn):
    public_id = _create(conn)
    request = get_request(conn, public_id)
    assert public_id.startswith("RQ-")
    assert request["state"] == "draft"
    assert request["amount_cents"] == 245000


def test_submit_request_rejects_invalid_payload_with_no_record(conn):
    with pytest.raises(ValidationError):
        submit_request(conn, {"title": ""}, now=T0)
    assert conn.execute("SELECT COUNT(*) AS c FROM requests").fetchone()["c"] == 0


def test_idempotency_key_replays_without_duplicate(conn):
    payload = dict(GOOD_REQUEST)
    first = submit_request(conn, payload, idempotency_key="key-1", now=T0)
    second = submit_request(conn, payload, idempotency_key="key-1", now=T0)
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["body"] == first["body"]
    assert second["status"] == 201
    assert conn.execute("SELECT COUNT(*) AS c FROM requests").fetchone()["c"] == 1


# -- approval chain routing ----------------------------------------------------

def test_chain_is_manager_only_below_threshold():
    assert approval_chain_for(99_999, 100_000) == ["manager"]


def test_chain_adds_finance_above_threshold():
    assert approval_chain_for(100_001, 100_000) == ["manager", "finance"]


def test_chain_threshold_boundary_is_exclusive():
    assert approval_chain_for(100_000, 100_000) == ["manager"]


def test_submit_for_review_builds_chain_and_arms_sla(conn):
    public_id = _create(conn)  # $2,450 > $1,000 -> manager + finance
    request = _submit(conn, public_id, sla_hours=48)
    assert request["state"] == "in_review"
    assert request["current_step"] == 0
    expected_due = (T0 + timedelta(hours=48)).isoformat(timespec="seconds")
    assert request["sla_due_at"] == expected_due


def test_submit_for_review_below_threshold_has_single_step(conn):
    public_id = _create(conn, request_type="access", amount="")
    request = _submit(conn, public_id)
    import json

    assert json.loads(request["approval_chain"]) == ["manager"]


# -- decisions ------------------------------------------------------------------

def test_manager_approves_first_step_then_finance_final(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    step1 = record_decision(
        conn, public_id, decision="approve", role="manager",
        actor="reviewer:mara", now=T0 + timedelta(minutes=5),
    )
    assert step1["state"] == "in_review"  # still waiting: finance is next
    assert step1["current_step"] == 1
    final = record_decision(
        conn, public_id, decision="approve", role="finance",
        actor="reviewer:omar", now=T0 + timedelta(minutes=10),
    )
    assert final["state"] == "approved"
    assert final["decided_by"] == "reviewer:omar"
    assert final["decided_at"] is not None


def test_single_step_request_approves_immediately(conn):
    public_id = _create(conn, request_type="access", amount="")
    _submit(conn, public_id)
    final = record_decision(
        conn, public_id, decision="approve", role="manager",
        actor="reviewer:mara", now=T0,
    )
    assert final["state"] == "approved"


def test_wrong_role_cannot_decide(conn):
    public_id = _create(conn)  # step 0 belongs to manager
    _submit(conn, public_id)
    with pytest.raises(ApprovalRoleError):
        record_decision(
            conn, public_id, decision="approve", role="finance",
            actor="reviewer:omar", now=T0,
        )
    # The failed attempt changed nothing.
    assert get_request(conn, public_id)["state"] == "in_review"
    assert get_request(conn, public_id)["current_step"] == 0


def test_reject_terminates_request(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    rejected = record_decision(
        conn, public_id, decision="reject", role="manager",
        actor="reviewer:mara", now=T0,
    )
    assert rejected["state"] == "rejected"
    assert rejected["decided_by"] == "reviewer:mara"


def test_request_changes_returns_to_requester(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    sent_back = record_decision(
        conn, public_id, decision="request_changes", role="manager",
        actor="reviewer:mara", now=T0,
    )
    assert sent_back["state"] == "changes_requested"


def test_resubmit_reroutes_with_fresh_sla(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    record_decision(
        conn, public_id, decision="request_changes", role="manager",
        actor="reviewer:mara", now=T0,
    )
    rerouted = resubmit(
        conn, public_id, "requester:dana", now=T0 + timedelta(hours=2), sla_hours=48
    )
    assert rerouted["state"] == "in_review"
    assert rerouted["current_step"] == 0
    expected_due = (T0 + timedelta(hours=50)).isoformat(timespec="seconds")
    assert rerouted["sla_due_at"] == expected_due


def test_decision_in_wrong_state_rejected(conn):
    public_id = _create(conn)  # still draft
    with pytest.raises(InvalidDecision):
        record_decision(
            conn, public_id, decision="approve", role="manager",
            actor="reviewer:mara", now=T0,
        )


def test_decision_on_unknown_request_raises_key_error(conn):
    with pytest.raises(KeyError):
        record_decision(
            conn, "RQ-999999", decision="approve", role="manager",
            actor="reviewer:mara", now=T0,
        )


def test_unknown_decision_value_rejected(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    with pytest.raises(InvalidDecision):
        record_decision(
            conn, public_id, decision="maybe", role="manager",
            actor="reviewer:mara", now=T0,
        )


# -- fulfill / cancel ------------------------------------------------------------

def test_fulfill_after_approval(conn):
    public_id = _create(conn, request_type="access", amount="")
    _submit(conn, public_id)
    record_decision(
        conn, public_id, decision="approve", role="manager",
        actor="reviewer:mara", now=T0,
    )
    done = fulfill(conn, public_id, "ops:lee", now=T0)
    assert done["state"] == "fulfilled"


def test_fulfill_before_approval_is_illegal(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    with pytest.raises(InvalidTransition):
        fulfill(conn, public_id, "ops:lee", now=T0)


def test_cancel_from_in_review(conn):
    public_id = _create(conn)
    _submit(conn, public_id)
    cancelled = cancel(conn, public_id, "requester:dana", now=T0)
    assert cancelled["state"] == "cancelled"


def test_cancel_after_decision_is_rejected(conn):
    public_id = _create(conn, request_type="access", amount="")
    _submit(conn, public_id)
    record_decision(
        conn, public_id, decision="approve", role="manager",
        actor="reviewer:mara", now=T0,
    )
    with pytest.raises(InvalidDecision):
        cancel(conn, public_id, "requester:dana", now=T0)


# -- SLA escalation (deterministic clock) ------------------------------------------

def test_sla_breach_escalates_to_director(conn):
    public_id = _create(conn)
    _submit(conn, public_id, sla_hours=1)
    escalated = sweep_sla(conn, now=T0 + timedelta(hours=2), sla_hours=48)
    assert len(escalated) == 1
    request = escalated[0]
    assert request["public_id"] == public_id
    assert request["state"] == "escalated"
    import json

    assert json.loads(request["approval_chain"]) == ["director"]
    assert request["current_step"] == 0
    expected_due = (T0 + timedelta(hours=50)).isoformat(timespec="seconds")
    assert request["sla_due_at"] == expected_due


def test_sweep_leaves_unbreached_requests_alone(conn):
    fresh = _create(conn, title="Fresh request with plenty of time")
    _submit(conn, fresh, sla_hours=48)
    stale = _create(conn, title="Stale request about to breach")
    _submit(conn, stale, sla_hours=1)
    escalated = sweep_sla(conn, now=T0 + timedelta(hours=2))
    assert [r["public_id"] for r in escalated] == [stale]
    assert get_request(conn, fresh)["state"] == "in_review"


def test_sweep_is_idempotent_for_already_escalated(conn):
    public_id = _create(conn)
    _submit(conn, public_id, sla_hours=1)
    sweep_sla(conn, now=T0 + timedelta(hours=2))
    again = sweep_sla(conn, now=T0 + timedelta(hours=200))
    assert again == []
    assert get_request(conn, public_id)["state"] == "escalated"


def test_director_can_decide_escalated_request(conn):
    public_id = _create(conn)
    _submit(conn, public_id, sla_hours=1)
    sweep_sla(conn, now=T0 + timedelta(hours=2))
    decided = record_decision(
        conn, public_id, decision="approve", role="director",
        actor="reviewer:pat", now=T0 + timedelta(hours=3),
    )
    assert decided["state"] == "approved"
    assert decided["decided_by"] == "reviewer:pat"


def test_manager_cannot_decide_after_escalation(conn):
    public_id = _create(conn)
    _submit(conn, public_id, sla_hours=1)
    sweep_sla(conn, now=T0 + timedelta(hours=2))
    with pytest.raises(ApprovalRoleError):
        record_decision(
            conn, public_id, decision="approve", role="manager",
            actor="reviewer:mara", now=T0 + timedelta(hours=3),
        )


# -- audit trail ---------------------------------------------------------------------

def test_every_transition_is_actor_stamped(conn):
    public_id = _create(conn, request_type="access", amount="")
    _submit(conn, public_id)
    record_decision(
        conn, public_id, decision="approve", role="manager",
        actor="reviewer:mara", now=T0,
    )
    fulfill(conn, public_id, "ops:lee", now=T0)
    request = get_request(conn, public_id)
    events = request_events(conn, request["id"])
    event_types = [e["event_type"] for e in events]
    assert event_types == [
        "request.created",
        "request.submitted",
        "request.routed",
        "approval.recorded",
        "request.fulfilled",
    ]
    assert all(e["actor"] for e in events)
    assert all(e["created_at"] for e in events)
    # State linkage is consistent across the timeline.
    states = [(e["from_state"], e["to_state"]) for e in events if e["from_state"] or e["to_state"]]
    assert states[1] == ("draft", "submitted")
    assert states[2] == ("submitted", "in_review")
    assert states[3] == ("in_review", "approved")
    assert states[4] == ("approved", "fulfilled")
    # Roles are recorded on approval events.
    assert events[3]["role"] == "manager"


def test_escalation_is_in_the_audit_trail(conn):
    public_id = _create(conn)
    _submit(conn, public_id, sla_hours=1)
    sweep_sla(conn, now=T0 + timedelta(hours=2))
    request = get_request(conn, public_id)
    events = request_events(conn, request["id"])
    escalations = [e for e in events if e["event_type"] == "request.escalated"]
    assert len(escalations) == 1
    assert escalations[0]["actor"] == "system"
    assert escalations[0]["from_state"] == "in_review"
    assert escalations[0]["to_state"] == "escalated"


# -- dashboard reconciliation ----------------------------------------------------------

def test_dashboard_stats_reconcile_with_source_rows(conn):
    # Six requests across states and types.
    p1 = _create(conn, request_type="access", amount="")
    _submit(conn, p1)
    record_decision(conn, p1, decision="approve", role="manager",
                    actor="reviewer:mara", now=T0)
    fulfill(conn, p1, "ops:lee", now=T0)

    p2 = _create(conn, title="Second request")
    _submit(conn, p2)
    record_decision(conn, p2, decision="reject", role="manager",
                    actor="reviewer:mara", now=T0)

    p3 = _create(conn, title="Third request")
    _submit(conn, p3)  # stays in_review

    p4 = _create(conn, title="Fourth request")
    _submit(conn, p4)
    record_decision(conn, p4, decision="request_changes", role="manager",
                    actor="reviewer:mara", now=T0)

    p5 = _create(conn, title="Fifth request")  # stays draft

    p6 = _create(conn, title="Sixth request")
    cancel(conn, p6, "requester:dana", now=T0)

    stats = request_stats(conn, now=T0)
    assert stats["total"] == 6
    assert sum(stats["by_state"].values()) == stats["total"]
    assert sum(stats["by_type"].values()) == stats["total"]

    # Independent re-computation with raw SQL — no shared code path.
    total = conn.execute("SELECT COUNT(*) AS c FROM requests").fetchone()["c"]
    by_state = {
        r["state"]: r["c"]
        for r in conn.execute("SELECT state, COUNT(*) AS c FROM requests GROUP BY state")
    }
    assert total == stats["total"] == 6
    assert by_state == stats["by_state"]
    assert stats["by_state"] == {
        "fulfilled": 1, "rejected": 1, "in_review": 1,
        "changes_requested": 1, "draft": 1, "cancelled": 1,
    }
    assert stats["escalated"] == 0
    assert stats["sla_breached"] == 0


def test_sla_breached_count_reflects_fake_clock(conn):
    public_id = _create(conn)
    _submit(conn, public_id, sla_hours=1)
    assert request_stats(conn, now=T0)["sla_breached"] == 0
    assert request_stats(conn, now=T0 + timedelta(hours=2))["sla_breached"] == 1
    sweep_sla(conn, now=T0 + timedelta(hours=2))
    after = request_stats(conn, now=T0 + timedelta(hours=2))
    assert after["sla_breached"] == 0
    assert after["escalated"] == 1


# -- migration rollback ------------------------------------------------------------------

def test_migration_down_step_rolls_back_002(tmp_path):
    """The 002 rollback procedure, run for real: apply, use, roll back, re-apply."""
    from mavenu.db import get_connection

    db_path = str(tmp_path / "rollback.db")
    conn = get_connection(db_path)
    applied = run_migrations(conn)
    assert "002_approvals.sql" in applied

    # The schema is live: create a request through the service layer.
    public_id = _create(conn)
    assert get_request(conn, public_id) is not None

    # Roll back: down-step drops the P02 tables and removes the record.
    assert rollback_migration(conn, "002_approvals.sql") is True
    remaining = {
        r["name"] for r in
        conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "requests" not in remaining
    assert "request_events" not in remaining
    assert "request_idempotency_keys" not in remaining
    assert "002_approvals.sql" not in applied_migrations(conn)
    # Project 01 tables are untouched by the rollback.
    assert "leads" in remaining
    assert "001_core.sql" in applied_migrations(conn)

    # Re-applying restores the schema; the engine works again.
    assert run_migrations(conn) == ["002_approvals.sql"]
    public_id2 = _create(conn)
    assert get_request(conn, public_id2) is not None
    conn.close()


def test_rollback_of_unapplied_migration_is_noop(conn):
    assert rollback_migration(conn, "002_approvals.sql") is True  # applied via fixture
    assert rollback_migration(conn, "002_approvals.sql") is False


def test_rollback_without_down_step_raises(conn):
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        rollback_migration(conn, "001_core.sql")  # 001 ships no down-step
