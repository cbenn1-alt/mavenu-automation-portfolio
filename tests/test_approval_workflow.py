"""State-machine tests: the request lifecycle is enforced in code.

Legal transitions are listed; everything else raises InvalidTransition.
"""
import pytest

from mavenu.workflow import (
    REQUEST_TRANSITIONS,
    REQUEST_WORKFLOW,
    TERMINAL_REQUEST_STATES,
    InvalidTransition,
)


def test_all_expected_states_exist():
    expected = {
        "draft", "submitted", "in_review", "approved", "rejected",
        "changes_requested", "escalated", "fulfilled", "cancelled",
    }
    assert REQUEST_WORKFLOW.states == expected


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        ("draft", "submitted"),
        ("draft", "cancelled"),
        ("submitted", "in_review"),
        ("submitted", "cancelled"),
        ("in_review", "approved"),
        ("in_review", "rejected"),
        ("in_review", "changes_requested"),
        ("in_review", "escalated"),
        ("in_review", "cancelled"),
        ("changes_requested", "submitted"),
        ("changes_requested", "cancelled"),
        ("escalated", "approved"),
        ("escalated", "rejected"),
        ("escalated", "changes_requested"),
        ("escalated", "cancelled"),
        ("approved", "fulfilled"),
    ],
)
def test_legal_transitions_are_permitted(from_state, to_state):
    assert REQUEST_WORKFLOW.can(from_state, to_state)
    REQUEST_WORKFLOW.check(from_state, to_state)  # does not raise


@pytest.mark.parametrize(
    "from_state,to_state",
    [
        ("draft", "in_review"),          # must go through submitted
        ("draft", "approved"),           # no approval without review
        ("submitted", "approved"),       # must go through in_review
        ("in_review", "fulfilled"),      # fulfillment only after approval
        ("in_review", "submitted"),      # backwards is not allowed
        ("changes_requested", "in_review"),  # must resubmit first
        ("approved", "rejected"),        # decided requests cannot be re-decided
        ("approved", "cancelled"),       # approved requests are fulfilled, not cancelled
        ("approved", "in_review"),
        ("escalated", "in_review"),      # escalation resolves by decision, not demotion
        ("rejected", "submitted"),
        ("fulfilled", "cancelled"),
        ("cancelled", "draft"),
    ],
)
def test_illegal_transitions_raise(from_state, to_state):
    assert not REQUEST_WORKFLOW.can(from_state, to_state)
    with pytest.raises(InvalidTransition):
        REQUEST_WORKFLOW.check(from_state, to_state)


def test_terminal_states_have_no_outgoing_transitions():
    assert TERMINAL_REQUEST_STATES == {"rejected", "fulfilled", "cancelled"}
    for state in TERMINAL_REQUEST_STATES:
        assert REQUEST_WORKFLOW.allowed_from(state) == set()


def test_unknown_state_raises():
    with pytest.raises(InvalidTransition):
        REQUEST_WORKFLOW.check("archived", "draft")


def test_transition_table_is_defensive_copy():
    original = dict(REQUEST_TRANSITIONS)
    mutated = {k: set(v) for k, v in REQUEST_TRANSITIONS.items()}
    mutated["draft"].add("approved")
    assert REQUEST_WORKFLOW.can("draft", "approved") is False
    assert original == REQUEST_TRANSITIONS
