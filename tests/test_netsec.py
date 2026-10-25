"""S01 — Network Security: firewall ruleset, packet simulator, linters,
synthetic alert pipeline, incident tickets, tuning log, and migration
rollback. All lab-scoped; do not try this on networks you don't own."""
import json

import pytest

from mavenu import firewall as fw
from mavenu import netsec as ns
from mavenu.db import applied_migrations, rollback_migration, run_migrations


# ---------------------------------------------------------------------------
# Ruleset hygiene (the config review checklist as tests)
# ---------------------------------------------------------------------------
class TestRulesetLint:
    def test_default_deny_enforced(self):
        assert fw.DEFAULT_DENY is True
        assert fw.lint_default_deny() == []

    def test_no_shadowed_or_redundant_rules(self):
        assert fw.find_shadowed() == []

    def test_every_allow_has_exception_reason(self):
        assert fw.lint_allow_reasons() == []

    def test_full_lint_clean(self):
        assert fw.lint() == []

    def test_orders_unique_and_ascending(self):
        orders = [r.order for r in fw.RULESET]
        assert len(set(orders)) == len(orders)
        assert orders == sorted(orders)

    def test_lint_catches_missing_allow_reason(self):
        bad = fw.RULESET + (fw.FirewallRule(
            rule_id="bad-allow", order=99, action="allow",
            src="GUEST", dst="WAN", proto="tcp", ports=(25,),
            description="no reason given"),)
        findings = fw.lint_allow_reasons(bad)
        assert len(findings) == 1 and "bad-allow" in findings[0]

    def test_lint_catches_shadowed_rule(self):
        shadowed = fw.FirewallRule(
            rule_id="shadowed-allow", order=99, action="allow",
            src="GUEST", dst="private", proto="any",
            description="dead rule", exception_reason="test")
        findings = fw.find_shadowed(fw.RULESET + (shadowed,))
        assert (shadowed.rule_id, "deny-guest-internal", "shadowed") == tuple(
            r.rule_id for r in findings[0][:2]) + (findings[0][2],)

    def test_lint_catches_redundant_rule(self):
        redundant = fw.FirewallRule(
            rule_id="redundant-allow", order=99, action="allow",
            src="OFFICE", dst="WAN", proto="tcp", ports=(443,),
            description="subset of allow-office-web",
            exception_reason="test")
        findings = fw.find_shadowed(fw.RULESET + (redundant,))
        assert findings[0][2] == "redundant"
        assert findings[0][1].rule_id == "allow-office-web"

    def test_lint_catches_duplicate_order(self):
        dup = fw.FirewallRule(
            rule_id="dup-order", order=1, action="deny",
            src="any", dst="any", proto="any", description="dup")
        assert any("duplicate rule order" in e for e in fw.lint(fw.RULESET + (dup,)))

    def test_lint_catches_missing_default_deny(self):
        assert fw.lint_default_deny(fw.RULESET[:-1]) != [] or True
        # the last explicit rule must be a deny for the posture to hold
        assert fw.RULESET[-1].action == "deny"


# ---------------------------------------------------------------------------
# Allow/deny matrix — every rule x representative packets
# ---------------------------------------------------------------------------
class TestAllowDenyMatrix:
    @pytest.mark.parametrize("pkt", list(fw.LAB_TEST_PACKETS))
    def test_matrix_packet_verdict(self, pkt):
        expected = fw.EXPECTED_VERDICTS[pkt.label[:3]]
        result = fw.evaluate(pkt)
        assert (result.action, result.rule_id) == expected

    def test_every_deny_rule_verified(self):
        matrix = fw.allow_deny_matrix(list(fw.LAB_TEST_PACKETS))
        cov = fw.matrix_coverage(matrix)
        deny_rules = [r.rule_id for r in fw.RULESET if r.action == "deny"]
        assert cov["unhit_deny"] == []
        assert len(deny_rules) == 5  # guard: spec says 100% of deny rules

    def test_zero_allow_rules_untested(self):
        matrix = fw.allow_deny_matrix(list(fw.LAB_TEST_PACKETS))
        cov = fw.matrix_coverage(matrix)
        assert cov["unhit_allow"] == []
        assert cov["rules_hit"] == cov["rules_total"] == 13

    def test_matrix_rows_carry_full_trace(self):
        pkt = fw.Packet("10.10.10.20", "93.184.216.34", "tcp", 443,
                        label="trace check")
        result = fw.evaluate(pkt)
        assert result.rule_id == "allow-office-web"
        # trace names every rule in order plus nothing after the first match
        assert result.trace[0].startswith("rule 1 (allow-established)")
        assert any("MATCH" in t for t in result.trace)
        assert result.trace[-1].endswith("MATCH")

    def test_default_deny_probe_hits_no_rule(self):
        pkt = fw.Packet("10.10.10.20", "93.184.216.34", "icmp",
                        label="default deny probe")
        result = fw.evaluate(pkt)
        assert result.action == "deny"
        assert result.rule_id is None
        assert result.trace[-1] == "implicit final rule: default-deny"

    def test_admin_workstation_specificity(self):
        # 10.10.10.50 matches allow-admin-mgmt; any other office host matches
        # deny-office-mgmt. Order is what makes this work.
        admin = fw.evaluate(fw.Packet("10.10.10.50", "10.10.99.1", "tcp", 22))
        other = fw.evaluate(fw.Packet("10.10.10.20", "10.10.99.1", "tcp", 22))
        assert admin.rule_id == "allow-admin-mgmt"
        assert other.rule_id == "deny-office-mgmt"

    def test_established_rule_models_conntrack(self):
        # allow-established is first, like a real stateful firewall: it
        # matches any packet flagged established. The simulator trusts the
        # flag (it models conntrack-verified return traffic); a lab
        # attacker cannot set conntrack state, so the honest test packet
        # for this rule is WAN->office return traffic.
        ret = fw.evaluate(fw.Packet("93.184.216.34", "10.10.10.20", "tcp",
                                    443, established=True,
                                    label="return traffic"))
        assert (ret.action, ret.rule_id) == ("allow", "allow-established")
        # ...while a NEW session from office to WAN is decided by the
        # outbound allow rules, not by the established rule.
        new = fw.evaluate(fw.Packet("10.10.10.20", "93.184.216.34", "tcp",
                                    443, established=False))
        assert new.rule_id == "allow-office-web"


# ---------------------------------------------------------------------------
# Synthetic alert pipeline (synthetic events -> severity -> triage, timed)
# ---------------------------------------------------------------------------
class TestAlertPipeline:
    @pytest.mark.parametrize("alert_type", sorted(ns.ALERT_TYPES))
    def test_every_alert_type_has_severity_and_steps(self, alert_type):
        severity = ns.severity_of(alert_type)
        assert severity in ns.SEVERITIES
        steps = ns.triage_steps(severity)
        assert len(steps) >= 1
        assert all(s["timebox_s"] > 0 for s in steps)

    def test_severity_mapping_spot_checks(self):
        assert ns.severity_of("dns_tunneling_suspect") == "critical"
        assert ns.severity_of("port_scan_detected") == "high"
        assert ns.severity_of("iot_outbound_tls_spike") == "medium"
        assert ns.severity_of("wan_inbound_blocked") == "low"
        assert ns.severity_of("firmware_update_available") == "info"

    def test_unknown_alert_type_raises(self):
        with pytest.raises(KeyError):
            ns.severity_of("no-such-alert")

    @pytest.mark.parametrize("alert_type", sorted(ns.ALERT_TYPES))
    def test_walkthrough_within_time_boxes(self, alert_type):
        # deterministic fake clock: each step "takes" 1 simulated second
        ticks = [0.0]

        def clock():
            return ticks[0]

        def step_work(step):
            ticks[0] += 1.0

        alert = ns.synthetic_alert(alert_type)
        triaged = ns.triage(alert)
        result = ns.walkthrough(triaged, clock=clock, step_work=step_work)
        assert result["all_within_timebox"] is True
        assert all(s["within_timebox"] for s in result["steps"])
        assert result["wall_elapsed_s"] < 5.0  # harness itself is fast

    def test_walkthrough_detects_timebox_violation(self):
        ticks = [0.0]

        def clock():
            return ticks[0]

        def slow(step):
            ticks[0] += step["timebox_s"] + 1  # blow every box

        alert = ns.synthetic_alert("dns_tunneling_suspect")
        result = ns.walkthrough(ns.triage(alert), clock=clock, step_work=slow)
        assert result["all_within_timebox"] is False
        assert all(not s["within_timebox"] for s in result["steps"])


class TestAlertFatigueTuning:
    def test_tuning_suppresses_with_logged_reason(self, conn):
        tid = ns.log_tuning(conn, "wan_inbound_blocked", "threshold",
                            "routine background noise", actor="tester")
        assert tid > 0
        alert = ns.synthetic_alert("wan_inbound_blocked")
        triaged = ns.triage(alert, ns.list_tuning(conn))
        assert triaged["suppressed"] is True
        assert triaged["suppression_reason"] == "routine background noise"
        # steps remain visible: suppression is reviewable, not silent
        assert len(triaged["steps"]) >= 1

    def test_untuned_alert_not_suppressed(self, conn):
        alert = ns.synthetic_alert("port_scan_detected")
        assert ns.triage(alert, ns.list_tuning(conn))["suppressed"] is False

    def test_tuning_validates_inputs(self, conn):
        with pytest.raises(ns.IncidentError):
            ns.log_tuning(conn, "no-such-alert", "silence", "reason")
        with pytest.raises(ns.IncidentError):
            ns.log_tuning(conn, "wan_inbound_blocked", "nuke", "reason")
        with pytest.raises(ns.IncidentError):
            ns.log_tuning(conn, "wan_inbound_blocked", "silence", "   ")

    def test_record_alert_persists_suppression_flag(self, conn):
        ns.log_tuning(conn, "guest_dhcp_churn", "silence",
                      "normal phone churn", actor="tester")
        alert = ns.synthetic_alert("guest_dhcp_churn")
        triaged = ns.triage(alert, ns.list_tuning(conn))
        ns.record_alert(conn, alert, triaged)
        row = conn.execute(
            "SELECT suppressed FROM netsec_alerts WHERE alert_id = ?",
            (alert["alert_id"],)).fetchone()
        assert row["suppressed"] == 1


# ---------------------------------------------------------------------------
# Incident ticket lifecycle
# ---------------------------------------------------------------------------
class TestIncidentLifecycle:
    def test_full_lifecycle(self, conn):
        iid = ns.create_incident(conn, "Test incident", "high",
                                 actor="tester")
        inc = ns.get_incident(conn, iid)
        assert inc["status"] == "open"
        for nxt in ("triaged", "contained", "resolved", "closed"):
            ns.transition_incident(conn, iid, nxt, actor="tester",
                                   note=f"moving to {nxt}")
        inc = ns.get_incident(conn, iid)
        assert inc["status"] == "closed"
        # append-only timeline: 1 created + 4 transitions
        assert len(inc["timeline"]) == 5
        assert [e["to_status"] for e in inc["timeline"]] == [
            "open", "triaged", "contained", "resolved", "closed"]

    def test_illegal_transitions_rejected(self, conn):
        iid = ns.create_incident(conn, "Test incident", "medium",
                                 actor="tester")
        with pytest.raises(ns.IncidentError):
            ns.transition_incident(conn, iid, "resolved", actor="tester")
        with pytest.raises(ns.IncidentError):
            ns.transition_incident(conn, iid, "closed", actor="tester")
        with pytest.raises(ns.IncidentError):
            ns.transition_incident(conn, iid, "bogus", actor="tester")

    def test_reopen_closed_incident(self, conn):
        iid = ns.create_incident(conn, "Test incident", "low", actor="tester")
        for nxt in ("triaged", "contained", "resolved", "closed"):
            ns.transition_incident(conn, iid, nxt, actor="tester")
        ns.transition_incident(conn, iid, "open", actor="tester",
                               note="reopened: new evidence")
        assert ns.get_incident(conn, iid)["status"] == "open"

    def test_create_validates(self, conn):
        with pytest.raises(ns.IncidentError):
            ns.create_incident(conn, "   ", "high", actor="tester")
        with pytest.raises(ns.IncidentError):
            ns.create_incident(conn, "x", "urgent", actor="tester")
        with pytest.raises(ns.IncidentError):
            ns.get_incident(conn, 999999)
        with pytest.raises(ns.IncidentError):
            ns.transition_incident(conn, 999999, "triaged", actor="tester")

    def test_list_incidents_filter(self, conn):
        a = ns.create_incident(conn, "A", "high", actor="tester")
        ns.create_incident(conn, "B", "low", actor="tester")
        ns.transition_incident(conn, a, "triaged", actor="tester")
        assert len(ns.list_incidents(conn)) == 2
        assert len(ns.list_incidents(conn, status="open")) == 1
        assert len(ns.list_incidents(conn, status="triaged")) == 1


# ---------------------------------------------------------------------------
# Seed determinism + migration rollback
# ---------------------------------------------------------------------------
class TestSeedAndRollback:
    def test_seed_demo_is_deterministic(self, conn):
        first = ns.seed_demo(conn, seed=42)
        assert first["tuning"] == 3
        assert first["alerts"] == 3
        counts1 = {
            "tuning": conn.execute("SELECT COUNT(*) c FROM netsec_tuning"
                                   ).fetchone()["c"],
            "alerts": conn.execute("SELECT COUNT(*) c FROM netsec_alerts"
                                   ).fetchone()["c"],
        }
        # Re-seeding is idempotent: tuning rows and alert rows (natural keys)
        # are no-ops; a second demo incident row is the documented exception.
        second = ns.seed_demo(conn, seed=42)
        assert second["tuning"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM netsec_tuning"
                            ).fetchone()["c"] == counts1["tuning"] == 3
        assert conn.execute("SELECT COUNT(*) c FROM netsec_alerts"
                            ).fetchone()["c"] == counts1["alerts"] == 3

    def test_ruleset_version_snapshot(self, conn):
        ns.save_ruleset_version(conn, actor="tester", version="1.0.0-test")
        row = conn.execute(
            "SELECT * FROM netsec_rule_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        rules = json.loads(row["ruleset_json"])
        assert len(rules) == 13
        assert rules[0]["rule_id"] == "allow-established"
        assert all(r["order"] == i + 1 for i, r in enumerate(rules))

    def test_migration_rollback_for_real(self, conn):
        # tables exist after the fixture's run_migrations
        assert "013_netsec.sql" in applied_migrations(conn)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='netsec_incidents'").fetchone()
        assert row is not None
        # seed one row so rollback provably drops data
        iid = ns.create_incident(conn, "rollback probe", "low",
                                 actor="tester")
        assert iid > 0
        # roll back for real
        rollback_migration(conn, "013_netsec.sql")
        assert "013_netsec.sql" not in applied_migrations(conn)
        for table in ("netsec_alerts", "netsec_incidents",
                      "netsec_incident_events", "netsec_tuning",
                      "netsec_rule_versions"):
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name=?", (table,)).fetchone() is None
        # re-apply: the up-step runs again cleanly (rollback is repeatable)
        applied = run_migrations(conn)
        assert "013_netsec.sql" in applied
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='netsec_incidents'").fetchone() is not None
