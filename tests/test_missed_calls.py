"""Q01 missed-call service tests: ingestion, privacy, workflow, outcomes.

All caller IDs below are synthetic fixtures (fictional 555 numbers).
"""
from datetime import datetime, timezone

import pytest

from mavenu import missed_calls as mc
from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.validation import ValidationError
from mavenu.workflow import CALL_WORKFLOW, TERMINAL_CALL_STATES, InvalidTransition

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

C1 = "7015550142"
C2 = "7015550199"
C3 = "7015550117"


def event(ts, caller, **kw):
    e = {"timestamp": ts, "caller_id": caller}
    e.update(kw)
    return e


# -- caller-ID privacy ---------------------------------------------------------

def test_mask_caller_id_hides_all_but_last_four():
    assert mc.mask_caller_id(C1) == "\u2022" * 6 + "0142"
    assert "701555" not in mc.mask_caller_id(C1)


def test_mask_short_number():
    assert mc.mask_caller_id("1234") == "\u2022" * 4


def test_hash_is_deterministic_and_distinct():
    assert mc.hash_caller_id(C1) == mc.hash_caller_id("(701) 555-0142")
    assert mc.hash_caller_id(C1) != mc.hash_caller_id(C2)
    assert len(mc.hash_caller_id(C1)) == 64


# -- event validation ----------------------------------------------------------

def test_normalize_event_cleans_and_scores_inputs():
    n = mc.normalize_event(event("2026-10-23T10:30:00", "(701) 555-0142",
                                 ring_count="9", duration_seconds=45,
                                 transcript="No heat"))
    assert n["missed_at"] == "2026-10-23T10:30:00+00:00"
    assert n["caller_digits"] == C1
    assert n["ring_count"] == 9
    assert n["duration_seconds"] == 45


def test_normalize_event_rejects_bad_timestamp():
    with pytest.raises(ValidationError) as exc:
        mc.normalize_event(event("not-a-date", C1))
    assert "timestamp" in exc.value.field_errors


def test_normalize_event_rejects_short_caller_id():
    with pytest.raises(ValidationError) as exc:
        mc.normalize_event(event("2026-10-23T10:30:00", "555"))
    assert "caller_id" in exc.value.field_errors


def test_normalize_event_rejects_bad_ring_count():
    for bad in ("many", -1, 61):
        with pytest.raises(ValidationError):
            mc.normalize_event(event("2026-10-23T10:30:00", C1, ring_count=bad))


def test_normalize_event_rejects_non_string_transcript():
    with pytest.raises(ValidationError) as exc:
        mc.normalize_event(event("2026-10-23T10:30:00", C1, transcript=["x"]))
    assert "transcript" in exc.value.field_errors


def test_transcript_capped_at_2000_chars():
    n = mc.normalize_event(event("2026-10-23T10:30:00", C1, transcript="x" * 5000))
    assert len(n["transcript"]) == 2000


# -- ingestion -----------------------------------------------------------------

def test_ingest_event_creates_call(conn):
    r = mc.ingest_event(conn, event("2026-10-23T10:30:00", C1,
                                   ring_count=9, transcript="No heat in the house"),
                        source="webhook", actor="demo", now=T0)
    assert r["public_id"] == "MC-000001"
    assert r["state"] == "pending"
    assert r["duplicate"] is False
    call = mc.get_call(conn, "MC-000001")
    assert call["caller_id_masked"] == "\u2022" * 6 + "0142"
    assert call["caller_id_hash"] == mc.hash_caller_id(C1)
    assert call["urgency_score"] == pytest.approx(0.6)  # 0.20 + 0.10 + 0.20 + 0.10
    events = mc.call_events(conn, call["id"])
    assert [e["event_type"] for e in events] == ["call.received", "call.scored"]
    assert events[0]["actor"] == "demo"


def test_raw_caller_id_never_stored(conn):
    mc.ingest_event(conn, event("2026-10-23T10:30:00", C1,
                               transcript="voicemail text"), now=T0)
    blob = ""
    for table in ("missed_calls", "call_events"):
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            blob += " ".join("" if v is None else str(v) for v in dict(row).values())
    assert C1 not in blob
    assert "0142" in blob  # last four visible in the masked form


def test_duplicate_event_does_not_create_new_row(conn):
    first = mc.ingest_event(conn, event("2026-10-23T10:30:00", C1), now=T0)
    second = mc.ingest_event(conn, event("2026-10-23T10:30:00", "(701) 555-0142"), now=T0)
    assert second["duplicate"] is True
    assert second["public_id"] == first["public_id"]
    assert conn.execute("SELECT COUNT(*) c FROM missed_calls").fetchone()["c"] == 1
    types = [e["event_type"] for e in mc.call_events(conn, first["call_id"])]
    assert "call.duplicate_received" in types


def test_out_of_order_timestamps_accepted(conn):
    mc.ingest_event(conn, event("2026-10-23T11:00:00", C1), now=T0)
    mc.ingest_event(conn, event("2026-10-23T09:00:00", C2), now=T0)  # older, later ingested
    rows = conn.execute("SELECT missed_at FROM missed_calls ORDER BY id").fetchall()
    assert rows[1]["missed_at"] < rows[0]["missed_at"]


def test_repeat_caller_gets_repeat_bonus(conn):
    mc.ingest_event(conn, event("2026-10-23T08:00:00", C1), now=T0)
    second = mc.ingest_event(conn, event("2026-10-23T09:00:00", C1), now=T0)
    call = mc.get_call(conn, second["public_id"])
    assert call["urgency_score"] == pytest.approx(0.45)  # 0.20 base + 0.25 repeat
    assert "repeat-caller" in call["flags"]


def test_third_call_in_window_flags_repeat_id_anomaly(conn):
    for ts in ("2026-10-23T08:00:00", "2026-10-23T09:00:00", "2026-10-23T10:00:00"):
        mc.ingest_event(conn, event(ts, C1), now=T0)
    call = mc.get_call(conn, "MC-000003")
    assert "repeat-id-anomaly" in call["flags"]


def test_csv_ingest_batch_with_row_level_errors(conn):
    csv_text = (
        "timestamp,caller_id,ring_count,duration_seconds,transcript\n"
        "2026-10-23T10:00:00,7015550142,9,0,No heat\n"
        "2026-10-23T10:30:00,7015550199,3,0,quote please\n"
        "not-a-date,7015550117,,,\n"
        "2026-10-23T11:00:00,12,,,\n"
    )
    res = mc.ingest_csv(conn, csv_text, source="csv", actor="demo", now=T0)
    assert res["accepted"] == 2
    assert res["rejected"] == 2
    assert res["duplicates"] == 0
    assert {e["row"] for e in res["errors"]} == {4, 5}
    assert res["first_public_id"] == "MC-000001"


def test_csv_ingest_counts_duplicates(conn):
    csv_text = ("timestamp,caller_id\n"
                "2026-10-23T10:00:00,7015550142\n"
                "2026-10-23T10:00:00,7015550142\n")
    res = mc.ingest_csv(conn, csv_text, now=T0)
    assert res["accepted"] == 1
    assert res["duplicates"] == 1


def test_csv_without_header_is_accepted_zero_rows_gracefully(conn):
    res = mc.ingest_csv(conn, "2026-10-23T10:00:00,7015550142\n", now=T0)
    assert res["accepted"] == 0
    assert res["rejected"] == 0


def test_ingest_idempotency_key_replays_without_duplicate(conn):
    payload = event("2026-10-23T10:00:00", C1)
    first = mc.ingest_with_idempotency(conn, payload, idempotency_key="k-1", now=T0)
    second = mc.ingest_with_idempotency(conn, payload, idempotency_key="k-1", now=T0)
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["body"] == first["body"]
    assert conn.execute("SELECT COUNT(*) c FROM missed_calls").fetchone()["c"] == 1


# -- claim / assign --------------------------------------------------------------

def test_claim_sets_assignee_without_state_change(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    call = mc.claim_call(conn, "MC-000001", "Rosa", "agent:demo")
    assert call["assigned_to"] == "Rosa"
    assert call["state"] == "pending"
    types = [e["event_type"] for e in mc.call_events(conn, call["id"])]
    assert "call.claimed" in types


def test_claim_requires_assignee(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    with pytest.raises(ValidationError):
        mc.claim_call(conn, "MC-000001", "  ", "agent:demo")


def test_claim_unknown_call_raises(conn):
    with pytest.raises(KeyError):
        mc.claim_call(conn, "MC-999999", "Rosa", "agent:demo")


def test_claim_non_pending_call_rejected(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    mc.log_outcome(conn, "MC-000001", "attempted", "agent:demo", now=T0)
    with pytest.raises(InvalidTransition):
        mc.claim_call(conn, "MC-000001", "Rosa", "agent:demo")


# -- outcome state machine ---------------------------------------------------------

def test_legal_transitions_pass(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    for to_state in ("attempted", "connected", "booked"):
        call = mc.log_outcome(conn, "MC-000001", to_state, "agent:demo", now=T0)
        assert call["state"] == to_state


def test_attempted_stamps_first_attempt_time(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    call = mc.log_outcome(conn, "MC-000001", "attempted", "agent:demo", now=T0)
    assert call["attempted_at"] == T0.isoformat()


def test_booked_and_lost_stamp_outcome_time(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    mc.log_outcome(conn, "MC-000001", "attempted", "agent:demo", now=T0)
    mc.log_outcome(conn, "MC-000001", "connected", "agent:demo", now=T0)
    call = mc.log_outcome(conn, "MC-000001", "booked", "agent:demo", now=T0)
    assert call["outcome_at"] == T0.isoformat()


@pytest.mark.parametrize("from_state,to_state", [
    ("pending", "booked"),
    ("pending", "connected"),
    ("attempted", "pending"),
    ("attempted", "booked"),
    ("connected", "attempted"),
    ("connected", "pending"),
    ("booked", "attempted"),
    ("booked", "lost"),
    ("lost", "pending"),
    ("lost", "attempted"),
])
def test_illegal_transitions_raise(conn, from_state, to_state):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    path = {"pending": [], "attempted": ["attempted"],
            "connected": ["attempted", "connected"],
            "booked": ["attempted", "connected", "booked"],
            "lost": ["attempted", "lost"]}[from_state]
    for step in path:
        mc.log_outcome(conn, "MC-000001", step, "agent:demo", now=T0)
    with pytest.raises(InvalidTransition):
        mc.log_outcome(conn, "MC-000001", to_state, "agent:demo", now=T0)
    # the failed move must not change state
    assert mc.get_call(conn, "MC-000001")["state"] == from_state


def test_terminal_states_have_no_outgoing_moves():
    for terminal in ("booked", "lost"):
        assert CALL_WORKFLOW.allowed_from(terminal) == set()
    assert TERMINAL_CALL_STATES == {"booked", "lost"}


def test_outcome_unknown_call_raises(conn):
    with pytest.raises(KeyError):
        mc.log_outcome(conn, "MC-999999", "attempted", "agent:demo", now=T0)


def test_pending_can_be_closed_as_lost(conn):
    mc.ingest_event(conn, event("2026-10-23T10:00:00", C1), now=T0)
    call = mc.log_outcome(conn, "MC-000001", "lost", "agent:demo", now=T0)
    assert call["state"] == "lost"
    assert call["outcome_at"] == T0.isoformat()


# -- migration rollback --------------------------------------------------------------

def test_migration_003_down_step_rolls_back_for_real(conn):
    assert "003_missed_calls.sql" in applied_migrations(conn)
    before = {r["name"] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"missed_calls", "call_events", "call_idempotency_keys",
            "owner_notifications"} <= before

    assert rollback_migration(conn, "003_missed_calls.sql") is True

    after = {r["name"] for r in
             conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "missed_calls" not in after
    assert "call_events" not in after
    assert "003_missed_calls.sql" not in applied_migrations(conn)
    # P01/P02 tables untouched
    assert {"leads", "requests"} <= after

    # re-apply works
    assert run_migrations(conn) == ["003_missed_calls.sql"]
    assert "missed_calls" in {
        r["name"] for r in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def test_rollback_unapplied_migration_is_noop(conn):
    rollback_migration(conn, "003_missed_calls.sql")
    assert rollback_migration(conn, "003_missed_calls.sql") is False
    run_migrations(conn)
