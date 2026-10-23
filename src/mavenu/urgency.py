"""Project Q01 — deterministic urgency scoring for missed calls.

The ``UrgencyScorer`` protocol is the seam where a real model would plug in.
The bundled implementation, ``DeterministicDemoScorer``, is a transparent
rule-based scorer. It is NOT a trained machine-learning model, it performs
no inference, and it must never be described as one.

The scorer is a pure function of its input features: identical features
always produce an identical score (asserted by property-style tests).

Weights (documented, inspectable, changeable in one place):
  base                                0.20
  +0.25  repeat caller (prior missed call from this caller in the window)
  +0.15  after-hours (outside 08:00-18:00 local wall time, or Sat/Sun)
  +0.20  emergency keyword in voicemail transcript
  +0.05  service-request keyword in transcript (only if no emergency keyword)
  +0.10  caller left voicemail (non-empty transcript)
  +0.10  persistent caller (ring_count >= 8)
Scores are clamped to [0.0, 1.0] and rounded to 3 decimals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol

BUSINESS_OPEN_HOUR = 8
BUSINESS_CLOSE_HOUR = 18
LONG_RING_THRESHOLD = 8

# Emergency keywords indicate a caller with an urgent problem (no heat in
# winter, water intrusion, gas, electrical hazard). Matching is
# case-insensitive substring matching on the transcript.
EMERGENCY_KEYWORDS = (
    "no heat",
    "no hot water",
    "no water",
    "flooding",
    "flood",
    "gas leak",
    "burst pipe",
    "burst",
    "sparking",
    "sparks",
    "electrical fire",
    "carbon monoxide",
    "sewage",
    "sewer backup",
    "water pouring",
)

# Softer buying/service intent; weaker signal than an emergency.
SOFT_KEYWORDS = (
    "quote",
    "estimate",
    "pricing",
    "price",
    "schedule",
    "appointment",
    "book",
    "call back",
    "callback",
)


@dataclass(frozen=True)
class UrgencyScore:
    score: float  # 0.0 .. 1.0
    reasons: tuple  # human-readable explanation of every applied rule
    scorer: str  # identifier of the scorer that produced this
    flags: tuple = field(default_factory=tuple)  # machine-readable tags


class UrgencyScorer(Protocol):
    name: str

    def score(self, features: Mapping[str, Any]) -> UrgencyScore:
        ...


def is_after_hours(missed_at: str) -> bool:
    """True when the call arrived outside 08:00-18:00 Mon-Fri local wall time.

    The timestamp's own wall clock is used (naive timestamps are treated as
    local). This keeps the function pure: identical input strings always give
    identical results.
    """
    dt = datetime.fromisoformat(missed_at.replace("Z", "+00:00"))
    if dt.weekday() >= 5:  # Saturday / Sunday
        return True
    return dt.hour < BUSINESS_OPEN_HOUR or dt.hour >= BUSINESS_CLOSE_HOUR


def _keyword_hits(transcript: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = (transcript or "").lower()
    return [kw for kw in keywords if kw and kw in lowered]


class DeterministicDemoScorer:
    """Rule-based demonstration urgency scorer.

    Replace with a real model-backed implementation of ``UrgencyScorer``
    when one exists. The demo scorer never claims to learn or predict;
    it applies the documented weights above.
    """

    name = "deterministic-demo-v1"

    def score(self, features: Mapping[str, Any]) -> UrgencyScore:
        score = 0.20
        reasons = ["base score 0.20"]
        flags: list[str] = []

        repeat_count = int(features.get("repeat_count") or 0)
        if repeat_count >= 1:
            score += 0.25
            reasons.append("+0.25 repeat caller "
                           f"({repeat_count} prior missed call(s) in window)")
            flags.append("repeat-caller")

        missed_at = str(features.get("missed_at") or "")
        if missed_at and is_after_hours(missed_at):
            score += 0.15
            reasons.append("+0.15 after-hours call")
            flags.append("after-hours")

        transcript = features.get("transcript") or ""
        transcript = str(transcript)
        if transcript.strip():
            score += 0.10
            reasons.append("+0.10 caller left voicemail")

        emergency = _keyword_hits(transcript, EMERGENCY_KEYWORDS)
        if emergency:
            score += 0.20
            reasons.append("+0.20 emergency keyword(s): " + ", ".join(emergency))
            flags.append("emergency-keyword")
        else:
            soft = _keyword_hits(transcript, SOFT_KEYWORDS)
            if soft:
                score += 0.05
                reasons.append("+0.05 service-request keyword(s): " + ", ".join(soft))

        ring_count = features.get("ring_count")
        try:
            rings = int(ring_count) if ring_count is not None else 0
        except (TypeError, ValueError):
            rings = 0
        if rings >= LONG_RING_THRESHOLD:
            score += 0.10
            reasons.append(f"+0.10 persistent caller ({rings} rings)")

        score = round(max(0.0, min(1.0, score)), 3)
        return UrgencyScore(
            score=score,
            reasons=tuple(reasons),
            scorer=self.name,
            flags=tuple(flags),
        )
