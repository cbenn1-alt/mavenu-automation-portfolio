"""Project Q03 — RFM feature computation and dormancy scoring.

``features/``: RFM (recency / frequency / monetary) features are computed
over a customer's synthetic job history at a reference time (an injectable
clock). ``scoring/``: a dormancy score is produced behind a replaceable
``DormancyScorer`` protocol (same seam pattern as P01's ``LeadClassifier``
and Q01's ``UrgencyScorer``).

The bundled scorer, ``DeterministicDemoScorer``, is a transparent,
rule-based formula — NOT a trained model, it performs no inference, and
it must never be described as one. It is a pure function of its input
features: identical features always produce an identical score (asserted
by determinism tests).

Dormancy semantics: a HIGHER score means MORE dormant (a better win-back
candidate). Each raw feature is normalized to [0, 1] and combined with
documented weights:

    dormancy = 0.50 * recency_norm
             + 0.30 * (1 - frequency_norm)
             + 0.20 * (1 - monetary_norm)

where:
  recency_norm   = min(days_since_last_job / 365, 1.0)
                   (a customer with no job history is treated as fully
                   dormant: recency_norm = 1.0)
  frequency_norm = min(lifetime_job_count / 10, 1.0)
  monetary_norm  = min(lifetime_spend_cents / 200_000, 1.0)

Weights (inspectable, changeable in one place):
  RECENCY_WEIGHT   0.50   # time since last job dominates dormancy
  FREQUENCY_WEIGHT 0.30   # loyal-but-lapsed customers are cheaper to win back
  MONETARY_WEIGHT  0.20   # high-value history is worth a stronger sequence

Scores are rounded to 3 decimals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

RECENCY_WINDOW_DAYS = 365
FREQUENCY_CAP = 10
MONETARY_CAP_CENTS = 200_000  # $2,000 lifetime spend normalizes to 1.0

RECENCY_WEIGHT = 0.50
FREQUENCY_WEIGHT = 0.30
MONETARY_WEIGHT = 0.20


@dataclass(frozen=True)
class RFMFeatures:
    """Recency / frequency / monetary features for one customer at a reference time."""
    recency_days: float | None  # None when the customer has no job history
    frequency: int              # lifetime completed jobs
    monetary_cents: int         # lifetime spend in cents
    last_job_date: str | None   # ISO-8601 of the most recent job, if any


@dataclass(frozen=True)
class DormancyScore:
    score: float  # 0.0 .. 1.0, higher = more dormant
    reasons: tuple  # human-readable explanation of every applied weight
    scorer: str  # identifier of the scorer that produced this
    flags: tuple = field(default_factory=tuple)  # machine-readable tags


class DormancyScorer(Protocol):
    name: str

    def score(self, features: Mapping[str, Any]) -> DormancyScore:
        ...


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_rfm(
    jobs: Sequence[Mapping[str, Any]], *, now: datetime
) -> RFMFeatures:
    """Compute RFM features over a customer's job history.

    ``jobs``: mappings with at least ``job_date`` (ISO-8601) and
    ``amount_cents`` (int). Jobs dated after ``now`` are ignored (they are
    not history yet). Deterministic: identical inputs always produce
    identical features.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    past = [j for j in jobs if _parse_ts(str(j["job_date"])) <= now]
    if not past:
        return RFMFeatures(
            recency_days=None, frequency=0, monetary_cents=0, last_job_date=None
        )
    latest = max(past, key=lambda j: _parse_ts(str(j["job_date"])))
    last_dt = _parse_ts(str(latest["job_date"]))
    recency_days = (now - last_dt).total_seconds() / 86400.0
    total = 0
    for j in past:
        amount = j.get("amount_cents") or 0
        try:
            total += int(amount)
        except (TypeError, ValueError):
            continue
    return RFMFeatures(
        recency_days=round(recency_days, 3),
        frequency=len(past),
        monetary_cents=total,
        last_job_date=last_dt.isoformat(),
    )


class DeterministicDemoScorer:
    """Rule-based demonstration dormancy scorer.

    Replace with a real model-backed implementation of ``DormancyScorer``
    when one exists. The demo scorer never claims to learn or predict;
    it applies the documented weights in this module's docstring.
    """

    name = "deterministic-rfm-v1"

    def score(self, features: Mapping[str, Any]) -> DormancyScore:
        recency_days = features.get("recency_days")
        frequency = int(features.get("frequency") or 0)
        monetary_cents = int(features.get("monetary_cents") or 0)

        if recency_days is None:
            recency_norm = 1.0
            recency_line = "+0.50 no job history (recency_norm 1.00)"
        else:
            recency_norm = max(0.0, min(1.0, float(recency_days) / RECENCY_WINDOW_DAYS))
            recency_line = (
                f"+{RECENCY_WEIGHT * recency_norm:.3f} recency "
                f"({float(recency_days):.1f}d since last job, "
                f"recency_norm {recency_norm:.3f})"
            )

        frequency_norm = max(0.0, min(1.0, frequency / FREQUENCY_CAP))
        monetary_norm = max(0.0, min(1.0, monetary_cents / MONETARY_CAP_CENTS))

        score = (
            RECENCY_WEIGHT * recency_norm
            + FREQUENCY_WEIGHT * (1.0 - frequency_norm)
            + MONETARY_WEIGHT * (1.0 - monetary_norm)
        )
        reasons = (
            recency_line,
            f"+{FREQUENCY_WEIGHT * (1.0 - frequency_norm):.3f} frequency "
            f"({frequency} lifetime jobs, frequency_norm {frequency_norm:.3f})",
            f"+{MONETARY_WEIGHT * (1.0 - monetary_norm):.3f} monetary "
            f"(${monetary_cents / 100:,.2f} lifetime, monetary_norm {monetary_norm:.3f})",
        )
        flags: list[str] = []
        if recency_days is None:
            flags.append("no-history")
        elif recency_norm >= 0.75:
            flags.append("long-dormant")
        if frequency >= FREQUENCY_CAP:
            flags.append("high-frequency")
        if monetary_norm >= 0.75:
            flags.append("high-value")

        return DormancyScore(
            score=round(score, 3),
            reasons=reasons,
            scorer=self.name,
            flags=tuple(flags),
        )
