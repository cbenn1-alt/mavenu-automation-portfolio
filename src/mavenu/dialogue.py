"""Project Q04 — Conversational Booking Agent: dialogue layer.

Two pieces live here:

1. ``DialoguePolicy`` — a replaceable protocol for interpreting a caller
   turn (the same seam pattern as P01's ``LeadClassifier`` and Q01's
   ``UrgencyScorer``). The bundled ``ScriptedDemoPolicy`` is deterministic,
   rule-driven, and honestly labeled: v1 is NOT a language-model
   integration. It never generates free text beyond fixed templates and it
   never invents availability — availability text comes only from the
   ``BookingAdapter`` at confirm time.

2. ``DialogueManager`` — a finite-state dialogue manager implementing the
   slot-filling flow::

       greeting -> service -> location -> window -> contact -> confirm
                                                              -> booked
                                                              | handoff

   Every state transition is recorded in the turn decision log. The
   manager enforces three hard safety rules:
     * below-confidence-threshold turns -> handoff (never guessed at);
     * max-turn cap -> handoff (no infinite loops; the cap leaves headroom
       for the in-flight caller turn plus the agent's handoff reply, so the
       logged total can never exceed MAX_TURNS);
     * injection-style input -> handoff (never obeyed).

Confidence heuristics (deterministic, documented — the policy's contract):

    slot           signal                                    confidence
    -------------  ----------------------------------------  ----------
    service        whole-word service keyword or synonym     1.0
    location       5-digit ZIP (any; synthetic demo)         1.0
    window         ISO date (YYYY-MM-DD)                     1.0
    window         "today" / "tomorrow"                      0.9
    window         day-name + day-part ("tuesday morning")   0.9
    window         day-name only OR day-part only            0.8
    contact_name   letters-only, >= 2 chars, not a command   0.85
    contact_phone  10 digits (US-style)                      0.95
    contact_phone  7-9 digits                                0.7
    confirm        yes-word / no-word                        1.0
    (anything)     no recognizable signal for the state      0.0

Turn confidence = the minimum confidence over the slots claimed on that
turn. CONFIDENCE_THRESHOLD = 0.55: any turn below it routes to handoff.
Injection patterns (documented below) force confidence 0.0 and handoff
with reason 'suspicious_input'; they are never acted on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

# ---------------------------------------------------------------------------
# Confidence threshold and turn cap — the two hard safety rails.
# ---------------------------------------------------------------------------

#: Any caller turn scoring below this routes to a human handoff.
CONFIDENCE_THRESHOLD = 0.55

#: Total agent + caller turns allowed per conversation; reaching the cap
#: hands off instead of continuing. The cap is enforced *before* a caller
#: turn is processed with three turns of headroom (the caller turn already
#: accepted plus the agent's handoff reply, plus one spare), so the logged
#: total can never exceed MAX_TURNS.
#:
#: Sized so the full happy path fits with margin: greeting (1) + five
#: slot-filling exchanges (10) + confirm exchange (2) = 13 turns; the cap
#: hands off on the 7th caller turn at the latest.
MAX_TURNS = 16

# ---------------------------------------------------------------------------
# Dialogue states.
# ---------------------------------------------------------------------------

GREETING = "greeting"
SERVICE = "service"
LOCATION = "location"
WINDOW = "window"
CONTACT = "contact"
CONFIRM = "confirm"
BOOKED = "booked"
HANDOFF = "handoff"

STATES = (GREETING, SERVICE, LOCATION, WINDOW, CONTACT, CONFIRM, BOOKED, HANDOFF)
TERMINAL_STATES = (BOOKED, HANDOFF)

# The slot each non-terminal waiting state is trying to fill.
STATE_SLOT = {
    SERVICE: "service",
    LOCATION: "location",
    WINDOW: "window",
    CONTACT: "contact_name",  # contact_phone fills opportunistically too
}

# Next waiting state once a slot is filled (confirm is entered directly).
NEXT_STATE = {
    SERVICE: LOCATION,
    LOCATION: WINDOW,
    WINDOW: CONTACT,
}

# ---------------------------------------------------------------------------
# Extraction vocabularies (deterministic, documented).
# ---------------------------------------------------------------------------

SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hvac": ("hvac", "furnace", "heater", "heating", "ac", "a/c", "air conditioner", "cooling"),
    "plumbing": ("plumbing", "plumber", "pipe", "pipes", "leak", "drain", "water heater", "toilet", "faucet"),
    "electrical": ("electrical", "electrician", "wiring", "outlet", "breaker", "panel", "light fixture"),
    "roofing": ("roofing", "roof", "roofer", "shingle", "shingles", "gutter"),
    "landscaping": ("landscaping", "landscaper", "lawn", "yard", "mowing", "hedge", "sprinkler"),
}

ZIP_RE = re.compile(r"\b(\d{5})\b")
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
PHONE_DIGITS_RE = re.compile(r"\d")
DAY_NAMES = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
)
DAY_PARTS = ("morning", "afternoon", "evening")
YES_WORDS = ("yes", "yeah", "yep", "sure", "ok", "okay", "please do", "confirm", "book it", "do it")
NO_WORDS = ("no", "nope", "nah", "not yet", "cancel", "never mind", "nevermind")

#: Injection-style patterns. Matching text is never obeyed — the turn is
#: routed to handoff with reason 'suspicious_input'. This list is a
#: documented, deterministic denylist (not an LLM guardrail claim).
INJECTION_PATTERNS = (
    r"ignore (all |any |the |your )?previous instructions",
    r"disregard (all |any |the |your )?(previous|prior|above) instructions",
    r"you are now ",
    r"pretend (you are|to be)",
    r"act as (a |an )?(human|person|real)",
    r"system prompt",
    r"jailbreak",
    r"forget (your|the) instructions",
    r"override (your|the) instructions",
    r"book .* without asking",
    r"skip (the |all )?questions",
)
_INJECTION_RES = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

_COMMAND_WORDS = {
    "yes", "no", "yeah", "yep", "nope", "ok", "okay", "sure", "please",
    "book", "cancel", "help", "hi", "hello", "hey",
}


# ---------------------------------------------------------------------------
# PII masking (applied at write time, before anything is stored).
# ---------------------------------------------------------------------------

_PHONE_RUN_RE = re.compile(r"\d[\d \-\.\(\)]{6,}\d")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_phone_digits(digits: str) -> str:
    """Mask a digit string, keeping only the last 4 digits."""
    digits = "".join(ch for ch in digits if ch.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "***-***-" + digits[-4:]


def mask_text(text: str) -> str:
    """Mask phone-number runs and email addresses inside free text."""
    def _phone(m: re.Match) -> str:
        digits = "".join(ch for ch in m.group(0) if ch.isdigit())
        return mask_phone_digits(digits)

    def _email(m: re.Match) -> str:
        local, _, domain = m.group(0).partition("@")
        head = local[0] if local else ""
        return f"{head}***@{domain}"

    return _EMAIL_RE.sub(_email, _PHONE_RUN_RE.sub(_phone, text))


def mask_slot_value(slot_name: str, value: str) -> str:
    """Mask a slot value according to its sensitivity."""
    if slot_name == "contact_phone":
        return mask_phone_digits(value)
    if slot_name == "contact_name":
        # Names are needed by the human queue, but stored minimized:
        # first name + initial of the rest.
        parts = value.split()
        if not parts:
            return value
        rest = " ".join(p[0] + "." for p in parts[1:] if p)
        return (parts[0] + (" " + rest if rest else "")).strip()
    return value


def looks_like_injection(text: str) -> bool:
    """True when the text matches a documented injection pattern."""
    return any(rx.search(text) for rx in _INJECTION_RES)


# ---------------------------------------------------------------------------
# Policy protocol + deterministic demo policy.
# ---------------------------------------------------------------------------


@dataclass
class PolicyDecision:
    """What the policy understood about one caller turn."""

    extracted: dict[str, str] = field(default_factory=dict)
    confidences: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0  # turn-level: min over claimed slots
    reasons: list[str] = field(default_factory=list)
    injection: bool = False


class DialoguePolicy(Protocol):
    """Replaceable seam for interpreting caller turns.

    v1 ships ``ScriptedDemoPolicy`` (deterministic rules). A future model
    could implement this protocol without redesigning the dialogue
    manager — but it would still be bound by the manager's confidence
    threshold, turn cap, and terminal-state rules.
    """

    name: str

    def interpret(self, text: str, state: str, filled: dict[str, str]) -> PolicyDecision:
        """Interpret one caller utterance in dialogue context.

        ``filled`` maps already-filled slot names to their values, so the
        policy can detect contradictions.
        """
        ...


def _whole_word(text: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def _extract_service(text: str) -> Optional[str]:
    lowered = text.lower()
    # Longest keyword first: "water heater" must beat "heater" so a
    # plumbing mention is not misread as HVAC.
    pairs = sorted(
        ((service, kw) for service, kws in SERVICE_KEYWORDS.items() for kw in kws),
        key=lambda p: len(p[1]),
        reverse=True,
    )
    for service, kw in pairs:
        if _whole_word(lowered, kw):
            return service
    return None


def _extract_location(text: str) -> Optional[str]:
    m = ZIP_RE.search(text)
    return m.group(1) if m else None


def _extract_window(text: str) -> tuple[Optional[str], float]:
    lowered = text.lower()
    m = ISO_DATE_RE.search(text)
    if m:
        return m.group(1), 1.0
    if "today" in lowered.split() or _whole_word(lowered, "today"):
        return "today", 0.9
    if "tomorrow" in lowered.split() or _whole_word(lowered, "tomorrow"):
        return "tomorrow", 0.9
    day = next((d for d in DAY_NAMES if _whole_word(lowered, d)), None)
    part = next((p for p in DAY_PARTS if _whole_word(lowered, p)), None)
    if day and part:
        return f"{day} {part}", 0.9
    if day or part:
        return (day or part), 0.8
    if _whole_word(lowered, "next week"):
        return "next week", 0.8
    return None, 0.0


def _extract_phone(text: str) -> tuple[Optional[str], float]:
    digits = "".join(PHONE_DIGITS_RE.findall(text))
    if len(digits) == 10:
        return digits, 0.95
    if 7 <= len(digits) <= 9:
        return digits, 0.7
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:], 0.95
    return None, 0.0


def _extract_name(text: str) -> tuple[Optional[str], float]:
    cleaned = re.sub(r"[^A-Za-z' -]", " ", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned) < 2:
        return None, 0.0
    words = cleaned.split()
    if len(words) > 4:
        return None, 0.0
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", w) for w in words):
        return None, 0.0
    if len(words) == 1 and words[0].lower() in _COMMAND_WORDS:
        return None, 0.0
    return cleaned, 0.85


def _extract_confirm(text: str) -> tuple[Optional[str], float]:
    lowered = text.lower()
    if any(_whole_word(lowered, w) for w in YES_WORDS):
        return "yes", 1.0
    if any(_whole_word(lowered, w) for w in NO_WORDS):
        return "no", 1.0
    return None, 0.0


class ScriptedDemoPolicy:
    """Deterministic rule-driven policy (v1).

    Honest labeling: this is a scripted slot-filler, NOT a language model.
    It matches keywords/regexes per the documented confidence table above,
    fills slots opportunistically from any turn (service, location, window,
    contact details are all extracted independently), and reports
    confidence 0.0 whenever it recognizes nothing for the current state.
    """

    name = "scripted-demo-v1"

    def interpret(self, text: str, state: str, filled: dict[str, str]) -> PolicyDecision:
        decision = PolicyDecision()
        if looks_like_injection(text):
            decision.injection = True
            decision.confidence = 0.0
            decision.reasons.append("injection pattern matched; never obeyed")
            return decision

        extracted: dict[str, str] = {}
        confidences: dict[str, float] = {}

        def claim(slot: str, value: Optional[str], conf: float, reason: str) -> None:
            if value:
                extracted[slot] = value
                confidences[slot] = conf
                decision.reasons.append(f"{slot}: {reason} (conf {conf:.2f})")

        service = _extract_service(text)
        claim("service", service, 1.0, f"keyword match -> {service}" if service else "")

        location = _extract_location(text)
        claim("location", location, 1.0, f"ZIP {location}" if location else "")

        window, wconf = _extract_window(text)
        claim("window", window, wconf, f"window phrase '{window}'" if window else "")

        if state == CONTACT:
            # In the contact state, interpret the text as name and/or phone.
            phone, pconf = _extract_phone(text)
            claim("contact_phone", phone, pconf, f"{len(phone or '')} digits" if phone else "")
            name, nconf = _extract_name(text)
            if phone and not name:
                pass  # phone-only answer: name stays unfilled, ask for it
            else:
                claim("contact_name", name, nconf, f"name-like '{name}'" if name else "")
        else:
            # Opportunistic contact capture outside the contact state.
            phone, pconf = _extract_phone(text)
            claim("contact_phone", phone, pconf, f"{len(phone or '')} digits" if phone else "")

        if state == CONFIRM:
            answer, aconf = _extract_confirm(text)
            claim("answer", answer, aconf, f"confirm word -> {answer}" if answer else "")

        # The current state's slot determines whether the turn "lands".
        # CONTACT is special: a name-only OR phone-only answer lands (the
        # missing half is asked for next); anything else must fill the
        # state's own slot.
        if state == CONFIRM:
            targets = ("answer",)
        elif state == CONTACT:
            targets = ("contact_name", "contact_phone")
        else:
            target = STATE_SLOT.get(state)
            targets = (target,) if target else ()

        claimed_for_state = any(t in extracted for t in targets) if targets else bool(extracted)
        if not claimed_for_state:
            decision.confidence = 0.0
            want = "/".join(targets) if targets else "input"
            decision.reasons.append(
                f"no recognizable {want} for state '{state}'"
            )
            # Still surface opportunistic slots (they may fill later states),
            # but the turn itself scores 0 -> handoff.
            decision.extracted = extracted
            decision.confidences = confidences
            return decision

        decision.extracted = extracted
        decision.confidences = confidences
        decision.confidence = min(confidences.values()) if confidences else 0.0
        return decision


# ---------------------------------------------------------------------------
# Dialogue manager (finite-state machine).
# ---------------------------------------------------------------------------

GREETING_TEXT = (
    "Hello! I'm Maven, an automated booking assistant for Demo Home Services. "
    "I can help you schedule a service visit — I'll ask a few quick questions, "
    "and if I'm ever unsure, I'll connect you with a person right away. "
    "Which service do you need — HVAC, plumbing, electrical, roofing, or landscaping?"
)

ASK_TEXT = {
    SERVICE: "Which service do you need — HVAC, plumbing, electrical, roofing, or landscaping?",
    LOCATION: "Got it — {service}. What ZIP code is the job at?",
    WINDOW: "Thanks. What day and time work best — for example, 'Tuesday morning' or '2026-10-28'?",
    CONTACT: "Almost done. May I have your name for the booking?",
    "contact_phone": "Thanks, {contact_name}. What's the best callback number?",
}


@dataclass
class TurnResult:
    state: str
    agent_message: str
    confidence: float
    handoff: bool = False
    handoff_reason: Optional[str] = None
    extracted: dict[str, str] = field(default_factory=dict)
    action: str = ""
    transition: tuple[str, str] = ("", "")


class DialogueManager:
    """Finite-state dialogue manager for the booking flow.

    Pure logic: it decides the next state and the agent's reply, and logs
    every transition. Persistence lives in ``booking_agent.py``.
    """

    def __init__(self, policy: Optional[DialoguePolicy] = None):
        self.policy: DialoguePolicy = policy or ScriptedDemoPolicy()

    # -- entry ----------------------------------------------------------------
    def start(self) -> TurnResult:
        """Greeting turn: identifies the agent as automated, asks for service."""
        return TurnResult(
            state=SERVICE,
            agent_message=GREETING_TEXT,
            confidence=1.0,
            action="greet",
            transition=(GREETING, SERVICE),
        )

    # -- main step --------------------------------------------------------------
    def step(
        self,
        text: str,
        state: str,
        filled: dict[str, str],
        turn_count: int,
    ) -> TurnResult:
        """Process one caller utterance. Returns the agent's turn result.

        ``turn_count`` is the number of turns already logged *before* the
        current caller turn. Every path below logs exactly two more turns
        (the caller turn is logged by the caller of ``step``; the agent
        reply is logged afterwards), so triggering the handoff when
        ``turn_count >= MAX_TURNS - 3`` guarantees the logged total never
        exceeds MAX_TURNS - 1 < MAX_TURNS. The full happy path needs 13
        turns, so legitimate conversations always complete before the cap.
        """
        if state in TERMINAL_STATES:
            raise ValueError(f"conversation already {state}; no further turns accepted")

        if turn_count >= MAX_TURNS - 3:
            return self._handoff(
                state, "max_turns",
                f"reached the {MAX_TURNS}-turn cap; handing off to a human",
                confidence=0.0,
            )

        decision = self.policy.interpret(text, state, filled)

        if decision.injection:
            return self._handoff(
                state, "suspicious_input",
                "input matched an injection pattern; never obeyed",
                confidence=0.0,
            )

        # Contradiction check: a confident new value for an already-filled
        # slot that disagrees with the stored value -> handoff, never guess.
        # Stored values are masked, so the candidate is masked the same way
        # before comparison (raw PII never enters the comparison path
        # beyond this transient local).
        for slot, value in decision.extracted.items():
            if slot == "answer" or slot not in filled:
                continue
            if mask_slot_value(slot, value) != filled[slot]:
                if decision.confidences.get(slot, 0.0) >= CONFIDENCE_THRESHOLD:
                    return self._handoff(
                        state, "contradictory_input",
                        f"new '{slot}' value contradicts the earlier one",
                        confidence=0.0,
                    )

        if decision.confidence < CONFIDENCE_THRESHOLD:
            return self._handoff(
                state, "low_confidence",
                f"turn confidence {decision.confidence:.2f} below threshold "
                f"{CONFIDENCE_THRESHOLD:.2f}",
                confidence=decision.confidence,
            )

        # Merge newly extracted slots into the filled set.
        new_filled = dict(filled)
        for slot, value in decision.extracted.items():
            if slot != "answer" and slot not in new_filled:
                new_filled[slot] = value

        if state == CONFIRM:
            return self._handle_confirm(decision, new_filled, state)

        # Advance to the earliest unfilled waiting state.
        target = STATE_SLOT.get(state)
        if target and target in new_filled:
            next_state = self._next_waiting_state(new_filled)
        else:
            next_state = state  # stay: ask again for the same slot

        if next_state == state:
            # Should not normally happen (confidence passed), but stay safe.
            question = self._question_for(state, new_filled)
            return TurnResult(
                state=state, agent_message=question,
                confidence=decision.confidence, action="ask",
                extracted=decision.extracted, transition=(state, state),
            )

        question = self._question_for(next_state, new_filled)
        return TurnResult(
            state=next_state, agent_message=question,
            confidence=decision.confidence, action="ask",
            extracted=decision.extracted, transition=(state, next_state),
        )

    # -- confirm state -----------------------------------------------------------
    def _handle_confirm(
        self, decision: PolicyDecision, filled: dict[str, str], state: str
    ) -> TurnResult:
        answer = decision.extracted.get("answer")
        if answer == "yes":
            # Booking itself happens in booking_agent.py via the adapter.
            return TurnResult(
                state=CONFIRM, agent_message="",
                confidence=decision.confidence, action="book",
                extracted=decision.extracted, transition=(state, CONFIRM),
            )
        if answer == "no":
            return self._handoff(
                state, "slot_declined",
                "caller declined the offered slot; a human should follow up",
                confidence=decision.confidence,
                extracted=decision.extracted,
            )
        return self._handoff(
            state, "low_confidence",
            "could not determine yes/no at confirm",
            confidence=0.0,
            extracted=decision.extracted,
        )

    def _next_waiting_state(self, filled: dict[str, str]) -> str:
        if "service" not in filled:
            return SERVICE
        if "location" not in filled:
            return LOCATION
        if "window" not in filled:
            return WINDOW
        if "contact_name" not in filled or "contact_phone" not in filled:
            return CONTACT
        return CONFIRM

    def _question_for(self, state: str, filled: dict[str, str]) -> str:
        if state == CONTACT and "contact_name" in filled and "contact_phone" not in filled:
            return ASK_TEXT["contact_phone"].format(**filled)
        template = ASK_TEXT.get(state, "")
        try:
            return template.format(**filled)
        except KeyError:
            return template

    def _handoff(
        self, state: str, reason: str, detail: str,
        confidence: float, extracted: Optional[dict[str, str]] = None,
    ) -> TurnResult:
        message = (
            "Thanks — I want to make sure this is handled right, so I'm "
            "connecting you with a person on our team. They'll have our full "
            f"conversation so far. (Reason noted for our team: {reason}.)"
        )
        return TurnResult(
            state=HANDOFF, agent_message=message, confidence=confidence,
            handoff=True, handoff_reason=reason, action="handoff",
            extracted=extracted or {}, transition=(state, HANDOFF),
        )

    # -- confirm prompt (availability text comes ONLY from the adapter) ---------
    @staticmethod
    def confirm_prompt(slot_when: str, slot_ref: str) -> str:
        """Build the confirm question from adapter-provided availability.

        The manager never invents times: ``slot_when`` and ``slot_ref``
        must be strings returned by ``BookingAdapter.get_availability``.
        """
        return (
            f"I found this opening in our booking system: {slot_when} "
            f"(slot {slot_ref}). Should I book it for you? "
            "Please reply yes or no."
        )
