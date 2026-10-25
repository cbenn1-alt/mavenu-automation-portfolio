"""N03 Safeguard — module tests.

All cases are synthetic written scenarios. No real people, accounts,
devices, or communications are involved. No network or messaging code
is exercised (the module has none).
"""
import inspect
import os
import re

import pytest

from mavenu import safeguard as sg
from mavenu.db import get_connection, run_migrations, rollback_migration
from mavenu.validation import ValidationError


def _intake(conn, ref, category, **kw):
    args = dict(
        case_ref=ref,
        category=category,
        reporter_role="synthetic test reporter",
        summary="SYNTHETIC TEST SCENARIO. Non-graphic test summary.",
    )
    args.update(kw)
    return sg.intake_case(conn, **args)


# ---------------------------------------------------------------------------
# Closed action vocabulary (structural)
# ---------------------------------------------------------------------------


class TestClosedVocabulary:
    def test_vocabulary_is_exactly_the_six_actions(self):
        assert sg.ACTIONS == (
            "preserve",
            "report",
            "refer",
            "safety_plan",
            "document",
            "escalate_to_authorities",
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "contact_suspect",
            "investigate_suspect",
            "gather_evidence_from_suspect",
            "track_suspect",
            "message_suspect",
            "confront_suspect",
            "dox_suspect",
            "preserve ",  # whitespace variant is not a member
            "INVESTIGATE",
        ],
    )
    def test_out_of_vocabulary_action_rejected(self, bad):
        with pytest.raises(sg.SafeguardError):
            sg.validate_action(bad)

    def test_no_suspect_contact_code_path_exists(self):
        src = inspect.getsource(sg)
        for name in (
            "contact_suspect",
            "investigate_suspect",
            "message_suspect",
            "track_suspect",
            "confront_suspect",
            "gather_evidence_from_suspect",
        ):
            assert name not in src, f"forbidden code path {name!r} present"

    def test_no_network_or_messaging_imports(self):
        src = inspect.getsource(sg)
        import_lines = [
            line
            for line in src.splitlines()
            if re.match(r"\s*(import|from)\s+", line)
        ]
        joined = "\n".join(import_lines)
        for mod in (
            "socket",
            "smtplib",
            "urllib",
            "http.client",
            "http.server",
            "requests",
            "ftplib",
            "telnetlib",
            "email",
            "wsgiref",
        ):
            assert mod not in joined, f"network/messaging import {mod!r} present"
        # The module only touches stdlib data/time/db/re modules + siblings.
        assert "import json" in joined
        assert "import sqlite3" in joined

    def test_db_check_constraint_rejects_out_of_vocabulary_action(self, conn):
        case = _intake(conn, "VOCAB-DB-1", "cyberharassment")
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO safeguard_checklist "
                "(case_id, step_id, action, title, status, updated_at) "
                "VALUES (?, 'x-1', 'contact_suspect', 'X', 'pending', ?)",
                (case["id"], "2026-10-23T00:00:00+00:00"),
            )


# ---------------------------------------------------------------------------
# Playbook authority discipline (structural)
# ---------------------------------------------------------------------------


class TestPlaybookAuthority:
    def test_all_eight_categories_have_playbooks(self):
        assert set(sg.PLAYBOOKS) == set(sg.CATEGORIES)
        assert len(sg.PLAYBOOKS) == 8

    def test_every_step_has_a_cited_authority(self):
        missing = [
            (cat, step["step_id"])
            for cat, pb in sg.PLAYBOOKS.items()
            for step in pb["steps"]
            if not str(step.get("authority", "")).strip()
        ]
        assert missing == []

    def test_every_step_action_is_in_vocabulary(self):
        bad = [
            (cat, step["step_id"], step["action"])
            for cat, pb in sg.PLAYBOOKS.items()
            for step in pb["steps"]
            if step["action"] not in sg.ACTIONS
        ]
        assert bad == []

    def test_step_ids_unique_within_playbook(self):
        for cat, pb in sg.PLAYBOOKS.items():
            ids = [s["step_id"] for s in pb["steps"]]
            assert len(ids) == len(set(ids)), cat

    def test_every_playbook_covers_preserve_report_refer(self):
        for cat, pb in sg.PLAYBOOKS.items():
            actions = {s["action"] for s in pb["steps"]}
            assert {"preserve", "report", "refer"} <= actions, cat

    def test_real_public_sources_cited_by_name(self):
        authorities = " | ".join(
            step["authority"] for pb in sg.PLAYBOOKS.values() for step in pb["steps"]
        )
        for name in (
            "NCMEC CyberTipline",
            "FBI Internet Crime Complaint Center (IC3)",
            "StopBullying.gov",
            "Cyber Civil Rights Initiative",
        ):
            assert name in authorities, name

    def test_csam_playbook_marked_no_investigation(self):
        pb = sg.get_playbook("child_sexual_exploitation")
        assert pb["no_investigation"] is True
        # The prohibition step is explicit and first-class data.
        titles = [s["title"] for s in pb["steps"]]
        assert any("Do NOT investigate" in t for t in titles)

    def test_no_playbook_step_targets_a_suspect(self):
        for cat, pb in sg.PLAYBOOKS.items():
            for step in pb["steps"]:
                sg._check_no_forbidden_operations(  # noqa: SLF001 (structural test)
                    f"{step['title']} {step['detail']}",
                    f"playbook {cat}/{step['step_id']}",
                )


# ---------------------------------------------------------------------------
# Content discipline (non-graphic)
# ---------------------------------------------------------------------------


class TestNonGraphic:
    @pytest.mark.parametrize(
        "bad", ["pornographic material", "sexually explicit photos", "genital images"]
    )
    def test_intake_rejects_graphic_summary(self, conn, bad):
        with pytest.raises(ValidationError):
            _intake(conn, "GRAPHIC-1", "cyberharassment",
                    summary=f"SYNTHETIC TEST. {bad}.")

    def test_finding_rejects_graphic_statement(self, conn):
        case = _intake(conn, "GRAPHIC-2", "cyberharassment")
        with pytest.raises(ValidationError):
            sg.add_finding(
                conn, case["id"], "SYNTHETIC TEST with pornographic detail.",
                claim_type="fact", status="lead",
            )

    def test_all_synthetic_cases_are_non_graphic(self):
        assert len(sg.SYNTHETIC_CASES) == 5
        for sc in sg.SYNTHETIC_CASES:
            sg.validate_non_graphic(sc["summary"], field=sc["case_ref"])
            assert "SYNTHETIC" in sc["summary"]


# ---------------------------------------------------------------------------
# Intake + safety triage
# ---------------------------------------------------------------------------


class TestIntakeTriage:
    def test_valid_intake_opens_checklist(self, conn):
        case = _intake(conn, "TRIAGE-1", "cyberharassment")
        assert case["stage"] == "triaged"
        assert case["safety_status"] == "standard"
        assert case["synthetic"] is True
        items = sg.get_checklist(conn, case["id"])
        assert len(items) == len(sg.PLAYBOOKS["cyberharassment"]["steps"])
        assert all(i["status"] == "pending" for i in items)

    def test_bad_category_rejected(self, conn):
        with pytest.raises(ValidationError):
            _intake(conn, "TRIAGE-2", "not_a_category")

    def test_bad_case_ref_rejected(self, conn):
        with pytest.raises(ValidationError):
            _intake(conn, "bad ref!", "cyberharassment")

    def test_duplicate_case_ref_rejected(self, conn):
        _intake(conn, "DUP-1", "cyberharassment")
        with pytest.raises(ValidationError):
            _intake(conn, "DUP-1", "cyberharassment")

    def test_missing_reporter_role_rejected(self, conn):
        with pytest.raises(ValidationError):
            _intake(conn, "TRIAGE-3", "cyberharassment", reporter_role="  ")

    def test_immediate_danger_routes_to_emergency_first(self, conn):
        case = _intake(conn, "DANGER-1", "swatting", immediate_danger=True)
        assert case["safety_status"] == "emergency"
        first = case["guidance"][0]
        assert "EMERGENCY FIRST" in first
        assert "911" in first

    def test_minor_involvement_triggers_safeguarding(self, conn):
        case = _intake(conn, "MINOR-1", "cyberbullying", involves_minor=True)
        assert case["safety_status"] == "minor-safeguarding"
        assert any("trusted adult" in g for g in case["guidance"])

    def test_csam_intake_refers_immediately(self, conn):
        case = _intake(conn, "CSE-1", "child_sexual_exploitation",
                       involves_minor=True)
        assert any("NCMEC" in g and "DO NOT INVESTIGATE" in g
                   for g in case["guidance"])
        referrals = sg.list_referrals(conn, case["id"])
        assert len(referrals) == 1
        assert referrals[0]["org_key"] == "ncmec_cybertipline"
        assert case["stage"] == "referred"
        # The referral is guidance text — it names no real contact channel
        # the system could use, because the system performs no outreach.
        assert "no outreach" in referrals[0]["guidance"]

    def test_sextortion_guidance_says_do_not_pay(self, conn):
        case = _intake(conn, "SEXT-1", "sextortion")
        assert any("Do NOT pay" in g for g in case["guidance"])

    def test_unknown_case_404_style(self, conn):
        with pytest.raises(sg.SafeguardError):
            sg.get_case(conn, 999999)


# ---------------------------------------------------------------------------
# Checklist tracking (preserve → report → refer)
# ---------------------------------------------------------------------------


class TestChecklist:
    def test_complete_and_skip(self, conn):
        case = _intake(conn, "CHECK-1", "internet_trolling")
        first = sg.get_checklist(conn, case["id"])[0]
        done = sg.complete_checklist_item(conn, case["id"], first["step_id"],
                                          note="screenshot saved")
        assert done["status"] == "done"
        assert done["note"] == "screenshot saved"
        second = sg.get_checklist(conn, case["id"])[1]
        skipped = sg.skip_checklist_item(conn, case["id"], second["step_id"],
                                         reason="no account to protect")
        assert skipped["status"] == "skipped"

    def test_skip_requires_reason(self, conn):
        case = _intake(conn, "CHECK-2", "internet_trolling")
        step = sg.get_checklist(conn, case["id"])[0]
        with pytest.raises(ValidationError):
            sg.skip_checklist_item(conn, case["id"], step["step_id"], reason="  ")

    def test_unknown_step_rejected(self, conn):
        case = _intake(conn, "CHECK-3", "internet_trolling")
        with pytest.raises(sg.SafeguardError):
            sg.complete_checklist_item(conn, case["id"], "nope-9")

    def test_close_requires_complete_checklist(self, conn):
        case = _intake(conn, "CHECK-4", "internet_trolling")
        with pytest.raises(sg.SafeguardError):
            sg.close_case(conn, case["id"])

    def test_checklist_status_counts(self, conn):
        case = _intake(conn, "CHECK-5", "internet_trolling")
        items = sg.get_checklist(conn, case["id"])
        sg.complete_checklist_item(conn, case["id"], items[0]["step_id"])
        st = sg.checklist_status(conn, case["id"])
        assert st["total"] == len(items)
        assert st["by_status"]["done"] == 1
        assert st["by_action"]["preserve"]["done"] == 1
        assert st["complete"] is False


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------


class TestReferrals:
    def test_unknown_org_rejected(self, conn):
        case = _intake(conn, "REF-1", "cyberharassment")
        with pytest.raises(ValidationError):
            sg.generate_referral(conn, case["id"], "not_an_org")

    def test_referral_moves_stage_and_lists(self, conn):
        case = _intake(conn, "REF-2", "cyberharassment")
        ref = sg.generate_referral(conn, case["id"], "fbi_ic3")
        assert ref["org_name"].startswith("FBI Internet Crime Complaint Center")
        assert "no outreach" in ref["guidance"]
        assert sg.get_case(conn, case["id"])["stage"] == "referred"
        listed = sg.list_referrals(conn, case["id"])
        assert len(listed) == 1
        assert listed[0]["what_to_provide"]

    def test_directory_has_ten_entries_and_template_note(self, conn):
        d = sg.referral_directory()
        assert len(d) == 10
        keys = {e["org_key"] for e in d}
        assert {"ncmec_cybertipline", "fbi_ic3", "local_law_enforcement",
                "crisis_text_line", "988_lifeline", "ccri"} <= keys
        for e in d:
            assert e["what_to_provide"]  # every entry says what to bring


# ---------------------------------------------------------------------------
# Findings — attribution discipline
# ---------------------------------------------------------------------------


class TestFindings:
    def test_unknown_is_an_acceptable_finding(self, conn):
        case = _intake(conn, "FIND-1", "cyberstalking")
        f = sg.add_finding(
            conn, case["id"],
            "The real-world identity behind the anonymous accounts.",
            claim_type="inference", status="unknown", confidence="low",
        )
        assert f["status"] == "unknown"
        assert f["confidence"] == "low"

    def test_verified_requires_evidence(self, conn):
        case = _intake(conn, "FIND-2", "cyberstalking")
        with pytest.raises(ValidationError):
            sg.add_finding(conn, case["id"], "A verified claim.",
                           claim_type="fact", status="verified")

    def test_verified_with_evidence_ok(self, conn):
        case = _intake(conn, "FIND-3", "cyberstalking")
        f = sg.add_finding(conn, case["id"], "A verified claim.",
                           claim_type="fact", status="verified",
                           evidence_ref="screenshot SYN-01")
        assert f["status"] == "verified"

    def test_inference_requires_confidence(self, conn):
        case = _intake(conn, "FIND-4", "cyberstalking")
        with pytest.raises(ValidationError):
            sg.add_finding(conn, case["id"], "An inference.",
                           claim_type="inference", status="lead")

    def test_fact_cannot_carry_confidence(self, conn):
        case = _intake(conn, "FIND-5", "cyberstalking")
        with pytest.raises(ValidationError):
            sg.add_finding(conn, case["id"], "A fact.",
                           claim_type="fact", status="lead", confidence="high")

    def test_bad_claim_type_and_status_rejected(self, conn):
        case = _intake(conn, "FIND-6", "cyberstalking")
        with pytest.raises(ValidationError):
            sg.add_finding(conn, case["id"], "x", claim_type="guess", status="lead")
        with pytest.raises(ValidationError):
            sg.add_finding(conn, case["id"], "x", claim_type="fact", status="maybe")

    def test_lead_vs_verified_separation(self, conn):
        case = _intake(conn, "FIND-7", "cyberstalking")
        sg.add_finding(conn, case["id"], "A lead.", claim_type="fact",
                       status="lead")
        sg.add_finding(conn, case["id"], "A verified fact.", claim_type="fact",
                       status="verified", evidence_ref="log entry 12")
        found = sg.list_findings(conn, case["id"])
        by_status = {f["status"] for f in found}
        assert by_status == {"lead", "verified"}


# ---------------------------------------------------------------------------
# Synthetic cases end-to-end (preserve → report → refer, no real contact)
# ---------------------------------------------------------------------------


def _run_case_end_to_end(conn, sc, referral_org):
    case = sg.intake_case(
        conn,
        case_ref=sc["case_ref"],
        category=sc["category"],
        reporter_role=sc["reporter_role"],
        summary=sc["summary"],
        immediate_danger=sc["immediate_danger"],
        involves_minor=sc["involves_minor"],
    )
    for item in sg.get_checklist(conn, case["id"]):
        if item["action"] == "refer":
            continue
        sg.complete_checklist_item(
            conn, case["id"], item["step_id"], note="synthetic exercise")
    sg.generate_referral(conn, case["id"], referral_org,
                         note="synthetic exercise referral")
    for item in sg.get_checklist(conn, case["id"]):
        if item["status"] == "pending":
            sg.complete_checklist_item(conn, case["id"], item["step_id"],
                                       note="referral recorded")
    closed = sg.close_case(conn, case["id"])
    assert closed["stage"] == "closed"
    st = sg.checklist_status(conn, case["id"])
    assert st["complete"] is True
    # preserve → report → refer all exercised
    for action in ("preserve", "report", "refer"):
        assert st["by_action"][action]["done"] >= 1, (sc["case_ref"], action)
    return case


class TestSyntheticCasesEndToEnd:
    def test_cyberbullying_full_path(self, conn):
        sc = next(s for s in sg.SYNTHETIC_CASES if s["case_ref"] == "SYN-CB-01")
        case = _run_case_end_to_end(conn, sc, "stopbullying")
        assert case["safety_status"] == "minor-safeguarding"

    def test_sextortion_full_path(self, conn):
        sc = next(s for s in sg.SYNTHETIC_CASES if s["case_ref"] == "SYN-SX-01")
        _run_case_end_to_end(conn, sc, "fbi_ic3")

    def test_csam_case_refers_immediately_no_investigation(self, conn):
        sc = next(s for s in sg.SYNTHETIC_CASES if s["case_ref"] == "SYN-CSE-01")
        case = sg.intake_case(
            conn, case_ref=sc["case_ref"], category=sc["category"],
            reporter_role=sc["reporter_role"], summary=sc["summary"],
            immediate_danger=sc["immediate_danger"],
            involves_minor=sc["involves_minor"],
        )
        # NCMEC referral exists at intake, before any checklist work.
        referrals = sg.list_referrals(conn, case["id"])
        assert [r["org_key"] for r in referrals] == ["ncmec_cybertipline"]
        # The playbook offers no investigation action to take.
        pb = sg.get_playbook("child_sexual_exploitation")
        assert pb["no_investigation"] is True
        assert all(s["action"] in sg.ACTIONS for s in pb["steps"])
        combined = " ".join(s["title"] + " " + s["detail"] for s in pb["steps"])
        assert "do not investigate" in combined.lower()
        # Every mention of investigation in this playbook is a prohibition.
        # Complete the non-refer steps, close the loop lawfully.
        for item in sg.get_checklist(conn, case["id"]):
            if item["action"] != "refer":
                sg.complete_checklist_item(conn, case["id"], item["step_id"],
                                           note="synthetic exercise")
        for item in sg.get_checklist(conn, case["id"]):
            if item["status"] == "pending":
                sg.complete_checklist_item(conn, case["id"], item["step_id"],
                                           note="NCMEC referral recorded")
        assert sg.close_case(conn, case["id"])["stage"] == "closed"

    def test_swatting_immediate_danger_first(self, conn):
        sc = next(s for s in sg.SYNTHETIC_CASES if s["case_ref"] == "SYN-SW-01")
        case = sg.intake_case(
            conn, case_ref=sc["case_ref"], category=sc["category"],
            reporter_role=sc["reporter_role"], summary=sc["summary"],
            immediate_danger=sc["immediate_danger"],
            involves_minor=sc["involves_minor"],
        )
        assert case["safety_status"] == "emergency"
        assert "EMERGENCY FIRST" in case["guidance"][0]
        _run_case_end_to_end(conn, {**sc, "case_ref": "SYN-SW-01B"}, "fbi_ic3")

    def test_cyberstalking_unknown_attribution(self, conn):
        sc = next(s for s in sg.SYNTHETIC_CASES if s["case_ref"] == "SYN-CS-01")
        case = _run_case_end_to_end(conn, sc, "local_law_enforcement")
        f = sg.add_finding(
            conn, case["id"],
            "The sender's real-world identity.",
            claim_type="inference", status="unknown", confidence="low",
        )
        assert f["status"] == "unknown"


# ---------------------------------------------------------------------------
# Preservation checklist + reporting guide
# ---------------------------------------------------------------------------


class TestChecklistAndGuide:
    def test_preservation_checklist_generic(self):
        items = sg.preservation_checklist()
        assert len(items) == len(sg.PRESERVATION_CHECKLIST)
        assert all(i["authority"].strip() for i in items)
        titles = [i["item"] for i in items]
        assert "Do not delete anything" in titles

    def test_preservation_addenda_per_category(self):
        for cat in ("sextortion", "nc_ii_abuse", "swatting",
                    "child_sexual_exploitation"):
            items = sg.preservation_checklist(cat)
            assert len(items) > len(sg.PRESERVATION_CHECKLIST), cat
            assert all(i["authority"].strip() for i in items)
        # CSAM addendum never asks for the material itself.
        cse = sg.preservation_checklist("child_sexual_exploitation")
        assert any("never the material" in (i["item"] + " " + i["detail"]).lower()
                   for i in cse)

    def test_reporting_guide_covers_platforms_and_ncmec(self):
        guide = sg.reporting_guide()
        platforms = {g["platform"] for g in guide}
        assert {"Instagram", "TikTok", "X (Twitter)", "Facebook",
                "NCMEC CyberTipline", "FBI IC3"} <= platforms
        assert all(g["authority"].strip() for g in guide)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


class TestDemo:
    def test_demo_runs_end_to_end(self, conn):
        demo = sg.run_demo(conn)
        assert demo["synthetic"] is True
        assert demo["mode"] == "Demo"
        assert demo["stage"] == "closed"
        assert demo["referral_org"]
        assert len(demo["steps_completed"]) >= 5
        assert demo["findings"] == 2
        detail = sg.get_case_detail(conn, demo["case_id"])
        assert detail["checklist_status"]["complete"] is True


# ---------------------------------------------------------------------------
# Migration rollback (for real)
# ---------------------------------------------------------------------------


class TestMigrationRollback:
    def test_rollback_for_real(self, tmp_path):
        db_path = str(tmp_path / "rollback.db")
        conn = get_connection(db_path)
        run_migrations(conn)
        case = _intake(conn, "ROLLBACK-1", "cyberharassment")
        n = conn.execute("SELECT COUNT(*) AS c FROM safeguard_cases").fetchone()["c"]
        assert n == 1
        rollback_migration(conn, "020_safeguard.sql")
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {t for t in tables if t.startswith("safeguard_")}
        mig = conn.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE name='020_safeguard.sql'"
        ).fetchone()["c"]
        assert mig == 0
        applied = run_migrations(conn)
        assert "020_safeguard.sql" in applied
        conn.close()
