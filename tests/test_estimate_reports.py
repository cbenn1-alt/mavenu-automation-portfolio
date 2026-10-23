"""Q02 report tests: aging, win/loss, follow-up effectiveness.

Every assertion reconciles the report against an independent raw-SQL
re-computation over the same rows — zero unexplained deltas. All fixture
data is synthetic.
"""
import json
from datetime import datetime, timedelta, timezone

from mavenu import cadence as ca
from mavenu import estimates as es
from mavenu import reports as rp

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def seed(conn):
    """A mixed synthetic portfolio. Returns {label: estimate}."""
    made = {}

    def add(label, days_ago, service, estimator, cents, terminal=None,
            decline_reason="price", followups=0):
        sent_at = T0 - timedelta(days=days_ago)
        e = es.create_estimate(conn, {
            "customer_name": f"{label} Test Co", "service_type": service,
            "estimator": estimator, "amount_cents": cents}, actor="seed", now=sent_at)
        e = es.transition_estimate(conn, e["public_id"], "sent", "seed", now=sent_at)
        for _ in range(followups):
            conn.execute(
                "UPDATE estimates SET followup_count = followup_count + 1 WHERE id = ?",
                (e["id"],))
        conn.commit()
        if terminal == "accepted":
            e = es.transition_estimate(conn, e["public_id"], "accepted", "seed",
                                       now=sent_at + timedelta(days=3))
        elif terminal == "declined":
            e = es.transition_estimate(conn, e["public_id"], "declined", "seed",
                                       decline_reason=decline_reason,
                                       now=sent_at + timedelta(days=5))
        elif terminal == "expired":
            e = es.transition_estimate(conn, e["public_id"], "expired", "seed",
                                       now=sent_at + timedelta(days=31))
        made[label] = es.get_estimate(conn, e["public_id"])
        return made[label]

    add("A", 1, "hvac", "Rosa", 100000, terminal="accepted", followups=1)
    add("B", 5, "hvac", "Rosa", 200000, terminal="declined", decline_reason="price",
        followups=2)
    add("C", 10, "plumbing", "Rosa", 50000, followups=2)            # open
    add("D", 20, "plumbing", "Theo", 75000, terminal="declined",
        decline_reason="chose_competitor", followups=3)              # open? no -> declined
    add("E", 40, "roofing", "Theo", 300000, terminal="expired", followups=3)
    add("F", 2, "roofing", "Theo", 150000, followups=0)              # open
    add("G", 12, "electrical", "Rosa", 90000, terminal="accepted", followups=2)
    return made


# -- aging ---------------------------------------------------------------------------------

def test_aging_report_reconciles_to_estimate_rows(conn):
    seed(conn)
    report = rp.aging_report(conn, now=T0)
    # Independent re-computation straight from the table.
    rows = conn.execute(
        "SELECT sent_at, amount_cents FROM estimates "
        "WHERE state IN ('sent','viewed','followed_up') AND sent_at IS NOT NULL"
    ).fetchall()
    assert report["open_count"] == len(rows)
    assert report["open_amount_cents"] == sum(r["amount_cents"] for r in rows)
    bucket_counts = {b["bucket"]: b["count"] for b in report["buckets"]}
    bucket_amounts = {b["bucket"]: b["amount_cents"] for b in report["buckets"]}
    assert sum(bucket_counts.values()) == len(rows)
    assert sum(bucket_amounts.values()) == sum(r["amount_cents"] for r in rows)
    # Spot-check bucketing: C is 10 days old -> "8-14"; F is 2 days old -> "0-2".
    assert bucket_counts["8-14"] == 1 and bucket_counts["0-2"] == 1
    assert bucket_counts["3-7"] == 0 and bucket_counts["31+"] == 0


def test_aging_report_empty_db(conn):
    report = rp.aging_report(conn, now=T0)
    assert report["open_count"] == 0
    assert all(b["count"] == 0 for b in report["buckets"])


# -- win / loss ------------------------------------------------------------------------------

def test_win_loss_by_service_type_reconciles(conn):
    seed(conn)
    report = rp.win_loss_report(conn)
    by_service = {s["segment"]: s for s in report["by_service_type"]}
    # Independent re-computation.
    for service in ("hvac", "plumbing", "roofing", "electrical"):
        rows = conn.execute(
            "SELECT state, amount_cents FROM estimates WHERE service_type = ?",
            (service,)).fetchall()
        seg = by_service[service]
        assert seg["sent"] == sum(1 for r in rows if r["state"] != "draft")
        assert seg["accepted"] == sum(1 for r in rows if r["state"] == "accepted")
        assert seg["declined"] == sum(1 for r in rows if r["state"] == "declined")
        assert seg["expired"] == sum(1 for r in rows if r["state"] == "expired")
        assert seg["amount_won_cents"] == sum(
            r["amount_cents"] for r in rows if r["state"] == "accepted")
    hvac = by_service["hvac"]      # 1 accepted, 1 declined -> 0.5
    assert hvac["win_rate"] == 0.5
    roofing = by_service["roofing"]  # 0 accepted, 0 declined -> None
    assert roofing["win_rate"] is None
    electrical = by_service["electrical"]  # 1 accepted, 0 declined -> 1.0
    assert electrical["win_rate"] == 1.0


def test_win_loss_by_estimator_reconciles(conn):
    seed(conn)
    report = rp.win_loss_report(conn)
    by_est = {s["segment"]: s for s in report["by_estimator"]}
    rosa = by_est["Rosa"]   # accepted A, G; declined B
    assert (rosa["accepted"], rosa["declined"]) == (2, 1)
    assert rosa["win_rate"] == round(2 / 3, 4)
    theo = by_est["Theo"]   # declined D; expired E; open F
    assert (theo["accepted"], theo["declined"], theo["expired"]) == (0, 1, 1)
    assert theo["win_rate"] == 0.0


def test_decline_reasons_grouped(conn):
    seed(conn)
    reasons = {d["reason"]: d["count"] for d in rp.win_loss_report(conn)["decline_reasons"]}
    assert reasons == {"price": 1, "chose_competitor": 1}


# -- follow-up effectiveness ----------------------------------------------------------------------

def test_followup_effectiveness_reconciles(conn):
    seed(conn)
    report = rp.followup_effectiveness(conn)
    buckets = {b["followups"]: b for b in report["by_followup_count"]}
    # Independent re-computation.
    for bucket, label in (("0", 0), ("1", 1), ("2", 2), ("3+", 3)):
        rows = conn.execute(
            "SELECT state FROM estimates WHERE state != 'draft' AND "
            + ("followup_count = ?" if bucket != "3+" else "followup_count >= ?"),
            (label,)).fetchall()
        b = buckets[bucket]
        assert b["estimates"] == len(rows), bucket
        assert b["accepted"] == sum(1 for r in rows if r["state"] == "accepted"), bucket
    assert buckets["1"]["accept_rate"] == 1.0   # A accepted with 1 follow-up
    assert buckets["0"]["accept_rate"] == 0.0   # F open with 0 follow-ups
    assert buckets["2"]["accept_rate"] == round(1 / 3, 4)  # G won; B lost, C open
    # Median days sent -> accepted over A (3 days) and G (3 days).
    assert report["median_days_sent_to_accepted"] == 3.0
    assert report["accepted_with_timestamps"] == 2


def test_effectiveness_empty_db(conn):
    report = rp.followup_effectiveness(conn)
    assert all(b["accept_rate"] is None for b in report["by_followup_count"])
    assert report["median_days_sent_to_accepted"] is None
