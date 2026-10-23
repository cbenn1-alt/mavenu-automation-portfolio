"""AI classification behind a replaceable interface.

The ``LeadClassifier`` protocol is the seam where a real model would plug in.
The bundled implementation, ``DeterministicDemoClassifier``, is a
transparent rule-based scorer. It is NOT a trained machine-learning model,
it performs no inference, and it must never be described as one.

Uncertain outputs (confidence below the configured threshold) are routed
to human review by the service layer — the classifier only reports its
confidence honestly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class Classification:
    label: str  # "qualified" | "needs_review"
    confidence: float  # 0.0 .. 1.0
    reason: str  # human-readable explanation of the score
    model: str  # identifier of the classifier that produced this


class LeadClassifier(Protocol):
    name: str

    def classify(self, features: Mapping[str, Any]) -> Classification:
        ...


class DeterministicDemoClassifier:
    """Rule-based demonstration classifier.

    Pure function of its inputs: identical features always produce an
    identical classification (asserted by tests). Replace with a real
    model-backed implementation of ``LeadClassifier`` when one exists.
    """

    name = "deterministic-demo-v1"

    def __init__(self, threshold: float = 0.65):
        self.threshold = threshold

    def classify(self, features: Mapping[str, Any]) -> Classification:
        score = 0.45
        reasons: list[str] = ["base score 0.45"]

        has_phone = bool(features.get("has_phone"))
        has_email = bool(features.get("has_email"))
        if has_phone and has_email:
            score += 0.20
            reasons.append("+0.20 phone and email present")
        elif has_phone or has_email:
            score += 0.08
            reasons.append("+0.08 single contact channel")

        if features.get("in_service_area"):
            score += 0.12
            reasons.append("+0.12 inside service area")

        if features.get("urgency") == "priority" and has_phone:
            score += 0.10
            reasons.append("+0.10 priority request with callback number")

        notes_len = int(features.get("notes_len") or 0)
        if notes_len > 20:
            score += 0.08
            reasons.append("+0.08 detailed request notes")
        elif notes_len == 0:
            score -= 0.05
            reasons.append("-0.05 no request details")

        if features.get("service") in ("hvac", "plumbing"):
            score += 0.03
            reasons.append("+0.03 high-demand vertical")

        score = round(max(0.0, min(1.0, score)), 3)
        label = "qualified" if score >= self.threshold else "needs_review"
        return Classification(
            label=label,
            confidence=score,
            reason="; ".join(reasons),
            model=self.name,
        )
