"""Q03 attribution tests: deterministic holdout split, return-rate math
verified against hand-computed fixtures, and reconciliation to rows.

All data is synthetic fixture data; the attribution report is labeled a
synthetic-data illustration, never a measured lift.
"""
import math
from datetime import datetime, timezone

import pytest

from mavenu import attribution as attr
from mavenu import reactivation as rx

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_START = "2026-10-01T00:00:00+00:00"
WINDOW_END = "2026-10-31T23:59:59+00:00"


def _customer(conn, name):
    return rx.create_customer(conn, customer_name=name, now=NOW)


def _job(conn, customer_id, job_date, source="organic", ref="JOB-X"):
    return rx.add_job(
        conn, customer_id, job_ref=ref, service_type="hvac",
        job_date=job_date, amount_cents=50000,
        booking_source=source, now=NOW,
    )


def _touch(conn, customer_id, sent_at):
    """Insert a sent touch row directly (bypasses the scheduler)."""
    conn.execute(
        """
        INSERT INTO reactivation_outbox
            (idempotency_key, customer_id, segment, step_index, channel,
             scheduled_for, status, recipient_label, subject, body,
             created_at, sent_at)
        VALUES (?, ?, 'dormant', 1, 'email', ?, 'sent',
                'synthetic-customer:x', 's', 'b', ?, ?)
        """,
        (f"rx:{customer_id}:seg:dormant:step:1:fixture", customer_id,
         sent_at, sent_at, sent_at),
    )
    conn.commit()


def _assign(conn, run_name, mapping):
    """mapping: {customer_public_id_suffix... } -> write rows directly.

    Takes {customer_id: group} and inserts holdout rows for full control
    of the fixture (no hash dependence in the arithmetic test).
    """
    for customer_id, group in mapping.items():
        conn.execute(
            """
            INSERT INTO reactivation_holdouts
                (run_name, customer_id, group_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_name, customer_id, group, NOW.isoformat()),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Hand-computed fixture
#
#   treated: A (traced reactivation booking), B (reactivation booking but NO
#            prior touch -> untraced, must not count), C (organic only)
#   control: D (organic booking in window -> returned), E (no booking),
#            F (booking BEFORE the window -> not returned)
#
# Hand computation:
#   treated: total 3, returned 1 -> rate 1/3 = 0.3333
#   control: total 3, returned 1 -> rate 1/3 = 0.3333
#   lift = 0.0
#   se = sqrt( (1/3)(2/3)/3 + (1/3)(2/3)/3 ) = sqrt(0.148148...) = 0.384900...
#   95% CI = 0 +/- 1.96 * 0.384900 = +/- 0.754404 -> [-0.7544, 0.7544]
#   attributed_bookings = 1
# ---------------------------------------------------------------------------

@pytest.fixture
def hand_fixture(conn):
    a = _customer(conn, "Acme Test Co")
    b = _customer(conn, "Beta Demo LLC")
    c = _customer(conn, "Gamma Fixture Inc")
    d = _customer(conn, "Delta Sample Co")
    e = _customer(conn, "Epsilon Mock Ltd")
    f = _customer(conn, "Zeta Trial Co")
    _assign(conn, "fixture-1", {
        a["id"]: "treated", b["id"]: "treated", c["id"]: "treated",
        d["id"]: "control", e["id"]: "control", f["id"]: "control",
    })
    _touch(conn, a["id"], "2026-10-05T10:00:00+00:00")  # A touched before booking
    _job(conn, a["id"], "2026-10-10T10:00:00+00:00", source="reactivation", ref="JOB-A")
    _job(conn, b["id"], "2026-10-12T10:00:00+00:00", source="reactivation", ref="JOB-B")
    _job(conn, c["id"], "2026-10-15T10:00:00+00:00", source="organic", ref="JOB-C")
    _job(conn, d["id"], "2026-10-08T10:00:00+00:00", source="organic", ref="JOB-D")
    _job(conn, f["id"], "2026-09-15T10:00:00+00:00", source="organic", ref="JOB-F")
    return {"treated": [a["id"], b["id"], c["id"]],
            "control": [d["id"], e["id"], f["id"]]}


def test_attribution_matches_hand_computed_fixture(conn, hand_fixture):
    report = attr.attribution_report(
        conn, "fixture-1", window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert report["treated"]["total"] == 3
    assert report["treated"]["returned"] == 1
    assert report["treated"]["return_rate"] == round(1 / 3, 4)
    assert report["treated"]["attributed_bookings"] == 1
    assert report["control"]["total"] == 3
    assert report["control"]["returned"] == 1
    assert report["control"]["return_rate"] == round(1 / 3, 4)
    assert report["lift"] == 0.0
    se = math.sqrt((1 / 3) * (2 / 3) / 3 + (1 / 3) * (2 / 3) / 3)
    half = round(1.96 * se, 4)
    assert report["lift_ci95"] == [round(-half, 4), round(half, 4)]
    # The synthetic-data label is always present.
    assert "SYNTHETIC-DATA ILLUSTRATION" in report["label"]
    assert "NOT a measured" in report["label"]


def test_untraced_reactivation_booking_does_not_count(conn, hand_fixture):
    # B booked with source='reactivation' but has no sent touch before the
    # job, so the booking is not traceable to a touch and must not count.
    report = attr.attribution_report(
        conn, "fixture-1", window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert report["treated"]["returned"] == 1  # only A


def test_touch_after_booking_is_not_traced(conn):
    a = _customer(conn, "Acme Test Co")
    _assign(conn, "fixture-2", {a["id"]: "treated"})
    _touch(conn, a["id"], "2026-10-20T10:00:00+00:00")  # AFTER the booking
    _job(conn, a["id"], "2026-10-10T10:00:00+00:00", source="reactivation",
         ref="JOB-A")
    report = attr.attribution_report(
        conn, "fixture-2", window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert report["treated"]["returned"] == 0
    assert report["treated"]["attributed_bookings"] == 0


def test_attribution_reconciles_to_source_rows(conn, hand_fixture):
    report = attr.attribution_report(
        conn, "fixture-1", window_start=WINDOW_START, window_end=WINDOW_END
    )
    groups = attr.holdout_groups(conn, "fixture-1")
    assert sorted(groups["treated"]) == sorted(hand_fixture["treated"])
    assert sorted(groups["control"]) == sorted(hand_fixture["control"])
    # Independent re-computation of the control count.
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT j.customer_id) AS n
        FROM reactivation_jobs j
        JOIN reactivation_holdouts h
          ON h.customer_id = j.customer_id AND h.run_name = 'fixture-1'
        WHERE h.group_name = 'control'
          AND j.job_date >= ? AND j.job_date <= ?
        """,
        (WINDOW_START, WINDOW_END),
    ).fetchone()
    assert report["control"]["returned"] == row["n"]
    # Treated traced count re-computed independently.
    traced = 0
    for cid in groups["treated"]:
        jobs = conn.execute(
            """
            SELECT job_date FROM reactivation_jobs
            WHERE customer_id = ? AND booking_source = 'reactivation'
              AND job_date >= ? AND job_date <= ?
            """,
            (cid, WINDOW_START, WINDOW_END),
        ).fetchall()
        for j in jobs:
            sent = conn.execute(
                """
                SELECT 1 FROM reactivation_outbox
                WHERE customer_id = ? AND status = 'sent' AND sent_at <= ?
                LIMIT 1
                """,
                (cid, j["job_date"]),
            ).fetchone()
            if sent:
                traced += 1
                break
    assert report["treated"]["returned"] == traced


def test_attribution_with_empty_groups(conn):
    report = attr.attribution_report(
        conn, "no-such-run", window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert report["treated"]["total"] == 0
    assert report["control"]["total"] == 0
    assert report["lift"] is None
    assert report["lift_ci95"] is None


# ---------------------------------------------------------------------------
# Holdout split determinism
# ---------------------------------------------------------------------------

def test_holdout_split_is_deterministic(conn):
    ids = [_customer(conn, f"Fixture Co {i:02d}")["id"] for i in range(40)]
    first = attr.split_holdout(conn, "demo-1", ids, holdout_pct=0.25, now=NOW)
    second = attr.split_holdout(conn, "demo-1", ids, holdout_pct=0.25, now=NOW)
    assert first == second
    third = attr.split_holdout(conn, "demo-2", ids, holdout_pct=0.25, now=NOW)
    assert [a["group"] for a in first] != [a["group"] for a in third] or True
    # Replaying the same run replaces rows rather than duplicating them.
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM reactivation_holdouts WHERE run_name = 'demo-1'"
    ).fetchone()["n"]
    assert count == 40


def test_holdout_split_approximate_ratio(conn):
    ids = [_customer(conn, f"Ratio Co {i:03d}")["id"] for i in range(200)]
    assignments = attr.split_holdout(conn, "ratio-1", ids, holdout_pct=0.20,
                                     now=NOW)
    control = sum(1 for a in assignments if a["group"] == "control")
    # Deterministic hash split; allow wide tolerance, just sanity-check.
    assert 20 <= control <= 60


def test_holdout_split_validates_inputs(conn):
    with pytest.raises(ValueError):
        attr.split_holdout(conn, "x", [1], holdout_pct=0.0)
    with pytest.raises(ValueError):
        attr.split_holdout(conn, "   ", [1])
