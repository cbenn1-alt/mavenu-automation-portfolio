"""N02 — risk workbook engine tests (module + DB, no web layer)."""
import copy
import json
import os
import random

import pytest

from mavenu import risk
from mavenu.db import get_connection, run_migrations, rollback_migration


def risk_db_dir():
    return os.path.join(os.path.dirname(__file__), "..", "src", "mavenu", "migrations")


@pytest.fixture
def db_conn(tmp_path):
    conn = get_connection(str(tmp_path / "n02.db"))
    run_migrations(conn, risk_db_dir())
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Ethical / fictional-company hard line
# ---------------------------------------------------------------------------

class TestEthicalBanner:
    def test_banner_present(self):
        assert "FICTIONAL" in risk.ETHICAL_BANNER
        assert "SYNTHETIC" in risk.ETHICAL_BANNER
        assert "NEVER an audit opinion" in risk.ETHICAL_BANNER

    def test_company_is_obviously_fictional(self):
        assert risk.COMPANY["fictional"] is True
        assert "Synthetic Test Co." in risk.COMPANY["name"]

    def test_all_asset_names_are_synthetic(self):
        for a in risk.ASSETS:
            assert a["asset_id"].startswith("A-")
            assert a["asset_type"] in risk.ASSET_TYPES


# ---------------------------------------------------------------------------
# Scales
# ---------------------------------------------------------------------------

class TestScales:
    def test_likelihood_scale_has_five_documented_levels(self):
        levels = [s["level"] for s in risk.LIKELIHOOD_SCALE]
        assert levels == [1, 2, 3, 4, 5]
        for s in risk.LIKELIHOOD_SCALE:
            assert s["label"] and s["rationale"], s

    def test_impact_scale_has_five_documented_levels(self):
        levels = [s["level"] for s in risk.IMPACT_SCALE]
        assert levels == [1, 2, 3, 4, 5]
        for s in risk.IMPACT_SCALE:
            assert s["label"] and s["rationale"], s

    def test_impact_is_max_of_cia(self):
        r = risk.score_risk(3, 2, 5, 1)
        assert r["impact"] == 5
        assert r["score"] == 15

    def test_invalid_levels_rejected(self):
        for bad in (0, 6, -1, 2.5, "3", True):
            with pytest.raises(risk.RiskError):
                risk.score_risk(bad, 1, 1, 1)
            with pytest.raises(risk.RiskError):
                risk.score_risk(1, bad, 1, 1)


class TestBandThresholds:
    @pytest.mark.parametrize("score,band", [
        (1, "low"), (4, "low"),
        (5, "medium"), (9, "medium"),
        (10, "high"), (15, "high"),
        (16, "critical"), (25, "critical"),
    ])
    def test_band_boundaries(self, score, band):
        assert risk.band_for_score(score) == band

    def test_boundary_15_vs_16(self):
        # The documented high/critical boundary, exercised by real fixture rows.
        assert risk.score_risk(3, 2, 5, 5)["band"] == "high"      # 3x5 = 15
        assert risk.score_risk(4, 4, 1, 1)["band"] == "critical"  # 4x4 = 16

    def test_fixture_spans_boundary(self):
        reg = {r["risk_id"]: r for r in risk.build_register()}
        assert reg["R-02"]["score"] == 15 and reg["R-02"]["band"] == "high"
        assert reg["R-01"]["score"] == 16 and reg["R-01"]["band"] == "critical"
        assert reg["R-08"]["score"] == 16 and reg["R-08"]["band"] == "critical"

    def test_out_of_range_scores_rejected(self):
        for bad in (0, 26, -3):
            with pytest.raises(risk.RiskError):
                risk.band_for_score(bad)


# ---------------------------------------------------------------------------
# Control registry (references, never duplicates, S01/S02 content)
# ---------------------------------------------------------------------------

class TestControlRegistry:
    def test_registry_built_live_from_s01_s02(self):
        reg = risk.CONTROL_REGISTRY
        assert "S02:auth-01" in reg and reg["S02:auth-01"]["project"] == "S02"
        assert "S01:deny-wan-inbound" in reg and reg["S01:deny-wan-inbound"]["project"] == "S01"
        assert "S01:alert:port_scan_detected" in reg
        assert len(reg) == 15 + 13 + 9  # S02 baselines + S01 fw rules + S01 alerts

    def test_unknown_ref_rejected(self):
        with pytest.raises(risk.RiskError):
            risk.validate_control_ref("S01:no-such-rule")
        with pytest.raises(risk.RiskError):
            risk.validate_control_ref("S03:anything")

    def test_gap_marker_validates(self):
        info = risk.validate_control_ref("GAP")
        assert info["kind"] == "accepted-gap"

    def test_every_register_control_ref_resolves(self):
        for raw in risk.REGISTER_FIXTURE:
            for c in raw["controls"]:
                risk.validate_control_ref(c["ref"])
                if c["ref"] == "GAP":
                    assert c.get("reason"), f"{raw['risk_id']}: GAP needs a reason"


# ---------------------------------------------------------------------------
# Risk register: structural traceability asset + threat + control
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_builds_with_expected_counts(self):
        reg = risk.build_register()
        assert len(reg) == 17
        bands = risk.register_totals(reg)["band_counts"]
        assert bands == {"low": 1, "medium": 6, "high": 8, "critical": 2}

    def test_every_entry_traces_to_asset_threat_control(self):
        # Structural assertion: no orphan entries. Every risk names a known
        # asset AND a known threat (applicable to the asset's type) AND at
        # least one control ref.
        for raw in risk.REGISTER_FIXTURE:
            asset = risk.ASSET_INDEX.get(raw["asset_id"])
            assert asset is not None, f"{raw['risk_id']}: orphan asset"
            threat = risk.THREAT_INDEX.get(raw["threat_id"])
            assert threat is not None, f"{raw['risk_id']}: orphan threat"
            assert asset["asset_type"] in threat["applies_to"], \
                f"{raw['risk_id']}: threat/asset-type mismatch"
            assert len(raw["controls"]) >= 1, f"{raw['risk_id']}: no controls"

    def test_every_score_cites_scale_levels_with_rationale(self):
        for r in risk.build_register():
            assert r["likelihood_rationale"], r["risk_id"]
            assert r["impact_rationale"], r["risk_id"]
            # rationale cites the applied levels, e.g. "L4" and "Impact 4"
            assert f"L{r['likelihood']}" in r["likelihood_rationale"], r["risk_id"]
            assert f"Impact {r['impact']}" in r["impact_rationale"], r["risk_id"]
            assert r["score"] == r["likelihood"] * r["impact"]

    def test_control_mapping_completeness_high_critical(self):
        reg = risk.build_register()
        assert risk.register_audit(reg) == []

    def test_threat_catalog_has_at_least_eight_threats(self):
        assert len(risk.THREATS) >= 8
        for t in risk.THREATS:
            assert t["vuln_class"], t["threat_id"]
            assert t["applies_to"], t["threat_id"]

    def test_register_sorted_by_severity(self):
        reg = risk.build_register()
        keys = [(-risk.BAND_ORDER[r["band"]], -r["score"]) for r in reg]
        assert keys == sorted(keys)

    def test_duplicate_risk_id_rejected(self):
        dup = risk.REGISTER_FIXTURE + (dict(risk.REGISTER_FIXTURE[0]),)
        with pytest.raises(risk.RiskError):
            risk.build_register(dup)

    def test_gap_entry_without_reason_rejected(self):
        bad = copy.deepcopy(risk.REGISTER_FIXTURE)
        for raw in bad:
            if raw["risk_id"] == "R-08":
                raw["controls"] = [{"ref": "GAP"}]
        with pytest.raises(risk.RiskError):
            risk.build_register(tuple(bad))


# ---------------------------------------------------------------------------
# Remediation prioritization: documented, reproducible
# ---------------------------------------------------------------------------

class TestRemediation:
    def test_eight_remediations_with_synthetic_cost_effort(self):
        reg = risk.build_register()
        rems = risk.build_remediations(reg)
        assert len(rems) == 8
        for r in rems:
            assert "synthetic" in r["cost_basis"], r["rem_id"]
            assert "synthetic" in r["effort_basis"], r["rem_id"]
            assert r["risk_reduction"] > 0, r["rem_id"]
            assert r["effort_hours"] > 0, r["rem_id"]
            assert r["affected_risks"] == sorted({e["risk_id"] for e in r["effects"]})

    def test_reduction_counted_once_per_affected_risk(self):
        # RM-04 carries two effects on R-11; the reduction must be R-11's
        # single score delta (15 -> 6 = 9), not 18.
        reg = risk.build_register()
        rems = {r["rem_id"]: r for r in risk.build_remediations(reg)}
        assert rems["RM-04"]["risk_reduction"] == 9

    def test_prioritization_order_is_documented_ratio_desc(self):
        reg = risk.build_register()
        ordered = risk.prioritize(risk.build_remediations(reg))
        ratios = [r["ratio"] for r in ordered]
        assert ratios == sorted(ratios, reverse=True)
        assert [r["rem_id"] for r in ordered] == [
            "RM-05", "RM-02", "RM-03", "RM-06",
            "RM-08", "RM-01", "RM-07", "RM-04"]

    def test_prioritization_reproducible_under_shuffle(self):
        reg = risk.build_register()
        rems = risk.build_remediations(reg)
        expected = [r["rem_id"] for r in risk.prioritize(rems)]
        rng = random.Random(20261023)
        for _ in range(25):
            shuffled = rems[:]
            rng.shuffle(shuffled)
            assert [r["rem_id"] for r in risk.prioritize(shuffled)] == expected

    def test_tie_broken_deterministically_by_rem_id(self):
        # RM-02 and RM-03 both have ratio 9/8; lower rem_id wins.
        reg = risk.build_register()
        rems = {r["rem_id"]: r for r in risk.build_remediations(reg)}
        assert rems["RM-02"]["ratio"] == rems["RM-03"]["ratio"] == 9 / 8
        ordered = [r["rem_id"] for r in risk.prioritize(list(rems.values()))]
        assert ordered.index("RM-02") < ordered.index("RM-03")

    def test_remediation_cannot_raise_a_level(self):
        reg = risk.build_register()
        bad = ({"rem_id": "RM-99", "title": "bad", "description": "bad",
                "cost_usd_cents": 0, "cost_basis": "synthetic estimate",
                "effort_hours": 1, "effort_basis": "synthetic estimate",
                "effects": [{"risk_id": "R-01", "field": "likelihood",
                             "new_value": 5}]},)
        with pytest.raises(risk.RiskError):
            risk.apply_remediations(reg, bad)


# ---------------------------------------------------------------------------
# Residual risk
# ---------------------------------------------------------------------------

class TestResidual:
    def test_residual_never_exceeds_inherent(self):
        reg = risk.build_register()
        stmt = risk.residual_statement(reg)
        res = {r["risk_id"]: r for r in stmt["risks"]}
        for r in reg:
            assert res[r["risk_id"]]["score"] <= r["score"], r["risk_id"]

    def test_totals_reconcile(self):
        reg = risk.build_register()
        stmt = risk.residual_statement(reg)
        assert stmt["total_reduction"] == (
            stmt["inherent"]["total_score"] - stmt["residual"]["total_score"])
        assert sum(d["delta"] for d in stmt["deltas"]) == stmt["total_reduction"]
        assert sum(stmt["residual"]["band_counts"].values()) == len(reg)

    def test_no_high_or_critical_remain(self):
        reg = risk.build_register()
        stmt = risk.residual_statement(reg)
        assert stmt["residual"]["band_counts"]["critical"] == 0
        assert stmt["residual"]["band_counts"]["high"] == 0

    def test_unremediated_risks_keep_inherent_scores(self):
        reg = risk.build_register()
        stmt = risk.residual_statement(reg)
        deltas = {d["risk_id"]: d for d in stmt["deltas"]}
        assert deltas["R-13"]["delta"] == 0  # no remediation covers R-13
        assert deltas["R-17"]["delta"] == 0  # accepted physical risk

    def test_memo_is_bannered_synthetic(self):
        stmt = risk.residual_statement(risk.build_register())
        assert "SYNTHETIC" in stmt["memo"]
        assert "not an audit opinion" in stmt["memo"]


# ---------------------------------------------------------------------------
# DB persistence + migration rollback
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_seed_inserts_expected_counts(self, db_conn):
        summary = risk.seed_demo(db_conn)
        assert summary == {"assets": 14, "threats": 10, "risks": 17,
                           "remediations": 8, "snapshots": 2}

    def test_seed_is_idempotent(self, db_conn):
        risk.seed_demo(db_conn)
        first = risk.list_risks(db_conn)
        risk.seed_demo(db_conn)
        second = risk.list_risks(db_conn)
        assert first == second

    def test_stored_rows_recompute_identically(self, db_conn):
        risk.seed_demo(db_conn)
        stored = risk.list_risks(db_conn)
        built = {r["risk_id"]: r for r in risk.build_register()}
        for r in stored:
            b = built[r["risk_id"]]
            assert (r["score"], r["band"], r["likelihood"], r["impact"]) == \
                   (b["score"], b["band"], b["likelihood"], b["impact"]), r["risk_id"]

    def test_remediation_money_round_trips_exact(self, db_conn):
        risk.seed_demo(db_conn)
        plan = risk.list_remediations(db_conn)
        cents = {r["rem_id"]: r for r in plan}
        assert cents["RM-01"]["cost_usd"] == "1200.00"
        assert cents["RM-06"]["cost_usd"] == "0.00"
        assert all("synthetic" in r["cost_basis"] for r in plan)
        assert all("synthetic" in r["effort_basis"] for r in plan)

    def test_list_remediations_returns_prioritized_order(self, db_conn):
        risk.seed_demo(db_conn)
        plan = risk.list_remediations(db_conn)
        assert [r["rem_id"] for r in plan] == [
            "RM-05", "RM-02", "RM-03", "RM-06",
            "RM-08", "RM-01", "RM-07", "RM-04"]
        assert all("ratio_exact" in r for r in plan)

    def test_snapshots_capture_inherent_and_residual(self, db_conn):
        risk.seed_demo(db_conn)
        snaps = {s["label"]: s for s in risk.list_snapshots(db_conn)}
        assert set(snaps) == {"inherent", "residual"}
        assert snaps["inherent"]["payload"]["totals"]["total_score"] == 177
        assert snaps["residual"]["payload"]["totals"]["total_score"] == 79
        assert snaps["residual"]["payload"]["total_reduction"] == 98

    def test_seeded_flag(self, db_conn):
        assert risk.seeded(db_conn) is False
        risk.seed_demo(db_conn)
        assert risk.seeded(db_conn) is True

    def test_residual_report_from_db(self, db_conn):
        risk.seed_demo(db_conn)
        stmt = risk.get_residual_report(db_conn)
        assert stmt["inherent"]["total_score"] == 177
        assert stmt["residual"]["total_score"] == 79
        assert "SYNTHETIC" in stmt["memo"]


class TestRollback:
    def test_migration_019_rollback_and_reapply(self, tmp_path):
        db_path = str(tmp_path / "rb.db")
        conn = get_connection(db_path)
        applied = run_migrations(conn, risk_db_dir())
        assert "019_risk.sql" in applied
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "risk_register" in tables
        # use it, then roll back
        risk.seed_demo(conn)
        assert risk.seeded(conn) is True
        rollback_migration(conn, "019_risk.sql", risk_db_dir())
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "risk_register" not in tables
        assert "risk_assets" not in tables
        assert "risk_snapshots" not in tables
        # re-apply works (idempotent up-step after rollback)
        applied2 = run_migrations(conn, risk_db_dir())
        assert "019_risk.sql" in applied2
        risk.seed_demo(conn)
        assert risk.seeded(conn) is True
        conn.close()

    def test_rollback_leaves_other_tables_intact(self, tmp_path):
        conn = get_connection(str(tmp_path / "rb2.db"))
        run_migrations(conn, risk_db_dir())
        rollback_migration(conn, "019_risk.sql", risk_db_dir())
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "netforensics_captures" in tables  # N01 untouched
        assert "schema_migrations" in tables
        conn.close()
