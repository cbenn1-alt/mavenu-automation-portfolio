"""Unit tests: workflow state machine."""
import pytest

from mavenu.workflow import (
    LEAD_WORKFLOW,
    TERMINAL_LEAD_STATES,
    InvalidTransition,
    Workflow,
)


def test_happy_path_transitions_allowed():
    for a, b in [
        ("received", "qualified"),
        ("qualified", "routed"),
        ("routed", "booked"),
        ("received", "needs_review"),
        ("needs_review", "qualified"),
        ("needs_review", "rejected"),
        ("booked", "cancelled"),
    ]:
        assert LEAD_WORKFLOW.can(a, b), f"{a} -> {b} should be allowed"


def test_illegal_transitions_rejected():
    for a, b in [
        ("received", "booked"),      # skipping qualification
        ("received", "routed"),
        ("booked", "qualified"),     # backwards
        ("qualified", "booked"),     # skipping routing
        ("rejected", "qualified"),   # terminal
        ("cancelled", "booked"),     # terminal
        ("booked", "needs_review"),  # not listed
    ]:
        assert not LEAD_WORKFLOW.can(a, b), f"{a} -> {b} should be rejected"
        with pytest.raises(InvalidTransition):
            LEAD_WORKFLOW.check(a, b)


def test_unknown_state_rejected():
    with pytest.raises(InvalidTransition):
        LEAD_WORKFLOW.check("mystery", "qualified")


def test_terminal_states_have_no_outgoing():
    for state in TERMINAL_LEAD_STATES:
        assert LEAD_WORKFLOW.allowed_from(state) == set()


def test_states_cover_expected_lifecycle():
    assert LEAD_WORKFLOW.states == {
        "received", "qualified", "routed", "booked",
        "needs_review", "rejected", "cancelled",
    }


def test_workflow_is_defensively_copied():
    transitions = {"a": {"b"}}
    wf = Workflow(transitions)
    transitions["a"].add("zzz")
    assert not wf.can("a", "zzz")
