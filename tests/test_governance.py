"""Project P05 — service tests (stdlib only). All data synthetic."""
import json

import pytest

from mavenu.db import applied_migrations, rollback_migration, run_migrations
from mavenu.governance import (
    GovError, ack_alert, add_incident_note, attempt_job, create_check,
    create_incident, create_job, create_policy, create_rule, create_runbook,
    due_jobs, evaluate_rules, get_alert, get_check, get_check_by_name,
    get_check_run, get_incident, get_job, get_policy, get_policy_by_name,
    get_rule, get_runbook, get_runbook_by_name, list_alerts, list_checks,
    list_dead_letters, list_incidents, list_jobs, list_policies,
    list_runbooks, next_delay_s, replay_dead_letter, resolve_alert,
    run_check, runbook_for_key, seed_demo_data, should_retry, silence_rule,
    status_summary, supersede_policy, supersede_runbook, transition_incident,
    walkthrough,
)

T0 = "2026-11-08T00:00:00+00:00"


def _pending_calls(conn, n):
    _pending_calls.counter = getattr(_pending_calls, "counter", 0) + 1
    offset = _pending_calls.counter * 1000
    for i in range(n):
        j = offset + i
        conn.execute(
            """INSERT INTO missed_calls
               (public_id, missed_at, caller_id_masked, caller_id_hash,
                state, dedup_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (f"MC-P05-{j:04d}", "2026-11-08T00:00:00+00:00", "••••••0001",
             f"hash-{j}", f"dedup-{j}", T0, T0),
        )
    conn.commit()


class _Disk:
    def __init__(self, total, free):
        self.total = total
        self.free = free


# ---------------------------------------------------------------------------
# Checks + probes
# ---------------------------------------------------------------------------
def test_create_and_run_db_check_passes(conn):
    check = create_check(conn, "DB-OK", "db", "liveness", "db_reachable",
                         warn_threshold=0, fail_threshold=0)
    run = run_check(conn, check["id"], now=T0)
    assert run["status"] == "pass"
    assert run["value_json"] == 0
    assert run["detail_json"]["tables"] > 0
    assert run["alerts"] == []
    assert get_check_run(conn, run["id"])["id"] == run["id"]


def test_storage_probe_thresholds_with_injected_disk_usage(conn):
    check = create_check(conn, "STORAGE", "storage", "readiness", "storage_tmp",
                         {"path": "/tmp"}, warn_threshold=80, fail_threshold=95)
    run = run_check(conn, check["id"], now=T0,
                    disk_usage_fn=lambda p: _Disk(1000, 500))
    assert run["status"] == "pass" and run["value_json"] == 50.0
    run = run_check(conn, check["id"], now=T0,
                    disk_usage_fn=lambda p: _Disk(1000, 150))
    assert run["status"] == "degraded" and run["value_json"] == 85.0
    run = run_check(conn, check["id"], now=T0,
                    disk_usage_fn=lambda p: _Disk(1000, 20))
    assert run["status"] == "fail" and run["value_json"] == 98.0


def test_queue_depth_probe_counts_pending_calls(conn):
    _pending_calls(conn, 3)
    check = create_check(conn, "QUEUE", "queue", "readiness", "queue_depth",
                         {"table": "missed_calls", "value": "pending"},
                         warn_threshold=5, fail_threshold=20)
    run = run_check(conn, check["id"], now=T0)
    assert run["status"] == "pass" and run["value_json"] == 3
    _pending_calls(conn, 4)
    run = run_check(conn, check["id"], now=T0)
    assert run["status"] == "degraded" and run["value_json"] == 7
    _pending_calls(conn, 14)
    run = run_check(conn, check["id"], now=T0)
    assert run["status"] == "fail" and run["value_json"] == 21


def test_migrations_probe_passes_when_current(conn):
    check = create_check(conn, "MIG", "db", "readiness", "migrations_current",
                         warn_threshold=0, fail_threshold=0)
    run = run_check(conn, check["id"], now=T0)
    assert run["status"] == "pass" and run["value_json"] == 0


def test_check_validation_rejects_bad_inputs(conn):
    with pytest.raises(GovError):
        create_check(conn, "BAD", "db", "liveness", "no_such_probe")
    with pytest.raises(GovError):
        create_check(conn, "BAD", "db", "liveness", "queue_depth",
                     {"table": "users", "value": "pending"})
    with pytest.raises(GovError):
        create_check(conn, "BAD", "db", "liveness", "queue_depth",
                     {"table": "missed_calls", "value": "zap"})
    with pytest.raises(GovError):
        create_check(conn, "BAD!", "db", "liveness", "db_reachable")
    with pytest.raises(GovError):
        create_check(conn, "BAD", "db", "liveness", "db_reachable",
                     warn_threshold=5, fail_threshold=1)
    create_check(conn, "DUP", "db", "liveness", "db_reachable")
    with pytest.raises(GovError):
        create_check(conn, "DUP", "db", "liveness", "db_reachable")
    with pytest.raises(GovError):
        get_check(conn, 99999)
    with pytest.raises(GovError):
        get_check_by_name(conn, "NOPE")


def test_status_summary_aggregates_worst_and_unknown(conn):
    assert status_summary(conn)["overall"] == "pass"  # no checks yet
    c1 = create_check(conn, "A", "db", "liveness", "db_reachable")
    summary = status_summary(conn)
    assert summary["overall"] == "unknown"
    run_check(conn, c1["id"], now=T0)
    assert status_summary(conn)["overall"] == "pass"
    c2 = create_check(conn, "B", "storage", "readiness", "storage_tmp",
                      {"path": "/tmp"}, warn_threshold=0, fail_threshold=0)
    run_check(conn, c2["id"], now=T0, disk_usage_fn=lambda p: _Disk(1000, 500))
    assert status_summary(conn)["overall"] == "fail"
    assert status_summary(conn)["open_alerts"] == 0
    assert status_summary(conn)["open_incidents"] == 0


# ---------------------------------------------------------------------------
# Policies + jobs
# ---------------------------------------------------------------------------
def test_backoff_schedule_is_exponential_and_capped(conn):
    policy = create_policy(conn, "P", max_attempts=5, backoff_base_s=30,
                           backoff_cap_s=3600, jitter_max_s=0)
    assert [next_delay_s(policy, n) for n in (1, 2, 3, 4, 5)] == \
        [30.0, 60.0, 120.0, 240.0, 480.0]
    capped = create_policy(conn, "C", max_attempts=5, backoff_base_s=100,
                           backoff_cap_s=150, jitter_max_s=0)
    assert [next_delay_s(capped, n) for n in (1, 2, 3)] == [100.0, 150.0, 150.0]


def test_jitter_is_deterministic_and_bounded(conn):
    policy = create_policy(conn, "J", max_attempts=5, backoff_base_s=30,
                           backoff_cap_s=3600, jitter_max_s=5)
    d1 = next_delay_s(policy, 1)
    d2 = next_delay_s(policy, 1)
    assert d1 == d2
    assert 30.0 <= d1 <= 35.0
    assert next_delay_s(policy, 2) != next_delay_s(policy, 1)


def test_should_retry_uses_min_of_max_and_dead_letter(conn):
    policy = create_policy(conn, "R", max_attempts=5, backoff_base_s=30,
                           backoff_cap_s=3600, dead_letter_after=3)
    assert should_retry(policy, 2) is True
    assert should_retry(policy, 3) is False
    policy2 = create_policy(conn, "R2", max_attempts=2, backoff_base_s=30,
                            backoff_cap_s=3600, dead_letter_after=5)
    assert should_retry(policy2, 1) is True
    assert should_retry(policy2, 2) is False


def test_policy_validation_and_supersede(conn):
    with pytest.raises(GovError):
        create_policy(conn, "X", max_attempts=0)
    with pytest.raises(GovError):
        create_policy(conn, "X", max_attempts=5, backoff_base_s=60,
                      backoff_cap_s=30)
    with pytest.raises(GovError):
        create_policy(conn, "X", max_attempts=5, backoff_base_s=30,
                      backoff_cap_s=3600, jitter_max_s=-1)
    create_policy(conn, "X", max_attempts=3, backoff_base_s=10,
                  backoff_cap_s=60)
    with pytest.raises(GovError):
        create_policy(conn, "X", max_attempts=3, backoff_base_s=10,
                      backoff_cap_s=60)
    new = supersede_policy(conn, "X", max_attempts=4, backoff_base_s=15,
                           backoff_cap_s=120, description="v2")
    assert new["version"] == 2
    assert get_policy_by_name(conn, "X")["id"] == new["id"]
    old = get_policy_by_name(conn, "X", version=1)
    assert old["status"] == "superseded"
    assert old["superseded_by"] == new["id"]
    assert len(list_policies(conn)) == 1
    assert len(list_policies(conn, include_superseded=True)) == 2


def test_job_success_path(conn):
    policy = create_policy(conn, "P", max_attempts=3, backoff_base_s=30,
                           backoff_cap_s=300)
    job = create_job(conn, "JOB-1", policy["id"], {"k": "v"}, now=T0)
    assert job["status"] == "pending" and job["attempts"] == 0
    done = attempt_job(conn, job["id"], "success", now=T0)
    assert done["status"] == "succeeded" and done["attempts"] == 1
    with pytest.raises(GovError):
        attempt_job(conn, job["id"], "success")


def test_job_failure_backoff_then_dead_letter(conn):
    policy = create_policy(conn, "P", max_attempts=3, backoff_base_s=30,
                           backoff_cap_s=300, jitter_max_s=0,
                           dead_letter_after=3)
    job = create_job(conn, "JOB-2", policy["id"], now=T0)
    job = attempt_job(conn, job["id"], "failure", error="timeout", now=T0)
    assert job["status"] == "scheduled" and job["attempts"] == 1
    assert job["next_run_at"] == "2026-11-08T00:00:30+00:00"
    assert job["last_error"] == "timeout"
    job = attempt_job(conn, job["id"], "failure", error="timeout",
                      now="2026-11-08T00:00:30+00:00")
    assert job["status"] == "scheduled" and job["attempts"] == 2
    assert job["next_run_at"] == "2026-11-08T00:01:30+00:00"
    job = attempt_job(conn, job["id"], "failure", error="timeout",
                      now="2026-11-08T00:01:30+00:00")
    assert job["status"] == "dead_lettered" and job["attempts"] == 3
    dead = list_dead_letters(conn)
    assert len(dead) == 1 and dead[0]["job_id"] == job["id"]
    assert dead[0]["status"] == "open"
    with pytest.raises(GovError):
        attempt_job(conn, job["id"], "failure")


def test_due_jobs_and_replay(conn):
    policy = create_policy(conn, "P", max_attempts=2, backoff_base_s=30,
                           backoff_cap_s=300, jitter_max_s=0,
                           dead_letter_after=2)
    job = create_job(conn, "JOB-3", policy["id"], {"a": 1}, now=T0)
    assert len(due_jobs(conn, now=T0)) == 1
    assert len(due_jobs(conn, now="2026-11-07T00:00:00+00:00")) == 0
    attempt_job(conn, job["id"], "failure", now=T0)
    assert len(due_jobs(conn, now=T0)) == 0  # next run is +30s
    assert len(due_jobs(conn, now="2026-11-08T00:00:30+00:00")) == 1
    job = attempt_job(conn, job["id"], "failure",
                      now="2026-11-08T00:00:30+00:00")
    assert job["status"] == "dead_lettered"
    dead = list_dead_letters(conn)[0]
    fresh = replay_dead_letter(conn, dead["id"], now="2026-11-08T01:00:00+00:00")
    assert fresh["id"] != job["id"] and fresh["status"] == "pending"
    assert fresh["attempts"] == 0
    assert list_dead_letters(conn)[0]["status"] == "replayed"
    with pytest.raises(GovError):
        replay_dead_letter(conn, dead["id"])


# ---------------------------------------------------------------------------
# Rules + alerts
# ---------------------------------------------------------------------------
def _queue_rule_setup(conn, threshold=20, dedup=3600):
    check = create_check(conn, "Q-CHECK", "queue", "readiness", "queue_depth",
                         {"table": "missed_calls", "value": "pending"},
                         warn_threshold=5, fail_threshold=20)
    rule = create_rule(conn, "Q-RULE", "Q-CHECK", "value", "gt", threshold,
                       "high", owner="on-call", dedup_window_s=dedup)
    return check, rule


def test_rule_fires_alert_on_threshold_breach(conn):
    check, _ = _queue_rule_setup(conn)
    _pending_calls(conn, 21)
    run = run_check(conn, check["id"], now=T0)
    assert run["status"] == "fail"
    assert len(run["alerts"]) == 1
    alert = get_alert(conn, run["alerts"][0])
    assert alert["status"] == "open" and alert["severity"] == "high"
    assert alert["count"] == 1
    assert alert["detail_json"]["value"] == 21


def test_rule_dedup_bumps_count_within_window(conn):
    check, _ = _queue_rule_setup(conn)
    _pending_calls(conn, 21)
    run1 = run_check(conn, check["id"], now=T0)
    run2 = run_check(conn, check["id"], now="2026-11-08T00:30:00+00:00")
    assert run1["alerts"] == run2["alerts"]
    assert get_alert(conn, run1["alerts"][0])["count"] == 2
    run3 = run_check(conn, check["id"], now="2026-11-08T02:00:00+00:00")
    assert run3["alerts"] != run1["alerts"]  # window (1h) passed -> new alert
    assert len(list_alerts(conn, status="open")) == 2


def test_silenced_rule_does_not_fire_but_is_logged(conn):
    check, rule = _queue_rule_setup(conn)
    silence_rule(conn, rule["id"], "2026-11-09T00:00:00+00:00")
    _pending_calls(conn, 21)
    run = run_check(conn, check["id"], now=T0)
    assert run["alerts"] == []
    events = conn.execute(
        "SELECT event_type FROM gov_events WHERE entity_type = 'rule' "
        "AND event_type = 'rule.suppressed'").fetchall()
    assert len(events) == 1
    with pytest.raises(GovError):
        silence_rule(conn, rule["id"], "2026-11-07T00:00:00+00:00")


def test_alert_ack_and_resolve_transitions(conn):
    check, _ = _queue_rule_setup(conn)
    _pending_calls(conn, 21)
    run = run_check(conn, check["id"], now=T0)
    alert_id = run["alerts"][0]
    alert = ack_alert(conn, alert_id)
    assert alert["status"] == "acked"
    alert = resolve_alert(conn, alert_id)
    assert alert["status"] == "resolved"
    with pytest.raises(GovError):
        resolve_alert(conn, alert_id)  # resolved is terminal
    with pytest.raises(GovError):
        ack_alert(conn, alert_id)


def test_rule_skips_missing_metric_and_rejects_bad_inputs(conn):
    check = create_check(conn, "DB", "db", "liveness", "db_reachable")
    create_rule(conn, "MISSING-METRIC", "DB", "not_a_metric", "gt", 0,
                "low")
    run = run_check(conn, check["id"], now=T0)
    assert run["alerts"] == []
    with pytest.raises(GovError):
        create_rule(conn, "BAD", "DB", "value", "xor", 0, "low")
    with pytest.raises(GovError):
        create_rule(conn, "BAD", "DB", "value", "gt", "abc", "low")
    with pytest.raises(GovError):
        create_rule(conn, "BAD", "NO-CHECK", "value", "gt", 0, "low")
    with pytest.raises(GovError):
        create_rule(conn, "BAD", "DB", "value", "gt", 0, "fatal")


# ---------------------------------------------------------------------------
# Runbooks
# ---------------------------------------------------------------------------
STEPS = [
    {"step": "acknowledge", "action": "Open an incident.", "timebox_s": 900},
    {"step": "resolve", "action": "Fix and close.", "timebox_s": 3600},
]


def test_runbook_create_supersede_lookup(conn):
    rb = create_runbook(conn, "RB-1", "critical", STEPS)
    assert rb["version"] == 1 and rb["status"] == "current"
    assert runbook_for_key(conn, "critical")["id"] == rb["id"]
    new = supersede_runbook(conn, "RB-1", "critical",
                            STEPS + [{"step": "verify", "action": "Re-run.",
                                      "timebox_s": 300}])
    assert new["version"] == 2
    assert get_runbook_by_name(conn, "RB-1")["id"] == new["id"]
    old = get_runbook_by_name(conn, "RB-1", version=1)
    assert old["status"] == "superseded"
    assert old["superseded_by"] == new["id"]
    with pytest.raises(GovError):
        runbook_for_key(conn, "no-such-key")
    with pytest.raises(GovError):
        create_runbook(conn, "RB-1", "critical", STEPS)
    with pytest.raises(GovError):
        create_runbook(conn, "RB-2", "critical", [])
    with pytest.raises(GovError):
        create_runbook(conn, "RB-2", "critical",
                       [{"step": "x", "action": "y", "timebox_s": 0}])


def test_walkthrough_respects_timeboxes_with_fake_clock(conn):
    rb = create_runbook(conn, "RB-W", "high", STEPS)
    times = iter([0.0, 100.0, 100.0, 200.0])
    result = walkthrough(conn, rb["id"], clock=lambda: next(times))
    assert result["all_within_timebox"] is True
    assert [s["elapsed_s"] for s in result["steps"]] == [100.0, 100.0]
    slow = iter([0.0, 9999.0, 9999.0, 10000.0])
    result = walkthrough(conn, rb["id"], clock=lambda: next(slow))
    assert result["all_within_timebox"] is False
    assert result["steps"][0]["within_timebox"] is False


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
def test_incident_full_lifecycle(conn):
    inc = create_incident(conn, "Queue backlog", "high")
    assert inc["status"] == "open"
    assert len(inc["timeline"]) == 1
    with pytest.raises(GovError):
        transition_incident(conn, inc["id"], "closed")  # open -> closed illegal
    inc = transition_incident(conn, inc["id"], "triaged")
    inc = transition_incident(conn, inc["id"], "mitigating")
    with pytest.raises(GovError):
        transition_incident(conn, inc["id"], "resolved")  # note required
    inc = transition_incident(conn, inc["id"], "resolved",
                              note="Drained the queue; checks pass.")
    assert inc["status"] == "resolved"
    assert inc["resolution_note"] == "Drained the queue; checks pass."
    inc = add_incident_note(conn, inc["id"], "Follow-up: tune the threshold.")
    assert len(inc["timeline"]) == 5  # created + 3 transitions + note
    inc = transition_incident(conn, inc["id"], "closed")
    assert inc["status"] == "closed"
    inc = transition_incident(conn, inc["id"], "open", note="Recurrence seen.")
    assert inc["status"] == "open"
    assert len(list_incidents(conn, status="open")) == 1
    with pytest.raises(GovError):
        create_incident(conn, "Bad", "fatal")
    with pytest.raises(GovError):
        create_incident(conn, "Bad", "low", source_alert_id=99999)
    with pytest.raises(GovError):
        add_incident_note(conn, inc["id"], "   ")


# ---------------------------------------------------------------------------
# Migration rollback
# ---------------------------------------------------------------------------
def test_migration_023_down_step_rolls_back_for_real(conn):
    assert "023_governance.sql" in applied_migrations(conn)
    tables = ("gov_checks", "gov_check_runs", "gov_policies", "gov_jobs",
              "gov_dead_letters", "gov_rules", "gov_alerts", "gov_runbooks",
              "gov_incidents", "gov_incident_events", "gov_events")
    for t in tables:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?",
            (t,)).fetchone()["c"] == 1
    assert rollback_migration(conn, "023_governance.sql") is True
    for t in tables:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?",
            (t,)).fetchone()["c"] == 0
    assert "023_governance.sql" not in applied_migrations(conn)
    # Re-apply so later tests in this process still see the tables.
    run_migrations(conn)
    assert "023_governance.sql" in applied_migrations(conn)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
def test_seed_demo_data_is_idempotent(conn):
    first = seed_demo_data(conn)
    assert first["checks"] == 5 and first["policies"] == 2
    assert first["rules"] == 4 and first["runbooks"] == 2
    assert first["runs"] == 5 and first["jobs"] == 1 and first["incidents"] == 1
    assert len(list_checks(conn)) == 5
    assert status_summary(conn)["overall"] == "pass"
    second = seed_demo_data(conn)
    assert all(v == 0 for v in second.values())
    assert len(list_checks(conn)) == 5
    events = conn.execute(
        "SELECT COUNT(*) AS c FROM gov_events").fetchone()["c"]
    assert events > 0
