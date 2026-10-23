"""Q10 — Webhook Integration Hub: core service tests (stdlib only).

Covers: HMAC verification (valid/invalid/replay/tampered), strict-mode
rejection, routing-rule matching + dry-run parity, retry/backoff schedule
(injectable clock), dead-letter after N attempts, circuit breaker
(open/half-open/recover), poison-event isolation (5k fuzz, zero crashes),
idempotency, full lineage audit, terminal state for every event, and the
007 migration rollback (for real).

All fixtures are synthetic. No network, no real credentials: signatures
use the documented TEST-ONLY secrets in webhooks.TEST_WEBHOOK_SECRETS.
"""
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from mavenu import delivery, router
from mavenu import webhooks as wh
from mavenu.db import rollback_migration, run_migrations

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def secrets():
    return dict(wh.TEST_WEBHOOK_SECRETS)


def _body(source="demo-form", event_type="lead.created",
          event_id="evt-test-1", payload=None):
    return json.dumps({
        "source": source,
        "event_type": event_type,
        "event_id": event_id,
        "payload": payload if payload is not None else {"name": "Sample Lead"},
    }).encode()


def _signed(body, secrets, source="demo-form"):
    return wh.sign(secrets[source], body)


@pytest.fixture
def ok_endpoints():
    return {
        "stub:crm-sink": lambda d, e: {"ok": True, "sink": "crm"},
        "stub:calendar-sink": lambda d, e: {"ok": True, "sink": "calendar"},
        "stub:sheet-sink": lambda d, e: {"ok": True, "sink": "sheet"},
    }


def _failing_endpoints(message="stub endpoint down"):
    def boom(delivery_row, envelope):
        raise RuntimeError(message)
    return {"stub:fail": boom}


@pytest.fixture
def fail_endpoints():
    return _failing_endpoints()


@pytest.fixture
def seeded(conn):
    """conn with the three demo rules seeded."""
    router.seed_demo_rules(conn)
    return conn


def _seed_event(conn, event_id, event_type="lead.created", source="demo-form"):
    """Insert a minimal stored event + received→routed lineage."""
    conn.execute(
        "INSERT INTO webhook_events (public_id, event_id, source, event_type,"
        " envelope_json, signature_ok, created_at)"
        " VALUES (?, ?, ?, ?, ?, 1, ?)",
        ("EVT-TEST-" + event_id, event_id, source, event_type,
         json.dumps({"event_id": event_id, "source": source,
                     "event_type": event_type, "payload": {}}),
         T0.isoformat()),
    )
    conn.commit()
    wh.record_lineage(conn, event_id, "received", actor="t")
    wh.record_lineage(conn, event_id, "routed", from_state="received", actor="t")


def _enqueue(conn, event_id, endpoint, **kwargs):
    """Enqueue a delivery for a properly stored event (realistic queue state)."""
    _seed_event(conn, event_id)
    return delivery.enqueue_delivery(conn, event_id, endpoint, **kwargs)


# ---------------------------------------------------------------------------
# HMAC signature verification
# ---------------------------------------------------------------------------

def test_sign_verify_roundtrip(secrets):
    body = _body()
    sig = _signed(body, secrets)
    assert sig.startswith("sha256=")
    assert wh.verify_signature(secrets["demo-form"], body, sig) is True


@pytest.mark.parametrize("tamper", ["append", "flip", "truncate"])
def test_tampered_body_fails_verification(secrets, tamper):
    body = _body()
    sig = _signed(body, secrets)
    if tamper == "append":
        body = body + b" "
    elif tamper == "flip":
        body = b"X" + body[1:]
    else:
        body = body[:-10]
    assert wh.verify_signature(secrets["demo-form"], body, sig) is False


def test_wrong_secret_fails(secrets):
    body = _body()
    sig = wh.sign("some-other-secret", body)
    assert wh.verify_signature(secrets["demo-form"], body, sig) is False


@pytest.mark.parametrize("bad_sig", [
    "", None, "sha256=", "sha256=zzz",
    "md5=" + "0" * 32, "sha256=" + "0" * 63, "sha256=" + "0" * 65,
    "SHA256=" + "a" * 64, "not-a-signature",
])
def test_empty_and_malformed_signatures_fail(secrets, bad_sig):
    body = _body()
    assert wh.verify_signature(secrets["demo-form"], body, bad_sig) is False


def test_compare_digest_is_used_for_timing_safety(secrets):
    # The verifier must use hmac.compare_digest (constant-time), per S05 guidance.
    import hmac as hmac_mod
    body = _body()
    sig = _signed(body, secrets)
    seen = []
    real = hmac_mod.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    hmac_mod.compare_digest = spy
    try:
        assert wh.verify_signature(secrets["demo-form"], body, sig) is True
    finally:
        hmac_mod.compare_digest = real
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# Strict-mode rejection of unsigned events
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sig_variant,reason", [
    ("", "missing_signature"),
    ("sha256=" + "0" * 64, "invalid_signature"),
])
def test_strict_rejects_unsigned_or_invalid(conn, secrets, sig_variant, reason):
    body = _body(event_id="rej-1")
    result = wh.ingest_event(conn, body=body, signature=sig_variant,
                             secrets=secrets, strict=True)
    assert result["accepted"] is False
    assert result["rejection_reason"] == reason
    # stored + rejected lineage, never routed
    assert wh.event_status(conn, "rej-1") == "rejected"
    assert delivery.list_deliveries(conn) == []
    lineage = wh.get_lineage(conn, "rej-1")
    assert [(l["from_state"], l["to_state"]) for l in lineage] == [(None, "rejected")]


def test_strict_rejects_unknown_source(conn, secrets):
    body = _body(source="mystery-source", event_id="rej-2")
    result = wh.ingest_event(conn, body=body, signature="sha256=" + "a" * 64,
                             secrets=secrets, strict=True)
    assert result["accepted"] is False
    assert result["rejection_reason"] == "unknown_source"
    assert wh.event_status(conn, "rej-2") == "rejected"


def test_nonstrict_accepts_unsigned_but_flags_unverified(conn, secrets, ok_endpoints, seeded):
    body = _body(event_id="nonstrict-1")
    result = wh.ingest_event(conn, body=body, signature="",
                             secrets=secrets, strict=False)
    assert result["accepted"] is True
    assert result["verified"] is False
    row = conn.execute(
        "SELECT signature_ok FROM webhook_events WHERE event_id = 'nonstrict-1'"
    ).fetchone()
    assert row["signature_ok"] == 0


# ---------------------------------------------------------------------------
# Replay + idempotency
# ---------------------------------------------------------------------------

def test_replay_same_signature_same_event_id_is_duplicate(conn, secrets):
    body = _body(event_id="replay-1")
    sig = _signed(body, secrets)
    first = wh.ingest_event(conn, body=body, signature=sig,
                            secrets=secrets, strict=True)
    second = wh.ingest_event(conn, body=body, signature=sig,
                             secrets=secrets, strict=True)
    assert first["accepted"] is True and first["duplicate"] is False
    assert second["accepted"] is True and second["duplicate"] is True
    assert second["event_id"] == first["event_id"]
    assert second["public_id"] == first["public_id"]
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM webhook_events WHERE event_id = 'replay-1'"
    ).fetchone()["c"]
    assert count == 1


def test_duplicate_event_id_delivered_once(conn, secrets, ok_endpoints, seeded):
    body = _body(event_id="dup-1", payload={"name": "Dup", "amount": 1500})
    sig = _signed(body, secrets)
    first = wh.ingest_event(conn, body=body, signature=sig,
                            secrets=secrets, strict=True)
    second = wh.ingest_event(conn, body=body, signature=sig,
                             secrets=secrets, strict=True)
    assert second["duplicate"] is True
    # route only the first; the duplicate must not create more deliveries
    wh.process_envelope(conn, first["envelope"], ok_endpoints)
    deliveries = delivery.list_deliveries(conn)
    endpoints = sorted(d["endpoint"] for d in deliveries)
    assert endpoints == ["stub:crm-sink", "stub:sheet-sink"]
    delivery.run_delivery_loop(conn, ok_endpoints)
    attempts = conn.execute(
        "SELECT COUNT(*) AS c FROM webhook_attempts").fetchone()["c"]
    assert attempts == 2  # exactly one attempt per endpoint
    assert wh.event_status(conn, "dup-1") == "delivered"


def test_enqueue_delivery_is_idempotent(conn):
    d1 = delivery.enqueue_delivery(conn, "evt-x", "stub:crm-sink", now=T0)
    d2 = delivery.enqueue_delivery(conn, "evt-x", "stub:crm-sink", now=T0)
    assert d1["id"] == d2["id"]
    assert len(delivery.list_deliveries(conn)) == 1


# ---------------------------------------------------------------------------
# Envelope normalization
# ---------------------------------------------------------------------------

def test_normalize_envelope_happy_path():
    env = wh.normalize_envelope({
        "source": "demo-form", "event_type": "lead.created",
        "event_id": "e1", "occurred_at": "2026-10-23T12:00:00+00:00",
        "payload": {"a": 1},
    })
    assert env["envelope_version"] == "1.0"
    assert env["event_id"] == "e1"
    assert env["payload"] == {"a": 1}


def test_normalize_envelope_generates_event_id_and_defaults():
    env = wh.normalize_envelope({"source": "s", "event_type": "t"})
    assert env["event_id"].startswith("evt-")
    assert env["payload"] == {}
    assert isinstance(env["occurred_at"], str)


@pytest.mark.parametrize("bad", [
    "not-a-dict", 123, None, [1, 2],
    {"event_type": "t", "payload": {}},                    # missing source
    {"source": 42, "event_type": "t"},                     # bad source type
    {"source": "s", "payload": {}},                        # missing event_type
    {"source": "s", "event_type": "t", "payload": "str"},  # bad payload type
    {"source": "s", "event_type": "t", "payload": [1]},    # bad payload type
])
def test_normalize_envelope_rejects_malformed(bad):
    with pytest.raises(wh.EnvelopeError):
        wh.normalize_envelope(bad)


def test_normalize_envelope_empty_event_id_is_regenerated():
    # Empty event_id is treated as missing: a fresh id is generated.
    env = wh.normalize_envelope(
        {"source": "s", "event_type": "t", "event_id": ""})
    assert env["event_id"].startswith("evt-")


def test_redacted_summary_never_contains_values():
    summary = wh.redacted_summary({"ssn": "123-45-6789", "amount": 999})
    assert summary["keys"] == ["amount", "ssn"]
    assert "123-45-6789" not in json.dumps(summary)
    assert "999" not in json.dumps(summary)


# ---------------------------------------------------------------------------
# Routing rules: matching, CRUD, versioning
# ---------------------------------------------------------------------------

def test_rule_crud_and_version_bump(conn):
    rule = router.create_rule(
        conn, name="r1", event_type="lead.created",
        conditions=[{"field": "payload.amount", "op": "gte", "value": 100}],
        actions=[{"type": "log", "message": "hi"}],
    )
    assert rule["version"] == 1
    assert router.get_rule(conn, rule["id"])["name"] == "r1"
    updated = router.update_rule(conn, rule["id"], priority=5)
    assert updated["version"] == 2
    assert updated["priority"] == 5
    router.delete_rule(conn, rule["id"])
    with pytest.raises(KeyError):
        router.get_rule(conn, rule["id"])


def test_rule_create_validates(conn):
    with pytest.raises(router.RuleError):
        router.create_rule(conn, name="", actions=[])
    with pytest.raises(router.RuleError):
        router.create_rule(conn, name="bad",
                           actions=[{"type": "forward"}])  # missing endpoint
    with pytest.raises(router.RuleError):
        router.create_rule(conn, name="bad2",
                           conditions=[{"field": "x", "op": "bogus"}])
    with pytest.raises(router.RuleError):
        router.create_rule(conn, name="bad3",
                           actions=[{"type": "teleport"}])
    router.create_rule(conn, name="dupname", actions=[])
    with pytest.raises(router.RuleError):
        router.create_rule(conn, name="dupname", actions=[])


def test_rule_matching_event_type_wildcard_disabled(conn):
    router.create_rule(conn, name="specific", event_type="lead.created",
                       actions=[{"type": "log"}])
    router.create_rule(conn, name="wild", event_type="*",
                       actions=[{"type": "log"}])
    router.create_rule(conn, name="off", event_type="*",
                       actions=[{"type": "log"}], enabled=False)
    env = {"event_id": "e", "source": "s", "event_type": "lead.created",
           "payload": {}}
    matched = [r["name"] for r in router.match_rules(conn, env)]
    assert matched == ["specific", "wild"]
    env2 = dict(env, event_type="other.thing")
    assert [r["name"] for r in router.match_rules(conn, env2)] == ["wild"]


@pytest.mark.parametrize("op,field_value,want,expected", [
    ("eq", 5, 5, True), ("eq", 5, 6, False),
    ("ne", 5, 6, True), ("ne", 5, 5, False),
    ("gt", 5, 4, True), ("gt", 4, 5, False),
    ("gte", 5, 5, True), ("gte", 4, 5, False),
    ("lt", 4, 5, True), ("lt", 5, 4, False),
    ("lte", 5, 5, True), ("lte", 6, 5, False),
    ("contains", "hello world", "world", True),
    ("contains", "hello", "zzz", False),
    ("startswith", "lead.created", "lead.", True),
    ("startswith", "lead.created", "x", False),
    ("exists", "anything", True, True),
    ("in", "b", ["a", "b"], True), ("in", "z", ["a", "b"], False),
])
def test_condition_operators(conn, op, field_value, want, expected):
    router.create_rule(
        conn, name=f"cond-{op}-{field_value}-{want}",
        conditions=[{"field": "payload.v", "op": op, "value": want}],
        actions=[{"type": "log"}],
    )
    env = {"event_id": "e", "source": "s", "event_type": "t",
           "payload": {"v": field_value}}
    matched = router.match_rules(conn, env)
    assert (len(matched) == 1) == expected


def test_exists_false_and_missing_field_never_match(conn):
    router.create_rule(
        conn, name="exists-false",
        conditions=[{"field": "payload.nope", "op": "exists", "value": False}],
        actions=[{"type": "log"}],
    )
    router.create_rule(
        conn, name="eq-missing",
        conditions=[{"field": "payload.nope", "op": "eq", "value": 1}],
        actions=[{"type": "log"}],
    )
    env = {"event_id": "e", "source": "s", "event_type": "t", "payload": {}}
    assert [r["name"] for r in router.match_rules(conn, env)] == ["exists-false"]


def test_condition_type_mismatch_never_matches_and_never_crashes(conn):
    router.create_rule(
        conn, name="mismatch",
        conditions=[{"field": "payload.v", "op": "gt", "value": 10}],
        actions=[{"type": "log"}],
    )
    env = {"event_id": "e", "source": "s", "event_type": "t",
           "payload": {"v": "not-a-number"}}
    assert router.match_rules(conn, env) == []


def test_priority_ordering(conn):
    router.create_rule(conn, name="low-pri", priority=200,
                       actions=[{"type": "log"}])
    router.create_rule(conn, name="high-pri", priority=10,
                       actions=[{"type": "log"}])
    env = {"event_id": "e", "source": "s", "event_type": "t", "payload": {}}
    assert [r["name"] for r in router.match_rules(conn, env)] == ["high-pri", "low-pri"]
    plan = router.plan_actions(conn, env)
    assert [p["rule_name"] for p in plan] == ["high-pri", "low-pri"]


# ---------------------------------------------------------------------------
# dry-run parity + no side effects
# ---------------------------------------------------------------------------

def test_dry_run_parity_with_real_run(conn, secrets, ok_endpoints, seeded, capsys):
    body = _body(event_id="parity-1",
                 payload={"name": "Parity", "amount": 2500})
    sig = _signed(body, secrets)
    result = wh.ingest_event(conn, body=body, signature=sig,
                             secrets=secrets, strict=True)
    envelope = result["envelope"]
    dry = router.dry_run(conn, envelope)
    plan = router.plan_actions(conn, envelope)
    assert [a["action"] for a in dry["actions"]] == [p["action"] for p in plan]
    assert dry["matched_rules"] == [
        {"id": r["id"], "name": r["name"], "version": r["version"],
         "priority": r["priority"]}
        for r in router.match_rules(conn, envelope)
    ]
    assert dry["would_forward_to"] == ["stub:crm-sink", "stub:sheet-sink"]
    # dry-run must not execute anything
    assert delivery.list_deliveries(conn) == []
    assert conn.execute("SELECT COUNT(*) AS c FROM webhook_derived").fetchone()["c"] == 0
    # now the real run: executed actions equal the dry-run plan exactly
    outcome = wh.process_envelope(conn, envelope, ok_endpoints)
    assert outcome["ok"] is True
    executed = outcome["plan"]["executed"]
    assert [e["action"] for e in executed] == [a["action"] for a in dry["actions"]]
    assert [e["rule_name"] for e in executed] == [a["rule_name"] for a in dry["actions"]]


def test_transform_action_stores_derived_and_never_reroutes(conn, ok_endpoints):
    router.create_rule(
        conn, name="xform", event_type="booking.created",
        actions=[{"type": "transform", "fields": {
            "ref": "payload.booking_ref",
            "cal": {"literal": "demo"},
            "missing": "payload.nope",
        }}],
    )
    env = {"event_id": "x1", "source": "demo-calendar",
           "event_type": "booking.created", "occurred_at": "t",
           "payload": {"booking_ref": "B-1"}}
    wh.process_envelope(conn, env, ok_endpoints)
    rows = conn.execute("SELECT * FROM webhook_derived").fetchall()
    assert len(rows) == 1
    derived = json.loads(rows[0]["derived_json"])
    assert derived["ref"] == "B-1"
    assert derived["cal"] == "demo"
    assert derived["missing"] is None
    assert derived["derived_from"] == "x1"
    # no new event was created for the derived envelope (no routing loop)
    assert conn.execute("SELECT COUNT(*) AS c FROM webhook_events").fetchone()["c"] == 0


def test_log_action_emits_redacted_line(conn, capsys):
    router.create_rule(
        conn, name="logrule",
        actions=[{"type": "log", "message": "saw event"}],
    )
    env = {"event_id": "l1", "source": "s", "event_type": "t",
           "occurred_at": "t", "payload": {"secret_field": "TOPSECRET-VALUE-123"}}
    wh.process_envelope(conn, env, {})
    out = capsys.readouterr().out
    assert "TOPSECRET-VALUE-123" not in out
    assert "secret_field" in out  # key names are fine


# ---------------------------------------------------------------------------
# Delivery: retry schedule with injectable clock
# ---------------------------------------------------------------------------

def test_backoff_schedule_exact(conn, monkeypatch):
    # Patch the circuit threshold sky-high so this test measures pure backoff.
    monkeypatch.setattr(delivery, "CIRCUIT_FAILURE_THRESHOLD", 10 ** 6)
    d = _enqueue(conn, "evt-bk", "stub:fail", now=T0, max_attempts=5)
    endpoints = _failing_endpoints()
    expected_next = [30, 90, 210, 450]  # seconds after T0 for attempts 1..4
    moment = T0
    for i, expected in enumerate(expected_next):
        stats = delivery.run_delivery_loop(conn, endpoints, now=moment)
        assert stats["attempted"] == 1 and stats["failed"] == 1
        row = conn.execute(
            "SELECT attempts, next_attempt_at, state FROM webhook_deliveries WHERE id = ?",
            (d["id"],),
        ).fetchone()
        assert row["attempts"] == i + 1
        assert row["next_attempt_at"] == (T0 + timedelta(seconds=expected)).isoformat()
        moment = T0 + timedelta(seconds=expected)
    # 5th attempt exhausts max_attempts -> dead-lettered
    stats = delivery.run_delivery_loop(conn, endpoints, now=moment)
    assert stats["dead_lettered"] == 1
    row = conn.execute(
        "SELECT state, attempts FROM webhook_deliveries WHERE id = ?", (d["id"],)
    ).fetchone()
    assert row["state"] == "dead_lettered" and row["attempts"] == 5


def test_dead_letter_after_max_attempts(conn, monkeypatch):
    monkeypatch.setattr(delivery, "CIRCUIT_FAILURE_THRESHOLD", 10 ** 6)
    body = _body(event_id="dl-1")
    conn.execute(
        "INSERT INTO webhook_events (public_id, event_id, source, event_type,"
        " envelope_json, signature_ok, created_at)"
        " VALUES ('EVT-000101','dl-1','demo-form','lead.created', ?, 1, ?)",
        (json.dumps({"event_id": "dl-1", "source": "demo-form",
                     "event_type": "lead.created", "payload": {}}), T0.isoformat()),
    )
    conn.commit()
    wh.record_lineage(conn, "dl-1", "received", actor="t")
    wh.record_lineage(conn, "dl-1", "routed", from_state="received", actor="t")
    delivery.enqueue_delivery(conn, "dl-1", "stub:fail", now=T0, max_attempts=3)
    endpoints = _failing_endpoints()
    moment = T0
    for _ in range(3):
        delivery.run_delivery_loop(conn, endpoints, now=moment)
        row = conn.execute(
            "SELECT next_attempt_at FROM webhook_deliveries WHERE event_id='dl-1'"
        ).fetchone()
        moment = datetime.fromisoformat(row["next_attempt_at"])
    dead = delivery.list_dead_letters(conn)
    assert len(dead) == 1
    assert dead[0]["reason"] == "max_attempts_exceeded"
    assert dead[0]["event_id"] == "dl-1"
    assert "stub endpoint down" in (dead[0]["detail_json"] or "")
    assert wh.event_status(conn, "dl-1") == "dead_lettered"
    attempts = conn.execute(
        "SELECT COUNT(*) AS c FROM webhook_attempts").fetchone()["c"]
    assert attempts == 3  # every attempt logged
    # further loop runs attempt nothing more for this delivery
    stats = delivery.run_delivery_loop(conn, endpoints, now=moment)
    assert stats["attempted"] == 0


def test_successful_retry_recovers(conn):
    calls = {"n": 0}

    def flaky(delivery_row, envelope):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("flaky")
        return {"ok": True}

    _enqueue(conn, "evt-flaky", "stub:flaky", now=T0)
    moment = T0
    for _ in range(3):
        delivery.run_delivery_loop(conn, {"stub:flaky": flaky}, now=moment)
        row = conn.execute(
            "SELECT next_attempt_at, state FROM webhook_deliveries WHERE event_id='evt-flaky'"
        ).fetchone()
        if row["state"] == "queued":
            moment = datetime.fromisoformat(row["next_attempt_at"])
    row = conn.execute(
        "SELECT state, attempts FROM webhook_deliveries WHERE event_id='evt-flaky'"
    ).fetchone()
    assert row["state"] == "delivered" and row["attempts"] == 3


def test_unknown_endpoint_dead_letters_immediately(conn):
    body = _body(event_id="unk-1")
    conn.execute(
        "INSERT INTO webhook_events (public_id, event_id, source, event_type,"
        " envelope_json, signature_ok, created_at)"
        " VALUES ('EVT-000102','unk-1','demo-form','lead.created', ?, 1, ?)",
        (json.dumps({"event_id": "unk-1", "source": "demo-form",
                     "event_type": "lead.created", "payload": {}}), T0.isoformat()),
    )
    conn.commit()
    wh.record_lineage(conn, "unk-1", "received", actor="t")
    delivery.enqueue_delivery(conn, "unk-1", "stub:does-not-exist", now=T0)
    stats = delivery.run_delivery_loop(conn, {}, now=T0)
    assert stats["dead_lettered"] == 1
    dead = delivery.list_dead_letters(conn)
    assert dead[0]["reason"] == "unknown_endpoint"
    assert wh.event_status(conn, "unk-1") == "dead_lettered"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def _open_circuit(conn, event_id="evt-cx"):
    """Drive one delivery to 3 consecutive failures; return (circuit, due_at)."""
    _enqueue(conn, event_id, "stub:fail", now=T0)
    endpoints = _failing_endpoints()
    moment = T0
    for _ in range(3):
        delivery.run_delivery_loop(conn, endpoints, now=moment)
        row = conn.execute(
            "SELECT next_attempt_at FROM webhook_deliveries WHERE event_id=?",
            (event_id,),
        ).fetchone()
        moment = datetime.fromisoformat(row["next_attempt_at"])
    circuit = delivery.get_circuit(conn, "stub:fail")
    assert circuit["state"] == "open"
    assert circuit["consecutive_failures"] == 3
    return circuit, moment


def test_circuit_opens_after_threshold_and_skips(conn):
    circuit, _ = _open_circuit(conn, "evt-c1")
    open_until = datetime.fromisoformat(circuit["half_open_after"])
    # a new delivery arrives while the circuit is open -> skipped, not attempted
    before_probe = open_until - timedelta(seconds=30)
    delivery.enqueue_delivery(conn, "evt-c1b", "stub:fail", now=before_probe)
    stats = delivery.run_delivery_loop(conn, _failing_endpoints(), now=before_probe)
    assert stats["skipped_circuit_open"] == 1
    assert stats["attempted"] == 0
    attempts = conn.execute(
        "SELECT COUNT(*) AS c FROM webhook_attempts").fetchone()["c"]
    assert attempts == 3


def test_circuit_half_open_probe_fails_reopens(conn):
    circuit, due_at = _open_circuit(conn, "evt-c2")
    probe_at = max(datetime.fromisoformat(circuit["half_open_after"]),
                   due_at) + timedelta(seconds=1)
    stats = delivery.run_delivery_loop(conn, _failing_endpoints(), now=probe_at)
    assert stats["attempted"] == 1  # exactly one half-open probe
    circuit = delivery.get_circuit(conn, "stub:fail")
    assert circuit["state"] == "open"  # probe failed -> re-opened
    assert circuit["consecutive_failures"] == 4


def test_circuit_half_open_probe_succeeds_recovers(conn):
    circuit, due_at = _open_circuit(conn, "evt-c3")
    probe_at = max(datetime.fromisoformat(circuit["half_open_after"]),
                   due_at) + timedelta(seconds=1)
    stats = delivery.run_delivery_loop(
        conn, {"stub:fail": lambda d, e: {"ok": True}}, now=probe_at)
    assert stats["delivered"] == 1
    circuit = delivery.get_circuit(conn, "stub:fail")
    assert circuit["state"] == "closed"
    assert circuit["consecutive_failures"] == 0


def test_retry_storm_is_bounded(conn):
    # 20 deliveries hammering one failing endpoint: the circuit breaker must
    # bound total attempts — no unbounded retry storm.
    for i in range(20):
        _enqueue(conn, f"evt-storm-{i}", "stub:fail", now=T0)
    endpoints = _failing_endpoints()
    total_attempted = 0
    moment = T0
    for run in range(6):
        stats = delivery.run_delivery_loop(conn, endpoints, now=moment)
        total_attempted += stats["attempted"]
        # first run: 3 attempts then circuit opens, rest skipped
        # later runs: at most one half-open probe each
        assert stats["attempted"] <= 3
        moment = moment + timedelta(seconds=delivery.CIRCUIT_COOLDOWN_SECONDS + 1)
    assert total_attempted <= 3 + 5  # 3 to open + one probe per later run
    assert delivery.get_circuit(conn, "stub:fail")["state"] == "open"


# ---------------------------------------------------------------------------
# Poison-event isolation + fuzz
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,source_hint", [
    (b"[1,2,3]", None),
    (b'"just a string"', None),
    (b"{not valid json", None),
    (b"", None),
    (json.dumps({"event_type": "t"}).encode(), None),            # missing source
    (json.dumps({"source": "s"}).encode(), None),                # missing event_type
    (json.dumps({"source": "s", "event_type": "t",
                 "payload": "nope"}).encode(), None),           # bad payload
    (json.dumps({"source": 1, "event_type": "t"}).encode(), None),
])
def test_poison_payloads_dead_lettered_never_crash(conn, raw, source_hint):
    stats = wh.process_batch(
        conn, [{"body": raw, "signature": None, "source_hint": source_hint}],
        secrets={}, strict=False, endpoints={},
    )
    assert stats["poison"] == 1
    dead = delivery.list_dead_letters(conn)
    assert len(dead) == 1
    assert dead[0]["reason"] == "malformed_envelope"
    assert wh.event_status(conn, dead[0]["event_id"]) == "dead_lettered"


def test_fuzz_5000_malformed_payloads_zero_crashes(conn, secrets):
    rng = random.Random(20261023)
    items = []
    for i in range(5000):
        kind = rng.randrange(8)
        if kind == 0:
            body = rng.choice([b"[1,2]", b'"s"', b"42", b"null", b"{oops", b""])
        elif kind == 1:
            body = json.dumps({"source": rng.choice(["s", 1, None, []]),
                                     "event_type": rng.choice(["t", {}, 5])}).encode()
        elif kind == 2:
            body = json.dumps({"source": "demo-form", "event_type": "lead.created",
                               "event_id": f"fuzz-{i}",
                               "payload": rng.choice(["x", [1], 5, None])}).encode()
        elif kind == 3:
            body = json.dumps({"a": {"b": [{"c": None}]},
                               "z": "x" * rng.randrange(0, 5000)}).encode()
        elif kind == 4:
            body = json.dumps({"source": "demo-form", "event_type": "t",
                               "payload": {f"k{j}": j for j in range(50)}}).encode()
        elif kind == 5:
            body = ("\U0001f4a5" * 100).encode()  # invalid JSON (bare unicode)
        elif kind == 6:
            body = json.dumps([{"source": "s"}]).encode()
        else:
            body = json.dumps({"source": "demo-form", "event_type": "t",
                               "event_id": f"fuzz-{i}", "payload": {},
                               "extra": [None, True, {"deep": [1, {"deeper": "x"}]}]}).encode()
        sig = None
        if rng.random() < 0.3 and body.startswith(b"{"):
            try:
                sig = wh.sign("wrong-secret", body)
            except Exception:
                sig = None
        items.append({"body": body, "signature": sig, "source_hint": None})
    stats = wh.process_batch(conn, items, secrets=secrets, strict=False,
                             endpoints={"stub:crm-sink": lambda d, e: {"ok": True}})
    # every item accounted for exactly once at ingest, and exactly once
    # after ingest (accepted=True covers poison too — poison is stored).
    assert stats["accepted"] + stats["rejected"] == 5000, stats
    assert (stats["poison"] + stats["duplicate"] + stats["routed"]
            + stats["routing_failed"] == stats["accepted"]), stats
    # every event reached a terminal state
    non_terminal = conn.execute(
        """
        SELECT COUNT(*) AS c FROM webhook_events e WHERE (
            SELECT to_state FROM webhook_lineage l
            WHERE l.event_id = e.event_id ORDER BY l.id DESC LIMIT 1
        ) NOT IN ('delivered','dead_lettered','rejected')
        """
    ).fetchone()["c"]
    assert non_terminal == 0


def test_routing_error_isolated_to_dead_letter_batch_continues(conn, secrets, ok_endpoints):
    # A rule whose transform spec is invalid raises inside routing;
    # the event must dead-letter and the batch must continue.
    router.create_rule(
        conn, name="bad-transform", event_type="*",
        actions=[{"type": "transform", "fields": {"x": 42}}],  # invalid spec
    )
    good_body = _body(event_id="good-after-bad", payload={"a": 1})
    sig = wh.sign(secrets["demo-form"], good_body)
    stats = wh.process_batch(
        conn,
        [{"body": b"{bad json", "signature": None},
         {"body": good_body, "signature": sig}],
        secrets=secrets, strict=True, endpoints=ok_endpoints,
    )
    assert stats["poison"] == 1
    assert stats["routing_failed"] == 1  # transform spec raised -> dead-letter
    dead = delivery.list_dead_letters(conn)
    reasons = sorted(d["reason"] for d in dead)
    assert reasons == ["malformed_envelope", "routing_error"]
    routing_dl = [d for d in dead if d["reason"] == "routing_error"][0]
    assert wh.event_status(conn, routing_dl["event_id"]) == "dead_lettered"


# ---------------------------------------------------------------------------
# Lineage audit + terminal states
# ---------------------------------------------------------------------------

def test_full_lineage_received_routed_queued_delivered(conn, secrets, ok_endpoints, seeded):
    body = _body(event_id="lin-1", payload={"name": "Lin", "amount": 10})
    sig = _signed(body, secrets)
    result = wh.ingest_event(conn, body=body, signature=sig,
                             secrets=secrets, strict=True)
    wh.process_envelope(conn, result["envelope"], ok_endpoints)
    delivery.run_delivery_loop(conn, ok_endpoints)
    chain = [(l["from_state"], l["to_state"]) for l in wh.get_lineage(conn, "lin-1")]
    assert chain == [
        (None, "received"),
        ("received", "routed"),
        ("routed", "queued"),
        ("queued", "delivered"),
    ]
    assert all(l["actor"] for l in wh.get_lineage(conn, "lin-1"))


def test_every_attempt_logged(conn, monkeypatch):
    monkeypatch.setattr(delivery, "CIRCUIT_FAILURE_THRESHOLD", 10 ** 6)
    _enqueue(conn, "evt-al", "stub:fail", now=T0, max_attempts=2)
    endpoints = _failing_endpoints()
    delivery.run_delivery_loop(conn, endpoints, now=T0)
    nxt = conn.execute(
        "SELECT next_attempt_at FROM webhook_deliveries WHERE event_id='evt-al'"
    ).fetchone()["next_attempt_at"]
    delivery.run_delivery_loop(conn, endpoints,
                               now=datetime.fromisoformat(nxt))
    rows = conn.execute(
        "SELECT attempt_no, ok FROM webhook_attempts ORDER BY attempt_no"
    ).fetchall()
    assert [(r["attempt_no"], r["ok"]) for r in rows] == [(1, 0), (2, 0)]


def test_event_with_log_only_actions_settles_delivered(conn, ok_endpoints):
    router.create_rule(conn, name="logonly",
                       actions=[{"type": "log", "message": "x"}])
    env = {"event_id": "lo1", "source": "s", "event_type": "t",
           "occurred_at": "t", "payload": {}}
    wh.process_envelope(conn, env, ok_endpoints)
    assert delivery.list_deliveries(conn) == []
    assert wh.event_status(conn, "lo1") == "delivered"


def test_every_event_reaches_terminal_state_mixed_batch(conn, secrets, monkeypatch):
    monkeypatch.setattr(delivery, "CIRCUIT_FAILURE_THRESHOLD", 10 ** 6)
    router.create_rule(
        conn, name="to-fail", event_type="fail.me",
        actions=[{"type": "forward", "endpoint": "stub:fail"}],
    )
    router.create_rule(
        conn, name="to-ok", event_type="ok.me",
        actions=[{"type": "forward", "endpoint": "stub:ok"}],
    )
    items = []
    for i in range(6):  # signed, routable to failing endpoint
        body = json.dumps({"source": "demo-form", "event_type": "fail.me",
                           "event_id": f"mix-fail-{i}", "payload": {}}).encode()
        items.append({"body": body,
                      "signature": wh.sign(secrets["demo-form"], body)})
    for i in range(4):  # signed, routable to good endpoint
        body = json.dumps({"source": "demo-form", "event_type": "ok.me",
                           "event_id": f"mix-ok-{i}", "payload": {}}).encode()
        items.append({"body": body,
                      "signature": wh.sign(secrets["demo-form"], body)})
    items.append({"body": json.dumps({"source": "demo-form",
                                      "event_type": "ok.me",
                                      "event_id": "mix-unsigned",
                                      "payload": {}}).encode(),
                  "signature": ""})  # unsigned -> rejected (strict)
    items.append({"body": b"not json at all", "signature": None})  # poison
    items.append({"body": json.dumps({"source": "demo-form"}).encode(),
                  "signature": None})  # poison (no event_type)
    endpoints = {"stub:fail": _failing_endpoints()["stub:fail"],
                 "stub:ok": lambda d, e: {"ok": True}}
    stats = wh.process_batch(conn, items, secrets=secrets, strict=True,
                             endpoints=endpoints)
    # accepted=True covers poison too (poison events are stored); the two
    # invariants below pin the accounting exactly.
    assert stats["accepted"] + stats["rejected"] == 13, stats
    assert (stats["poison"] + stats["duplicate"] + stats["routed"]
            + stats["routing_failed"] == stats["accepted"]), stats
    # drain the retry queue with an advancing clock: jump to the latest
    # next_attempt_at so every queued delivery is due on each pass
    for _ in range(8):
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM webhook_deliveries WHERE state='queued'"
        ).fetchone()["c"]
        if not pending:
            break
        nxt = conn.execute(
            "SELECT MAX(next_attempt_at) AS m FROM webhook_deliveries WHERE state='queued'"
        ).fetchone()["m"]
        delivery.run_delivery_loop(conn, endpoints,
                                   now=datetime.fromisoformat(nxt))
    terminal = wh.TERMINAL_STATES
    bad = conn.execute(
        """
        SELECT e.event_id, (
            SELECT to_state FROM webhook_lineage l
            WHERE l.event_id = e.event_id ORDER BY l.id DESC LIMIT 1
        ) AS st
        FROM webhook_events e
        """
    ).fetchall()
    assert all(r["st"] in terminal for r in bad), [
        (r["event_id"], r["st"]) for r in bad if r["st"] not in terminal]
    assert len(bad) == 13  # 11 stored + 2 poison rows
    delivered = [r for r in bad if r["st"] == "delivered"]
    dead = [r for r in bad if r["st"] == "dead_lettered"]
    rejected = [r for r in bad if r["st"] == "rejected"]
    assert len(delivered) == 4 and len(dead) == 8 and len(rejected) == 1


# ---------------------------------------------------------------------------
# Dead-letter replay
# ---------------------------------------------------------------------------

def test_replay_delivery_dead_letter_requeues(conn):
    conn.execute(
        "INSERT INTO webhook_events (public_id, event_id, source, event_type,"
        " envelope_json, signature_ok, created_at)"
        " VALUES ('EVT-000201','rp-1','demo-form','lead.created', ?, 1, ?)",
        (json.dumps({"event_id": "rp-1", "source": "demo-form",
                     "event_type": "lead.created", "payload": {}}), T0.isoformat()),
    )
    conn.commit()
    wh.record_lineage(conn, "rp-1", "received", actor="t")
    wh.record_lineage(conn, "rp-1", "routed", from_state="received", actor="t")
    delivery.enqueue_delivery(conn, "rp-1", "stub:fail", now=T0, max_attempts=1)
    delivery.run_delivery_loop(conn, _failing_endpoints(), now=T0)
    dead = delivery.list_dead_letters(conn)
    assert len(dead) == 1 and dead[0]["reason"] == "max_attempts_exceeded"
    result = delivery.replay_dead_letter(
        conn, dead[0]["id"], {"stub:fail": lambda d, e: {"ok": True}}, now=T0)
    assert result["replayed"] is True
    assert result["loop"]["delivered"] == 1
    assert wh.event_status(conn, "rp-1") == "delivered"
    row = conn.execute(
        "SELECT replayed FROM webhook_dead_letters WHERE id = ?", (dead[0]["id"],)
    ).fetchone()
    assert row["replayed"] == 1


def test_replay_malformed_dead_letter_refused(conn):
    wh.process_batch(conn, [{"body": b"{bad", "signature": None}],
                     secrets={}, strict=False, endpoints={})
    dead = delivery.list_dead_letters(conn)
    assert dead[0]["reason"] == "malformed_envelope"
    with pytest.raises(ValueError):
        delivery.replay_dead_letter(conn, dead[0]["id"], {})


# ---------------------------------------------------------------------------
# Migration rollback (for real)
# ---------------------------------------------------------------------------

def test_migration_007_down_step_rolls_back_for_real(conn):
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'webhook_%'")]
    assert len(tables) == 8
    assert rollback_migration(conn, "007_webhook_hub.sql") is True
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'webhook_%'")]
    assert tables == []
    applied = [r["name"] for r in conn.execute("SELECT name FROM schema_migrations")]
    assert "007_webhook_hub.sql" not in applied
    # re-apply works
    assert run_migrations(conn) == ["007_webhook_hub.sql"]
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'webhook_%'")]
    assert len(tables) == 8
