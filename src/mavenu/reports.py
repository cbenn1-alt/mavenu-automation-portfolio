"""Project Q02 — reports: aging, win/loss, follow-up effectiveness.

Every figure is computed directly from the ``estimates`` table; the test
suite asserts each report reconciles with an independent raw-SQL
re-computation, so there are zero unexplained deltas.

The clock is injectable (``now=``) so report timelines are deterministic.
All timestamps are stored and compared in UTC; any local-time rendering is
a presentation concern of the caller, never of this module.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .estimates import _age_days, _parse_ts
from .workflow import OPEN_ESTIMATE_STATES, TERMINAL_ESTIMATE_STATES

AGE_BUCKETS = [
    ("0-2", 0.0, 3.0),
    ("3-7", 3.0, 8.0),
    ("8-14", 8.0, 15.0),
    ("15-30", 15.0, 31.0),
    ("31+", 31.0, float("inf")),
]

FOLLOWUP_BUCKETS = [0, 1, 2]  # 3+ folded into "3+"


def _now_or(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _all_estimates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM estimates").fetchall()
    return [dict(r) for r in rows]


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


# ---------------------------------------------------------------------------
# Aging report: open estimates grouped by days since sent
# ---------------------------------------------------------------------------

def aging_report(conn: sqlite3.Connection, *, now: Optional[datetime] = None) -> dict:
    """Open estimates (sent/viewed/followed_up) bucketed by age in days.

    Each bucket: count of estimates + total open value. ``unbucketed`` is
    0 by construction (every open estimate has sent_at), and the test suite
    asserts the buckets sum back to the open-estimate rows exactly.
    """
    now = _now_or(now)
    buckets = {name: {"count": 0, "amount_cents": 0} for name, _, _ in AGE_BUCKETS}
    open_estimates = [
        e for e in _all_estimates(conn)
        if e["state"] in OPEN_ESTIMATE_STATES and e["sent_at"]
    ]
    for estimate in open_estimates:
        age = _age_days(estimate["sent_at"], now)
        for name, lo, hi in AGE_BUCKETS:
            if lo <= age < hi:
                buckets[name]["count"] += 1
                buckets[name]["amount_cents"] += estimate["amount_cents"]
                break
    return {
        "as_of": now.isoformat(),
        "open_count": len(open_estimates),
        "open_amount_cents": sum(e["amount_cents"] for e in open_estimates),
        "buckets": [
            {"bucket": name, **buckets[name]} for name, _, _ in AGE_BUCKETS
        ],
    }


# ---------------------------------------------------------------------------
# Win/loss: by service type and by estimator
# ---------------------------------------------------------------------------

def _win_loss_for(rows: list[dict], key: str) -> list[dict]:
    segments: dict[str, dict] = {}
    for estimate in rows:
        seg = segments.setdefault(
            estimate[key],
            {"sent": 0, "accepted": 0, "declined": 0, "expired": 0,
             "amount_won_cents": 0, "amount_sent_cents": 0},
        )
        seg["amount_sent_cents"] += estimate["amount_cents"]
        if estimate["state"] == "draft":
            continue
        seg["sent"] += 1
        if estimate["state"] == "accepted":
            seg["accepted"] += 1
            seg["amount_won_cents"] += estimate["amount_cents"]
        elif estimate["state"] == "declined":
            seg["declined"] += 1
        elif estimate["state"] == "expired":
            seg["expired"] += 1
    out = []
    for segment, seg in sorted(segments.items()):
        decided = seg["accepted"] + seg["declined"]
        seg["win_rate"] = round(seg["accepted"] / decided, 4) if decided else None
        out.append({"segment": segment, **seg})
    return out


def win_loss_report(conn: sqlite3.Connection) -> dict:
    """Win/loss by service type and by estimator.

    win_rate = accepted / (accepted + declined); None when nothing was
    decided yet. Draft estimates count toward value but not toward
    opportunities sent.
    """
    estimates = _all_estimates(conn)
    return {
        "by_service_type": _win_loss_for(estimates, "service_type"),
        "by_estimator": _win_loss_for(estimates, "estimator"),
        "decline_reasons": _decline_reasons(conn),
    }


def _decline_reasons(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT decline_reason AS reason, COUNT(*) AS c
        FROM estimates
        WHERE state = 'declined'
        GROUP BY decline_reason
        ORDER BY c DESC
        """
    ).fetchall()
    return [{"reason": r["reason"], "count": r["c"]} for r in rows]


# ---------------------------------------------------------------------------
# Follow-up effectiveness: does nudging convert?
# ---------------------------------------------------------------------------

def followup_effectiveness(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None
) -> dict:
    """Acceptance rate grouped by number of follow-ups queued.

    Estimates still open are counted in the denominator of their bucket
    but not as wins; the ``median_days_sent_to_accepted`` is over accepted
    estimates with both timestamps.
    """
    estimates = [e for e in _all_estimates(conn) if e["state"] != "draft"]
    buckets: dict[str, dict] = {
        "0": {"estimates": 0, "accepted": 0},
        "1": {"estimates": 0, "accepted": 0},
        "2": {"estimates": 0, "accepted": 0},
        "3+": {"estimates": 0, "accepted": 0},
    }
    days_to_accept: list[float] = []
    for estimate in estimates:
        bucket = str(min(estimate["followup_count"], 3)) if estimate["followup_count"] < 3 else "3+"
        buckets[bucket]["estimates"] += 1
        if estimate["state"] == "accepted":
            buckets[bucket]["accepted"] += 1
            if estimate["sent_at"] and estimate["accepted_at"]:
                days_to_accept.append(
                    (_parse_ts(estimate["accepted_at"]) - _parse_ts(estimate["sent_at"])).total_seconds()
                    / 86400.0
                )
    result = []
    for bucket, data in buckets.items():
        rate = (
            round(data["accepted"] / data["estimates"], 4)
            if data["estimates"] else None
        )
        result.append({"followups": bucket, "accept_rate": rate, **data})
    return {
        "by_followup_count": result,
        "median_days_sent_to_accepted": (
            round(_median(days_to_accept), 2) if days_to_accept else None
        ),
        "accepted_with_timestamps": len(days_to_accept),
    }
