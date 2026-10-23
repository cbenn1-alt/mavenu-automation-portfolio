"""Q01 recovery-queue tests: priority, SLA escalation, dashboard, web API.

Clock: T0 = 2026-10-23T12:00:00Z is passed explicitly everywhere time
matters, so assertions are equality checks, not ranges.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest

from mavenu import missed_calls as mc
from tests.conftest import wsgi_call

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

# HOT scores 0.60 in business hours, 0.75 after-hours:
#   base 0.20 + voicemail 0.10 + emergency 0.20 + rings 0.10 (+ after-hours 0.15)
HOT = {"transcript": "No heat in the house", "ring_count": 9}
# COLD scores 0.35 in business hours (base 0.20 + voicemail 0.10 + soft 0.05)
COLD = {"transcript": "Looking for a quote", "ring_count": 3}


def ts(hours_before_t0):
    return (T0 - timedelta(hours=hours_before_t0)).isoformat()


# -- priority queue --------------------------------------------------------------

def test_queue_orders_by_score_times_age_decay(conn):
    # evening timestamps -> after-hours bonus -> score 0.75 for the HOT calls
    mc.ingest_event(conn, {"timestamp": "2026-10-22T22:00:00",
                           "caller_id": "7015550101", **HOT}, now=T0)   # old hot
    mc.ingest_event(conn, {"timestamp": "2026-10-23T06:00:00",
                           "caller_id": "7015550102", **HOT}, now=T0)   # new hot
    mc.ingest_event(conn, {"timestamp": "2026-10-23T11:30:00",
                           "caller_id": "7015550103", **COLD}, now=T0)  # new cold
    queue = mc.priority_queue(conn, now=T0)
    assert [c["public_id"] for c in queue] == ["MC-000002", "MC-000001", "MC-000003"]
    assert queue[0]["priority"] > queue[1]["priority"] > queue[2]["priority"]


def test_priority_decay_formula(conn):
    mc.ingest_event(conn, {"timestamp": "2026-10-22T12:00:00",
                           "caller_id": "7015550101", **HOT}, now=T0)
    (entry,) = mc.priority_queue(conn, now=T0)
    assert entry["age_hours"] == pytest.approx(24.0)
    # business-hours score is 0.60; it halves at 24h of age
    assert entry["urgency_score"] == pytest.approx(0.6)
    assert entry["priority"] == pytest.approx(0.3)


def test_queue_excludes_non_pending(conn):
    mc.ingest_event(conn, {"timestamp": ts(1), "caller_id": "7015550101"}, now=T0)
    mc.log_outcome(conn, "MC-000001", "attempted", "agent:demo", now=T0)
    assert mc.priority_queue(conn, now=T0) == []


def test_queue_limit(conn):
    for i in range(5):
        mc.ingest_event(conn, {"timestamp": ts(1), "caller_id": f"70155501{i:02d}"}, now=T0)
    assert len(mc.priority_queue(conn, now=T0, limit=3)) == 3


# -- SLA escalation ------------------------------------------------------------------

def test_sla_sweep_escalates_aging_high_urgency(conn):
    # 2026-10-23T03:00:00 is after-hours -> HOT scores 0.75 there
    mc.ingest_event(conn, {"timestamp": "2026-10-23T03:00:00",
                           "caller_id": "7015550101", **HOT}, now=T0)  # 0.75, 9h
    mc.ingest_event(conn, {"timestamp": "2026-10-23T11:00:00",
                           "caller_id": "7015550102", **HOT}, now=T0)  # 0.60, 1h
    mc.ingest_event(conn, {"timestamp": "2026-10-23T03:00:00",
                           "caller_id": "7015550103", **COLD}, now=T0)  # 0.50, 9h
    escalated = mc.sweep_sla(conn, now=T0, sla_hours=2.0, urgency_threshold=0.7)
    assert [c["public_id"] for c in escalated] == ["MC-000001"]
    call = mc.get_call(conn, "MC-000001")
    assert call["escalated"] == 1
    notes = conn.execute("SELECT * FROM owner_notifications").fetchall()
    assert len(notes) == 1
    assert notes[0]["status"] == "queued-stub"
    assert "No real message was sent" in notes[0]["message"]
    types = [e["event_type"] for e in mc.call_events(conn, call["id"])]
    assert "call.escalated" in types


def test_sla_sweep_is_idempotent(conn):
    mc.ingest_event(conn, {"timestamp": "2026-10-23T03:00:00",
                           "caller_id": "7015550101", **HOT}, now=T0)
    mc.sweep_sla(conn, now=T0)
    mc.sweep_sla(conn, now=T0)
    assert conn.execute("SELECT COUNT(*) c FROM owner_notifications").fetchone()["c"] == 1


def test_sla_sweep_skips_attempted_calls(conn):
    mc.ingest_event(conn, {"timestamp": "2026-10-23T03:00:00",
                           "caller_id": "7015550101", **HOT}, now=T0)
    mc.log_outcome(conn, "MC-000001", "attempted", "agent:demo", now=T0)
    assert mc.sweep_sla(conn, now=T0) == []


# -- ingestion-lag alert -----------------------------------------------------------

def test_lag_report_quiet_when_feed_current(conn):
    mc.ingest_event(conn, {"timestamp": ts(1), "caller_id": "7015550101"}, now=T0)
    report = mc.ingestion_lag_report(conn, now=T0, max_gap_hours=6.0)
    assert report["alert"] is False
    assert report["gap_hours"] == pytest.approx(1.0)


def test_lag_report_alerts_on_stale_feed(conn):
    mc.ingest_event(conn, {"timestamp": ts(10), "caller_id": "7015550101"}, now=T0)
    report = mc.ingestion_lag_report(conn, now=T0, max_gap_hours=6.0)
    assert report["alert"] is True
    assert "stale" in report["message"].lower()


def test_lag_report_empty_db(conn):
    report = mc.ingestion_lag_report(conn, now=T0)
    assert report["alert"] is False
    assert report["newest_missed_at"] is None


# -- dashboard reconciliation --------------------------------------------------------

def seed_three(conn):
    """3 calls; attempt all at T0; book the first, lose the second."""
    for i, h in enumerate((2, 1, 0.5)):
        mc.ingest_event(conn, {"timestamp": ts(h), "caller_id": f"70155501{i:02d}"}, now=T0)
    for pid in ("MC-000001", "MC-000002", "MC-000003"):
        mc.log_outcome(conn, pid, "attempted", "agent:demo", now=T0)
    mc.log_outcome(conn, "MC-000001", "connected", "agent:demo", now=T0)
    mc.log_outcome(conn, "MC-000001", "booked", "agent:demo", now=T0)
    mc.log_outcome(conn, "MC-000002", "lost", "agent:demo", now=T0)


def test_dashboard_reconciles_with_source_rows(conn):
    seed_three(conn)
    s = mc.dashboard_stats(conn, now=T0)

    # independent re-computation, no shared code path with dashboard_stats()
    total = conn.execute("SELECT COUNT(*) c FROM missed_calls").fetchone()["c"]
    by_state = {r["state"]: r["c"] for r in
                conn.execute("SELECT state, COUNT(*) c FROM missed_calls GROUP BY state")}
    assert s["total"] == total == 3
    assert s["by_state"] == by_state == {"booked": 1, "attempted": 1, "lost": 1}
    assert s["booked"] == 1
    # dashboard rounds rates to 4 decimals; compare against the rounded value
    assert s["recovery_rate"] == round(1 / 3, 4)
    assert s["contact_rate"] == round(1 / 3, 4)  # connected absorbed into booked

    rows = conn.execute(
        """
        SELECT m.missed_at, MIN(e.created_at) AS first_attempt
        FROM missed_calls m
        JOIN call_events e ON e.call_id = m.id AND e.event_type = 'call.attempted'
        GROUP BY m.id
        """
    ).fetchall()
    minutes = sorted(
        (datetime.fromisoformat(r["first_attempt"]) -
         datetime.fromisoformat(r["missed_at"])).total_seconds() / 60.0
        for r in rows
    )
    assert minutes == [30.0, 60.0, 120.0]
    assert s["median_time_to_callback_minutes"] == pytest.approx(60.0)
    assert s["attempted_calls"] == 3


def test_dashboard_empty_db(conn):
    s = mc.dashboard_stats(conn, now=T0)
    assert s["total"] == 0
    assert s["recovery_rate"] == 0.0
    assert s["median_time_to_callback_minutes"] is None


def test_full_pipeline_csv_to_queue_to_outcome_to_dashboard(conn):
    csv_text = (
        "timestamp,caller_id,ring_count,duration_seconds,transcript\n"
        f"{ts(4)},7015550101,9,0,No heat in the house\n"
        f"{ts(2)},7015550102,3,0,quote please\n"
    )
    res = mc.ingest_csv(conn, csv_text, source="csv", actor="demo", now=T0)
    assert res["accepted"] == 2 and res["rejected"] == 0

    queue = mc.priority_queue(conn, now=T0)
    top = queue[0]
    mc.claim_call(conn, top["public_id"], "Rosa", "agent:demo")
    mc.log_outcome(conn, top["public_id"], "attempted", "agent:demo", now=T0)
    mc.log_outcome(conn, top["public_id"], "connected", "agent:demo", now=T0)
    mc.log_outcome(conn, top["public_id"], "booked", "agent:demo", now=T0)

    s = mc.dashboard_stats(conn, now=T0)
    assert s["total"] == 2
    assert s["by_state"] == {"booked": 1, "pending": 1}
    assert s["recovery_rate"] == pytest.approx(0.5)
    # totals reconcile with raw SQL
    assert sum(s["by_state"].values()) == s["total"]


# -- performance -----------------------------------------------------------------------

def test_ingestion_p95_under_5ms_per_event(conn):
    n = 2000
    timings = []
    for i in range(n):
        payload = {"timestamp": ts(i % 48 + 1),
                   "caller_id": f"701555{(i % 9000) + 1000:04d}",
                   "ring_count": i % 12, "transcript": "No heat" if i % 7 == 0 else ""}
        start = time.perf_counter()
        mc.ingest_event(conn, payload, now=T0)
        timings.append((time.perf_counter() - start) * 1000.0)
    timings.sort()
    p95 = timings[int(0.95 * n)]
    assert p95 < 5.0, f"ingestion p95 {p95:.2f} ms exceeds 5 ms budget"
    assert conn.execute("SELECT COUNT(*) c FROM missed_calls").fetchone()["c"] == n


# -- web + API --------------------------------------------------------------------------

def json_call(app, method, path, payload=None, headers=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    return wsgi_call(app, method, path, body=body, headers=headers)


def test_hub_lists_q01(app):
    status, _, body = wsgi_call(app, "GET", "/")
    assert status == 200
    assert b"Q01" in body


def test_q01_form_page_renders(app):
    status, _, body = wsgi_call(app, "GET", "/project_q01")
    assert status == 200
    assert b"Missed-Call Recovery" in body


def test_q01_html_import_single_event_redirects(app):
    form = urlencode({"timestamp": "2026-10-23T10:00:00",
                      "caller_id": "7015550142", "ring_count": "5",
                      "idempotency_key": "html-1"})
    status, headers, _ = wsgi_call(app, "POST", "/project_q01/import",
                                  body=form.encode(),
                                  content_type="application/x-www-form-urlencoded")
    assert status == 303
    assert headers["Location"] == "/project_q01/queue"


def test_q01_queue_and_dashboard_pages(app, settings):
    conn = __import__("mavenu.db", fromlist=["get_connection"]).get_connection(settings.db_path)
    mc.ingest_event(conn, {"timestamp": ts(1), "caller_id": "7015550142"}, now=T0)
    conn.close()
    status, _, body = wsgi_call(app, "GET", "/project_q01/queue")
    assert status == 200
    assert b"MC-000001" in body
    status, _, body = wsgi_call(app, "GET", "/project_q01/dashboard")
    assert status == 200
    assert b"Recovery rate" in body


def test_api_ingest_event_201(app):
    status, _, body = json_call(app, "POST", "/api/missed-calls",
                               {"timestamp": "2026-10-23T10:00:00",
                                "caller_id": "7015550142", "ring_count": 4})
    assert status == 201
    payload = json.loads(body)
    assert payload["public_id"] == "MC-000001"
    assert payload["state"] == "pending"


def test_api_ingest_invalid_returns_422(app):
    status, _, body = json_call(app, "POST", "/api/missed-calls",
                               {"timestamp": "bad", "caller_id": "12"})
    assert status == 422
    assert "validation_failed" in body.decode()


def test_api_ingest_idempotency_replays(app):
    headers = {"Idempotency-Key": "api-k-1"}
    p1 = json_call(app, "POST", "/api/missed-calls",
                   {"timestamp": "2026-10-23T10:00:00", "caller_id": "7015550142"},
                   headers=headers)
    p2 = json_call(app, "POST", "/api/missed-calls",
                   {"timestamp": "2026-10-23T10:00:00", "caller_id": "7015550142"},
                   headers=headers)
    assert p1[0] == 201
    assert p2[0] == 200
    assert json.loads(p2[2])["replayed"] is True


def test_api_import_csv(app):
    csv_text = ("timestamp,caller_id,ring_count\n"
                "2026-10-23T10:00:00,7015550142,5\n"
                "2026-10-23T10:30:00,7015550199,3\n")
    status, _, body = json_call(app, "POST", "/api/missed-calls/import", {"csv": csv_text})
    assert status == 201
    assert json.loads(body)["accepted"] == 2


def test_api_claim_and_outcome_flow(app):
    json_call(app, "POST", "/api/missed-calls",
              {"timestamp": "2026-10-23T10:00:00", "caller_id": "7015550142"})
    status, _, body = json_call(app, "POST", "/api/missed-calls/MC-000001/claim",
                               {"assignee": "Rosa", "actor": "agent:demo"})
    assert status == 200
    assert json.loads(body)["assigned_to"] == "Rosa"
    for to_state in ("attempted", "connected", "booked"):
        status, _, body = json_call(app, "POST", "/api/missed-calls/MC-000001/outcome",
                                   {"to_state": to_state, "actor": "agent:demo"})
        assert status == 200
        assert json.loads(body)["state"] == to_state


def test_api_illegal_outcome_returns_409(app):
    json_call(app, "POST", "/api/missed-calls",
              {"timestamp": "2026-10-23T10:00:00", "caller_id": "7015550142"})
    status, _, body = json_call(app, "POST", "/api/missed-calls/MC-000001/outcome",
                               {"to_state": "booked", "actor": "agent:demo"})
    assert status == 409
    assert "action_rejected" in body.decode()


def test_api_get_call_detail(app):
    json_call(app, "POST", "/api/missed-calls",
              {"timestamp": "2026-10-23T10:00:00", "caller_id": "7015550142"})
    status, _, body = json_call(app, "GET", "/api/missed-calls/MC-000001")
    assert status == 200
    payload = json.loads(body)
    assert payload["caller_id_masked"].endswith("0142")
    assert "caller_id" not in payload or "7015550142" not in json.dumps(payload)
    assert payload["allowed_transitions"] == ["attempted", "lost"]
    assert any(e["event_type"] == "call.scored" for e in payload["events"])


def test_api_unknown_call_404(app):
    status, _, _ = json_call(app, "GET", "/api/missed-calls/MC-999999")
    assert status == 404


def test_api_dashboard_and_sweep(app):
    json_call(app, "POST", "/api/missed-calls",
              {"timestamp": "2020-01-01T03:00:00", "caller_id": "7015550142",
               "ring_count": 9, "transcript": "No heat in the house"})
    status, _, body = json_call(app, "GET", "/api/missed-calls/dashboard")
    assert status == 200
    dash = json.loads(body)
    assert dash["total"] == 1
    assert dash["high_urgency_pending"] == 1
    status, _, body = json_call(app, "POST", "/api/missed-calls/sla-sweep")
    assert status == 200
    assert json.loads(body)["escalated"] == ["MC-000001"]


def test_api_queue_lists_pending(app):
    json_call(app, "POST", "/api/missed-calls",
              {"timestamp": "2026-10-23T10:00:00", "caller_id": "7015550142"})
    status, _, body = json_call(app, "GET", "/api/missed-calls/queue")
    assert status == 200
    payload = json.loads(body)
    assert payload["pending"] == 1
    assert payload["queue"][0]["priority"] > 0
