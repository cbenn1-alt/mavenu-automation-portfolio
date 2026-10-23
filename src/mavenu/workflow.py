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
