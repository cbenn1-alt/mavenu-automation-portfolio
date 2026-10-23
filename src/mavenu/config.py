"""Shared configuration for the Mavenu automation portfolio.

All settings come from environment variables so that no secret or
environment-specific value is ever baked into code. There are no real
secrets in this project; this module establishes the pattern for later
projects that may need credentials (they must arrive via env vars).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    db_path: str
    port: int
    idempotency_ttl_hours: int
    review_confidence_threshold: float
    log_level: str
    finance_threshold_cents: int
    approval_sla_hours: int


def load_settings() -> Settings:
    """Load settings from the environment. Never raises for missing optional vars."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_db = os.path.join(here, "data", "mavenu.db")
    return Settings(
        db_path=os.environ.get("MAVENU_DB_PATH", default_db),
        port=_get_int("MAVENU_PORT", 8080),
        idempotency_ttl_hours=_get_int("MAVENU_IDEMPOTENCY_TTL_HOURS", 72),
        review_confidence_threshold=_get_float("MAVENU_REVIEW_CONFIDENCE_THRESHOLD", 0.65),
        log_level=os.environ.get("MAVENU_LOG_LEVEL", "INFO"),
        finance_threshold_cents=_get_int("MAVENU_FINANCE_THRESHOLD_CENTS", 100_000),
        approval_sla_hours=_get_int("MAVENU_APPROVAL_SLA_HOURS", 48),
    )
