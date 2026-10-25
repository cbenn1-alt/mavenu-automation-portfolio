"""S02 — OS Architecture & Vulnerabilities: unit + integration tests.

Every verification function must FAIL on the vulnerable-state fixture and
PASS on the hardened fixture. The remediation simulator must turn the
former into the latter with before/after evidence recorded. All states are
synthetic fixtures — nothing here touches a real machine.
"""
import copy

import pytest

from mavenu import ossec
from mavenu.db import get_connection, run_migrations, rollback_migration


@pytest.fixture
def vuln():
    return ossec.vulnerable_state()


@pytest.fixture
def hard():
    return ossec.hardened_state()


# ---------------------------------------------------------------------------
# Fixture shape
# ---------------------------------------------------------------------------

class TestStateSchema:
    def test_required_top_keys(self, vuln):
        assert ossec.validate_state(vuln) == []

    def test_missing_key_flagged(self):
        bad = ossec.vulnerable_state()
        del bad["ssh"]
        assert any("ssh" in p for p in ossec.validate_state(bad))

    def test_non_dict_flagged(self):
        assert ossec.validate_state(["nope"]) != []


# ---------------------------------------------------------------------------
# Every baseline item: fail on vulnerable, pass on hardened
# ---------------------------------------------------------------------------

class TestBaselineVerification:
    def test_every_item_fails_on_vulnerable(self, vuln):
        results = ossec.verify_baseline(vuln)
        assert len(results) == len(ossec.BASELINES) == 15
        failing = [r["item_id"] for r in results if not r["passed"]]
        assert len(failing) == 15, f"expected all 15 to fail, passing: {[r['item_id'] for r in results if r['passed']]}"

    def test_every_item_passes_on_hardened(self, hard):
        results = ossec.verify_baseline(hard)
        failing = [r["item_id"] for r in results if not r["passed"]]
        assert failing == []

    @pytest.mark.parametrize("item_id", [b["id"] for b in ossec.BASELINES])
    def test_item_fails_vulnerable_passes_hardened(self, vuln, hard, item_id):
        before = {r["item_id"]: r for r in ossec.verify_baseline(vuln)}
        after = {r["item_id"]: r for r in ossec.verify_baseline(hard)}
        assert not before[item_id]["passed"], f"{item_id} should fail on vulnerable"
        assert after[item_id]["passed"], f"{item_id} should pass on hardened"
        assert before[item_id]["evidence"], "failure needs an evidence string"
        assert after[item_id]["evidence"], "pass needs an evidence string"

    def test_verify_does_not_mutate_state(self, vuln):
        snapshot = copy.deepcopy(vuln)
        ossec.verify_baseline(vuln)
        assert vuln == snapshot

    def test_evidence_is_non_empty_everywhere(self, vuln, hard):
        for state in (vuln, hard):
            for r in ossec.verify_baseline(state):
                assert isinstance(r["evidence"], str) and r["evidence"].strip()


# ---------------------------------------------------------------------------
# Coverage audit: every baseline item has a verification function + fix
# ---------------------------------------------------------------------------

class TestCoverageAudit:
    def test_full_coverage(self):
        assert ossec.coverage_audit() == []

    def test_baseline_ids_unique(self):
        ids = [b["id"] for b in ossec.BASELINES]
        assert len(ids) == len(set(ids))

    def test_categories_known(self):
        for b in ossec.BASELINES:
            assert b["category"] in ossec.BASELINE_CATEGORIES

    def test_get_baseline(self):
        assert ossec.get_baseline("acct-02")["title"] == "No weak passwords"
        with pytest.raises(KeyError):
            ossec.get_baseline("nope")


# ---------------------------------------------------------------------------
# Findings: detection + remediation + verification evidence
# ---------------------------------------------------------------------------

class TestFindings:
    def test_at_least_five_classes(self):
        assert len(ossec.FINDINGS) >= 5

    def test_all_findings_detect_on_vulnerable(self, vuln):
        for f in ossec.FINDINGS:
            d = ossec.detect_finding(vuln, f["id"])
            assert d["detected"] is True, f["id"]
            assert d["evidence"], f"{f['id']} needs detection evidence"
            assert d["detection_method"], f"{f['id']} needs detection method"

    def test_no_findings_detect_on_hardened(self, hard):
        for f in ossec.FINDINGS:
            d = ossec.detect_finding(hard, f["id"])
            assert d["detected"] is False, f["id"]

    def test_100_percent_carry_detection_remediation_verification(self):
        """Structural: every finding record must carry all three."""
        for f in ossec.FINDINGS:
            for field in ("description", "detection_method", "remediation",
                          "verification_method", "baseline_item_ids"):
                assert f.get(field), f"{f['id']}: missing {field}"
            assert f["baseline_item_ids"], f"{f['id']}: no mapped baseline items"
            for item_id in f["baseline_item_ids"]:
                assert item_id in ossec.BASELINE_INDEX, \
                    f"{f['id']}: unknown baseline item {item_id}"

    def test_unknown_finding_raises(self, vuln):
        with pytest.raises(KeyError):
            ossec.detect_finding(vuln, "nope")


# ---------------------------------------------------------------------------
# Remediation simulator: apply fix -> re-verify -> pass, before/after kept
# ---------------------------------------------------------------------------

class TestRemediationSimulator:
    @pytest.mark.parametrize("finding_id", [f["id"] for f in ossec.FINDINGS])
    def test_remediate_finding_verifies(self, vuln, finding_id):
        result = ossec.remediate_finding(vuln, finding_id)
        assert result["verified"] is True, \
            f"{finding_id}: {[r for r in result['verification'] if not r['passed']]}"
        assert result["remediation_evidence"], "remediation needs evidence"
        assert all(r["passed"] for r in result["verification"])
        # input state untouched
        assert ossec.detect_finding(vuln, finding_id)["detected"] is True

    def test_before_after_report_full(self, vuln):
        report = ossec.before_after_report(vuln)
        assert report["summary_before"]["passed"] == 0
        assert report["summary_after"]["passed"] == 15
        assert report["summary_after"]["pass_rate"] == 1.0
        assert len(report["findings"]) == len(ossec.FINDINGS)
        for fr in report["findings"]:
            assert fr["detected_before_fix"] is True
            assert fr["detection_evidence"]
            assert fr["remediation_evidence"]
        fixed = [i for i in report["items"] if i["fixed"]]
        assert len(fixed) == 15
        for item in report["items"]:
            assert item["evidence_before"] and item["evidence_after"]

    def test_partial_remediation(self, vuln):
        report = ossec.before_after_report(vuln, ["ssh-misconfiguration"])
        auth_items = [i for i in report["items"]
                      if i["category"] == "authentication"]
        assert all(i["passed_after"] for i in auth_items)
        acct_items = [i for i in report["items"]
                      if i["category"] == "account_policy"]
        assert not any(i["passed_after"] for i in acct_items)

    def test_unknown_finding_id_rejected(self, vuln):
        with pytest.raises(KeyError):
            ossec.before_after_report(vuln, ["nope"])


# ---------------------------------------------------------------------------
# Adversarial: tampered state must be caught by verification
# ---------------------------------------------------------------------------

class TestAdversarial:
    def test_reenabled_service_caught(self, hard):
        tampered = copy.deepcopy(hard)
        for s in tampered["services"]:
            if s["name"] == "legacy-remote":
                s["running"] = True
        results = {r["item_id"]: r for r in ossec.verify_baseline(tampered)}
        assert not results["svc-01"]["passed"]
        assert "legacy-remote" in results["svc-01"]["evidence"]

    def test_reopened_ssh_password_auth_caught(self, hard):
        tampered = copy.deepcopy(hard)
        tampered["ssh"]["password_auth"] = True
        results = {r["item_id"]: r for r in ossec.verify_baseline(tampered)}
        assert not results["auth-01"]["passed"]

    def test_restored_suid_caught(self, hard):
        tampered = copy.deepcopy(hard)
        for f in tampered["files"]:
            if f["path"] == "/opt/lab/suid-helper":
                f["suid"] = True
                f["justified"] = False
        results = {r["item_id"]: r for r in ossec.verify_baseline(tampered)}
        assert not results["perm-02"]["passed"]

    def test_stale_updates_caught(self, hard):
        tampered = copy.deepcopy(hard)
        tampered["patch"]["pending_security_updates"] = 12
        tampered["patch"]["last_patch_days_ago"] = 60
        results = {r["item_id"]: r for r in ossec.verify_baseline(tampered)}
        assert not results["pat-01"]["passed"]
        assert not results["pat-02"]["passed"]

    def test_detection_survives_state_copy(self, vuln):
        assert ossec.detect_finding(copy.deepcopy(vuln),
                                    "weak-credentials")["detected"]


# ---------------------------------------------------------------------------
# Baseline summary math
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_counts(self, vuln, hard):
        s = ossec.baseline_summary(ossec.verify_baseline(vuln))
        assert (s["total"], s["passed"], s["failed"]) == (15, 0, 15)
        assert s["pass_rate"] == 0.0
        s2 = ossec.baseline_summary(ossec.verify_baseline(hard))
        assert (s2["total"], s2["passed"], s2["failed"]) == (15, 15, 0)
        assert s2["pass_rate"] == 1.0


# ---------------------------------------------------------------------------
# SQLite persistence + migration rollback (for real)
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    conn = get_connection(str(tmp_path / "ossec.db"))
    run_migrations(conn)
    yield conn
    conn.close()


class TestPersistence:
    def test_record_and_transition_finding(self, db):
        row_id = ossec.record_finding(db, "weak-credentials",
                                      "detection evidence here")
        findings = ossec.list_findings(db)
        assert len(findings) == 1
        assert findings[0]["status"] == "open"
        ossec.transition_finding(db, row_id, "remediated",
                                 evidence="changed passwords")
        ossec.transition_finding(db, row_id, "verified",
                                 evidence="acct-02 passes")
        assert ossec.list_findings(db, "verified")[0]["id"] == row_id

    def test_illegal_transition_rejected(self, db):
        row_id = ossec.record_finding(db, "ssh-misconfiguration", "ev")
        with pytest.raises(ossec.OssecError):
            ossec.transition_finding(db, row_id, "verified")

    def test_unknown_finding_id_rejected(self, db):
        with pytest.raises(KeyError):
            ossec.record_finding(db, "nope", "ev")

    def test_save_and_get_baseline_run(self, db):
        results = ossec.verify_baseline(ossec.vulnerable_state())
        run_id = ossec.save_baseline_run(db, "lab-vm-vulnerable", results)
        run = ossec.get_baseline_run(db, run_id)
        assert run["state_label"] == "lab-vm-vulnerable"
        assert run["total_items"] == 15
        assert run["passed"] == 0
        assert len(run["results"]) == 15
        failing = [r for r in run["results"] if not r["passed"]]
        assert len(failing) == 15
        assert ossec.list_baseline_runs(db)[0]["id"] == run_id

    def test_unknown_run_rejected(self, db):
        with pytest.raises(ossec.OssecError):
            ossec.get_baseline_run(db, 999)

    def test_seed_demo(self, db):
        counts = ossec.seed_demo(db)
        assert counts == {"findings": 6, "baseline_runs": 2}
        assert len(ossec.list_findings(db)) == 6
        assert len(ossec.list_baseline_runs(db)) == 2
        # idempotent
        counts2 = ossec.seed_demo(db)
        assert counts2 == {"findings": 0, "baseline_runs": 0}

    def test_migration_rollback_for_real(self, tmp_path):
        conn = get_connection(str(tmp_path / "rollback.db"))
        try:
            applied = run_migrations(conn)
            assert "014_ossec.sql" in applied
            ossec.record_finding(conn, "weak-credentials", "ev")
            ossec.save_baseline_run(conn, "lab-vm-vulnerable",
                                    ossec.verify_baseline(
                                        ossec.vulnerable_state()))
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"ossec_findings", "ossec_baseline_runs",
                    "ossec_baseline_results"} <= tables
            # Roll back for real.
            rollback_migration(conn, "014_ossec.sql")
            tables_after = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert not ({"ossec_findings", "ossec_baseline_runs",
                         "ossec_baseline_results"} & tables_after)
            # The migration record is gone, so the up-step re-applies cleanly.
            reapplied = run_migrations(conn)
            assert "014_ossec.sql" in reapplied
            tables_re = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"ossec_findings", "ossec_baseline_runs",
                    "ossec_baseline_results"} <= tables_re
        finally:
            conn.close()
