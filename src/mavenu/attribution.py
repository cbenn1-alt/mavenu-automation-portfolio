"""Project Q03 — attribution: bookings traced to reactivation touches.

Method: a deterministic holdout split divides scored customers into a
``treated`` group (eligible for win-back touches) and a ``control`` group
(no touches). Over an attribution window we count:

  treated_returned = treated customers with >= 1 *traced* reactivation
                     booking in the window. A booking is "traced" when it
                     carries ``booking_source='reactivation'`` AND the
                     customer has a SENT touch dated on or before the job.
  control_returned = control customers with >= 1 booking in the window
                     (organic return — these customers receive no touches).

  lift = treated_return_rate - control_return_rate,
  with a Wald 95% confidence interval.

The split is deterministic per (run_name, public_id) via SHA-256, so the
same customers always land in the same group — replays of the analysis
produce identical numbers (tested).

EVERYTHING HERE RUNS ON SYNTHETIC DATA. The report carries an explicit
label saying the lift and interval are a synthetic-data illustration of
the arithmetic, never a measured campaign result. Presenting these
numbers as real marketing performance would be dishonest (see
SECURITY.md and README.md).
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence

from .db import utcnow_iso

SYNTHETIC_LABEL = (
    "SYNTHETIC-DATA ILLUSTRATION: every customer, job, touch, and booking "
    "below is fabricated fixture data. The lift and confidence interval "
    "demonstrate the attribution arithmetic only; they are NOT a measured "
    "campaign result."
)

Z_95 = 1.96  # two-sided 95% normal quantile (Wald interval)


def _now_iso(now: Optional[datetime]) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def split_holdout(
    conn: sqlite3.Connection,
    run_name: str,
    customer_ids: Sequence[int],
    *,
    holdout_pct: float = 0.20,
    seed: str = "q03-holdout-v1",
    actor: str = "system",
    now: Optional[datetime] = None,
) -> list[dict]:
    """Assign customers to treated/control groups deterministically.

    ``digest = sha256(f"{seed}:{run_name}:{public_id}")``; the customer is
    control when ``digest mod 1000 < holdout_pct * 1000``, else treated.
    Existing assignments for ``run_name`` are replaced (analysis runs are
    re-runnable; the split itself is deterministic so replacing is a no-op
    in content). Assignments are persisted to ``reactivation_holdouts``.
    """
    if not run_name.strip():
        raise ValueError("run_name is required")
    if not (0.0 < holdout_pct < 1.0):
        raise ValueError("holdout_pct must be between 0 and 1 (exclusive)")
    now_iso = _now_iso(now)
    conn.execute("DELETE FROM reactivation_holdouts WHERE run_name = ?",
                 (run_name.strip(),))
    threshold = int(holdout_pct * 1000)
    assignments: list[dict] = []
    for customer_id in sorted(set(customer_ids)):
        row = conn.execute(
            "SELECT public_id FROM reactivation_customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        if row is None:
            continue
        digest = hashlib.sha256(
            f"{seed}:{run_name.strip()}:{row['public_id']}".encode("utf-8")
        ).hexdigest()
        group = "control" if int(digest, 16) % 1000 < threshold else "treated"
        conn.execute(
            """
            INSERT INTO reactivation_holdouts
                (run_name, customer_id, group_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_name.strip(), customer_id, group, now_iso),
        )
        assignments.append({"customer_id": customer_id, "group": group})
    conn.commit()
    print(
        json.dumps(
            {
                "ts": now_iso,
                "event": "attribution.holdout_split",
                "actor": actor,
                "run_name": run_name.strip(),
                "treated": sum(1 for a in assignments if a["group"] == "treated"),
                "control": sum(1 for a in assignments if a["group"] == "control"),
                "holdout_pct": holdout_pct,
            },
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
    return assignments


def holdout_groups(conn: sqlite3.Connection, run_name: str) -> dict[str, list[int]]:
    """Return persisted group membership: {"treated": [...], "control": [...]}."""
    rows = conn.execute(
        "SELECT customer_id, group_name FROM reactivation_holdouts WHERE run_name = ?",
        (run_name,),
    ).fetchall()
    groups: dict[str, list[int]] = {"treated": [], "control": []}
    for r in rows:
        groups[r["group_name"]].append(r["customer_id"])
    return groups


def _traced_booking(conn: sqlite3.Connection, customer_id: int,
                    job_date: str) -> bool:
    """True when a SENT touch for this customer predates the job date."""
    row = conn.execute(
        """
        SELECT 1 FROM reactivation_outbox
        WHERE customer_id = ? AND status = 'sent' AND sent_at <= ?
        LIMIT 1
        """,
        (customer_id, job_date),
    ).fetchone()
    return row is not None


def attribution_report(
    conn: sqlite3.Connection,
    run_name: str,
    *,
    window_start: str,
    window_end: str,
) -> dict:
    """Compare treated vs control return rates over the attribution window.

    ``window_start`` / ``window_end`` are ISO-8601 bounds (inclusive).
    Returns rates, the lift, a Wald 95% CI, and the synthetic-data label.
    Every count is a direct SQL aggregation so the report reconciles to
    source rows by construction (tested against hand-computed fixtures).
    """
    groups = holdout_groups(conn, run_name)
    treated_ids = groups["treated"]
    control_ids = groups["control"]

    treated_total = len(treated_ids)
    control_total = len(control_ids)

    treated_returned = 0
    attributed_bookings = 0
    for cid in treated_ids:
        jobs = conn.execute(
            """
            SELECT job_date FROM reactivation_jobs
            WHERE customer_id = ?
              AND job_date >= ? AND job_date <= ?
              AND booking_source = 'reactivation'
            ORDER BY job_date ASC
            """,
            (cid, window_start, window_end),
        ).fetchall()
        traced = [j for j in jobs if _traced_booking(conn, cid, j["job_date"])]
        if traced:
            treated_returned += 1
            attributed_bookings += len(traced)

    control_returned = 0
    if control_ids:
        placeholders = ",".join("?" for _ in control_ids)
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT customer_id) AS n
            FROM reactivation_jobs
            WHERE customer_id IN ({placeholders})
              AND job_date >= ? AND job_date <= ?
            """,
            (*control_ids, window_start, window_end),
        ).fetchone()
        control_returned = row["n"] or 0

    p_t = (treated_returned / treated_total) if treated_total else None
    p_c = (control_returned / control_total) if control_total else None
    lift = (p_t - p_c) if (p_t is not None and p_c is not None) else None
    ci_low = ci_high = None
    if lift is not None and treated_total and control_total:
        se = math.sqrt(
            p_t * (1 - p_t) / treated_total + p_c * (1 - p_c) / control_total
        )
        ci_low = round(lift - Z_95 * se, 4)
        ci_high = round(lift + Z_95 * se, 4)

    return {
        "run_name": run_name,
        "window": {"start": window_start, "end": window_end},
        "treated": {
            "total": treated_total,
            "returned": treated_returned,
            "return_rate": round(p_t, 4) if p_t is not None else None,
            "attributed_bookings": attributed_bookings,
        },
        "control": {
            "total": control_total,
            "returned": control_returned,
            "return_rate": round(p_c, 4) if p_c is not None else None,
        },
        "lift": round(lift, 4) if lift is not None else None,
        "lift_ci95": [ci_low, ci_high] if ci_low is not None else None,
        "method": (
            "holdout comparison: treated return rate minus control return "
            "rate; Wald 95% CI"
        ),
        "label": SYNTHETIC_LABEL,
    }
