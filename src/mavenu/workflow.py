"""Explicit workflow state machines.

Permitted transitions are defined in code, in one place. Any attempt to move
a record through a transition that is not listed raises InvalidTransition —
there is no silent or ad-hoc state change anywhere in the system.
"""
from __future__ import annotations


class InvalidTransition(Exception):
    """Raised when a requested state transition is not permitted."""


class Workflow:
    def __init__(self, transitions: dict[str, set[str]]):
        # Defensive copy so callers cannot mutate the machine after creation.
        self._transitions = {k: set(v) for k, v in transitions.items()}

    @property
    def states(self) -> set[str]:
        states = set(self._transitions)
        for targets in self._transitions.values():
            states |= targets
        return states

    def can(self, from_state: str, to_state: str) -> bool:
        return to_state in self._transitions.get(from_state, set())

    def allowed_from(self, from_state: str) -> set[str]:
        return set(self._transitions.get(from_state, set()))

    def check(self, from_state: str, to_state: str) -> None:
        if from_state not in self._transitions:
            raise InvalidTransition(f"Unknown state {from_state!r}.")
        if not self.can(from_state, to_state):
            raise InvalidTransition(
                f"Transition {from_state!r} -> {to_state!r} is not permitted."
            )


# Project 01 — lead lifecycle.
#   received: intake accepted, not yet evaluated
#   qualified: passed rules + classifier, ready to route
#   routed: assigned to a territory/crew queue
#   booked: appointment created via the booking integration
#   needs_review: held for a human (low confidence, out of area, integration failure)
#   rejected: spam/invalid on human review (terminal)
#   cancelled: withdrawn after booking (terminal)
LEAD_TRANSITIONS: dict[str, set[str]] = {
    "received": {"qualified", "needs_review", "rejected"},
    "qualified": {"routed", "needs_review", "rejected"},
    "routed": {"booked", "needs_review", "cancelled"},
    "booked": {"cancelled"},
    "needs_review": {"qualified", "rejected", "routed"},
    "rejected": set(),
    "cancelled": set(),
}

LEAD_WORKFLOW = Workflow(LEAD_TRANSITIONS)
TERMINAL_LEAD_STATES = {"rejected", "cancelled"}


# Project 02 — enterprise request & approval lifecycle.
#   draft:             intake accepted, not yet submitted
#   submitted:         requester submitted; awaiting routing
#   in_review:         waiting on the approver for approval_chain[current_step]
#   changes_requested: an approver sent it back; requester may resubmit or cancel
#   escalated:         SLA breach; rerouted to the director role
#   approved:          all approval steps complete; awaiting fulfillment
#   rejected:          an approver rejected (terminal)
#   fulfilled:         work completed / goods received (terminal)
#   cancelled:         withdrawn by requester or cancelled mid-flight (terminal)
REQUEST_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"in_review", "cancelled"},
    "in_review": {"approved", "rejected", "changes_requested", "escalated", "cancelled"},
    "changes_requested": {"submitted", "cancelled"},
    "escalated": {"approved", "rejected", "changes_requested", "cancelled"},
    "approved": {"fulfilled"},
    "rejected": set(),
    "fulfilled": set(),
    "cancelled": set(),
}

REQUEST_WORKFLOW = Workflow(REQUEST_TRANSITIONS)
TERMINAL_REQUEST_STATES = {"rejected", "fulfilled", "cancelled"}


# Project Q01 — missed-call callback lifecycle.
#   pending:    call recorded, awaiting a callback attempt
#   attempted:  someone tried calling back (first attempt stamped)
#   connected:  reached the caller (a human picked up)
#   booked:     callback converted to a booked job (terminal)
#   lost:       caller unreachable / went elsewhere / admin close (terminal)
CALL_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"attempted", "lost"},
    "attempted": {"connected", "lost"},
    "connected": {"booked", "lost"},
    "booked": set(),
    "lost": set(),
}

CALL_WORKFLOW = Workflow(CALL_TRANSITIONS)
TERMINAL_CALL_STATES = {"booked", "lost"}


# Project Q02 — estimate follow-up lifecycle.
#   draft:       created, not yet sent to the customer
#   sent:        estimate sent; awaiting a view or a follow-up
#   viewed:      customer opened the estimate (tracking event)
#   followed_up: at least one scheduled follow-up was queued
#   accepted:    customer accepted (terminal)
#   declined:    customer declined with a captured reason (terminal)
#   expired:    aged out past the expiry window (terminal)
ESTIMATE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent"},
    "sent": {"viewed", "followed_up", "accepted", "declined", "expired"},
    "viewed": {"followed_up", "accepted", "declined", "expired"},
    "followed_up": {"followed_up", "viewed", "accepted", "declined", "expired"},
    "accepted": set(),
    "declined": set(),
    "expired": set(),
}

ESTIMATE_WORKFLOW = Workflow(ESTIMATE_TRANSITIONS)
TERMINAL_ESTIMATE_STATES = {"accepted", "declined", "expired"}
# Estimates still eligible for scheduled follow-ups.
OPEN_ESTIMATE_STATES = {"sent", "viewed", "followed_up"}


# Project Q05 — reconciliation exception lifecycle.
#   open:          raised by the matcher/ingest; not yet worked
#   investigating: a human is working it (actor-stamped)
#   resolved:      fixed by a human (terminal)
#   written_off:   accepted loss, requires human authorization (terminal)
# The system proposes; it never posts a write-off itself.
EXCEPTION_TRANSITIONS: dict[str, set[str]] = {
    "open": {"investigating"},
    "investigating": {"resolved", "written_off"},
    "resolved": set(),
    "written_off": set(),
}

EXCEPTION_WORKFLOW = Workflow(EXCEPTION_TRANSITIONS)
TERMINAL_EXCEPTION_STATES = {"resolved", "written_off"}
