"""Service-level tests: the Project 01 acceptance criteria."""
import pytest

from mavenu import leads as lead_service
from mavenu.leads import FakeBookingAdapter
from mavenu.validation import ValidationError
from mavenu.workflow import InvalidTransition

from .conftest import GOOD_LEAD, LOW_CONFIDENCE_LEAD, OUT_OF_AREA_LEAD


def _submit(conn, payload, **kw):
    return lead_service.submit_lead(conn, dict(payload), **kw)


def _count(conn):
    return conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]


# -- Acceptance: valid submissions create one lead record --------------------
def test_valid_submission_creates_one_booked_lead(conn):
    result = _submit(conn, GOOD_LEAD, idempotency_key="k-1")
    assert result["status"] == 201 and not result["replayed"]
    body = result["body"]
    assert body["public_id"].startswith("LD-")
    assert body["state"] == "booked"
    assert body["booking_ref"].startswith("BK-")
    assert _count(conn) == 1

    lead = lead_service.get_lead(conn, body["public_id"])
    assert lead["classification_label"] == "qualified"
    assert lead["classification_model"] == "deterministic-demo-v1"

    events = lead_service.lead_events(conn, lead["id"])
    types = [e["event_type"] for e in events]
    assert types == ["lead.received", "lead.qualified", "lead.routed", "lead.booked"]
    # every transition records from/to states
    for e in events[1:]:
        assert e["from_state"] and e["to_state"]


# -- Acceptance: invalid submissions are rejected, nothing stored -------------
def test_invalid_submission_rejected_with_no_record(conn):
    bad = dict(GOOD_LEAD, name="", email="bad", phone="")
    with pytest.raises(ValidationError) as ei:
        _submit(conn, bad, idempotency_key="k-bad")
    assert set(ei.value.field_errors) >= {"name", "email"}
    assert _count(conn) == 0


# -- Acceptance: duplicate submissions do not create duplicate records --------
def test_idempotent_retry_returns_original_without_duplicate(conn):
    first = _submit(conn, GOOD_LEAD, idempotency_key="dup-key")
    second = _submit(conn, GOOD_LEAD, idempotency_key="dup-key")
    assert second["replayed"] is True
    assert second["body"]["public_id"] == first["body"]["public_id"]
    assert _count(conn) == 1


def test_same_person_new_key_flags_possible_duplicate(conn):
    _submit(conn, GOOD_LEAD, idempotency_key="k-a")
    result = _submit(conn, GOOD_LEAD, idempotency_key="k-b")  # genuinely new request
    assert _count(conn) == 2
    lead = lead_service.get_lead(conn, result["body"]["public_id"])
    assert lead["possible_duplicate_of"] is not None


# -- Acceptance: uncertain classifier output enters human review --------------
def test_low_confidence_lead_goes_to_needs_review(conn):
    result = _submit(conn, LOW_CONFIDENCE_LEAD, idempotency_key="k-low")
    assert result["body"]["state"] == "needs_review"
    lead = lead_service.get_lead(conn, result["body"]["public_id"])
    assert lead["classification_confidence"] < 0.65
    events = lead_service.lead_events(conn, lead["id"])
    review = [e for e in events if e["event_type"] == "lead.needs_review"]
    assert len(review) == 1
    assert "low_classifier_confidence" in review[0]["detail"]


def test_out_of_area_overrides_qualified_classifier(conn):
    result = _submit(conn, OUT_OF_AREA_LEAD, idempotency_key="k-ooa")
    assert result["body"]["state"] == "needs_review"
    lead = lead_service.get_lead(conn, result["body"]["public_id"])
    assert lead["classification_label"] == "qualified"  # classifier said yes...
    events = lead_service.lead_events(conn, lead["id"])
    review = [e for e in events if e["event_type"] == "lead.needs_review"][0]
    assert "out_of_service_area" in review["detail"]  # ...rules layer said review


# -- Acceptance: failed integrations do not silently lose leads ---------------
def test_booking_failure_preserves_lead_in_review(conn):
    result = _submit(conn, GOOD_LEAD, idempotency_key="k-fail",
                     booking_adapter=FakeBookingAdapter(fail=True))
    assert result["body"]["state"] == "needs_review"
    lead = lead_service.get_lead(conn, result["body"]["public_id"])
    assert lead is not None and lead["booking_ref"] is None
    events = lead_service.lead_events(conn, lead["id"])
    failed = [e for e in events if e["event_type"] == "lead.booking_failed"]
    assert len(failed) == 1
    assert "simulated booking integration failure" in failed[0]["detail"]


# -- Reviewer workflow ----------------------------------------------------------
def test_reviewer_can_rescue_and_route_a_held_lead(conn):
    result = _submit(conn, LOW_CONFIDENCE_LEAD, idempotency_key="k-rescue")
    pid = result["body"]["public_id"]
    lead = lead_service.transition_lead(conn, pid, "qualified", "reviewer:ann")
    assert lead["state"] == "qualified"
    lead = lead_service.transition_lead(conn, pid, "routed", "reviewer:ann")
    assert lead["state"] == "routed"
    events = lead_service.lead_events(conn, lead["id"])
    assert events[-1]["actor"] == "reviewer:ann"


def test_illegal_manual_transition_raises(conn):
    result = _submit(conn, GOOD_LEAD, idempotency_key="k-manual")
    pid = result["body"]["public_id"]  # booked
    with pytest.raises(InvalidTransition):
        lead_service.transition_lead(conn, pid, "qualified", "reviewer:ann")
    with pytest.raises(KeyError):
        lead_service.transition_lead(conn, "LD-999999", "qualified", "reviewer:ann")


# -- Acceptance: dashboard totals reconcile with the database ------------------
def test_stats_reconcile_with_database(conn):
    _submit(conn, GOOD_LEAD, idempotency_key="s-1")            # booked
    _submit(conn, LOW_CONFIDENCE_LEAD, idempotency_key="s-2")  # needs_review
    _submit(conn, OUT_OF_AREA_LEAD, idempotency_key="s-3")     # needs_review
    s = lead_service.stats(conn)
    assert s["total"] == 3 == _count(conn)
    assert sum(s["by_state"].values()) == s["total"]
    assert s["by_state"]["booked"] == 1
    assert s["by_state"]["needs_review"] == 2
