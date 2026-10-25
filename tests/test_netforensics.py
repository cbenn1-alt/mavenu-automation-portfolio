"""N01 — netforensics module tests (no web layer)."""
import json
import os
import sqlite3

import pytest

from mavenu import netforensics as nf
from mavenu.db import get_connection, run_migrations, rollback_migration


@pytest.fixture
def db_conn(tmp_path):
    conn = get_connection(str(tmp_path / "n01.db"))
    run_migrations(conn, nf_db_dir())
    yield conn
    conn.close()


def nf_db_dir():
    return os.path.join(os.path.dirname(__file__), "..", "src", "mavenu", "migrations")


def _pipeline(scenario, seed=20261023):
    return nf.run_full_pipeline(scenario, seed=seed)


# ---------------------------------------------------------------------------
# Ethical / no-socket hard line
# ---------------------------------------------------------------------------

class TestNoCaptureCode:
    def test_module_contains_no_socket_or_pcap(self):
        # Token-aware scan: the docstring legitimately *discusses* the ban,
        # so only actual code tokens count (imports, names, attribute access).
        import io
        import tokenize
        src_path = nf.__file__
        with open(src_path, "r", encoding="utf-8") as fh:
            tokens = list(tokenize.generate_tokens(fh.readline))
        code_names = {t.string for t in tokens
                      if t.type == tokenize.NAME}
        for banned in ("socket", "pcap", "AF_PACKET", "SOCK_RAW"):
            assert banned not in code_names, f"banned code token: {banned}"
        imports = [t.string for t in tokens
                   if t.type == tokenize.NAME and t.string in ("import", "from")]
        assert imports, "expected import statements"
        # No dynamic capture tricks either.
        src_text = tokenize.untokenize(tokens)
        assert "create_connection" not in src_text

    def test_ethical_banner_present(self):
        assert "LAWFUL LAB ONLY" in nf.ETHICAL_BANNER
        assert "SYNTHETIC" in nf.ETHICAL_BANNER

    def test_unknown_scenario_rejected(self):
        with pytest.raises(nf.NetForensicsError):
            nf.generate_capture("internet_backbone")

    def test_all_addresses_are_documentation_ranges(self):
        packets, _ = nf.generate_capture("port_scan")
        for p in packets:
            assert (p["src"].startswith("192.0.2.") or p["src"].startswith("203.0.113.")), p
            assert (p["dst"].startswith("192.0.2.") or p["dst"].startswith("203.0.113.")), p


# ---------------------------------------------------------------------------
# Generator determinism + ground truth
# ---------------------------------------------------------------------------

class TestGenerator:
    def test_determinism_same_seed_identical_capture(self):
        p1, g1 = nf.generate_capture("port_scan", seed=7)
        p2, g2 = nf.generate_capture("port_scan", seed=7)
        assert p1 == p2
        assert g1 == g2

    def test_different_seed_changes_jitter(self):
        p1, _ = nf.generate_capture("c2_beaconing", seed=7)
        p2, _ = nf.generate_capture("c2_beaconing", seed=8)
        assert p1 != p2
        # but both still detect one beaconing anomaly
        assert [a["type"] for a in nf.detect_anomalies(p2, nf.reconstruct_sessions(p2))] == ["beaconing"]

    def test_packet_schema(self):
        packets, _ = nf.generate_capture("baseline_clean")
        required = {"index", "ts", "src", "dst", "src_port", "dst_port",
                    "proto", "flags", "length", "payload_label", "payload_hash"}
        for p in packets:
            assert required <= set(p.keys())
        assert [p["index"] for p in packets] == list(range(len(packets)))
        assert all(p["ts"] for p in packets)

    def test_payload_hashes_cover_labels(self):
        packets, _ = nf.generate_capture("baseline_clean")
        import hashlib
        for p in packets:
            assert p["payload_hash"] == hashlib.sha256(
                p["payload_label"].encode()).hexdigest()

    def test_scenarios_registered(self):
        assert set(nf.SCENARIOS) == {"baseline_clean", "port_scan",
                                     "c2_beaconing", "data_exfiltration"}


# ---------------------------------------------------------------------------
# Session reconstruction
# ---------------------------------------------------------------------------

class TestSessions:
    def test_exfil_session_exact(self):
        r = _pipeline("data_exfiltration")
        ex = [s for s in r["sessions"] if s["dst_port"] == 31337]
        assert len(ex) == 1
        s = ex[0]
        # 3 handshake + 400 data + 2 teardown = 405 packets
        assert s["packet_count"] == 405
        assert s["bytes_out"] == 400 * 1400
        assert s["handshake_complete"] is True
        assert s["teardown_seen"] is True
        assert s["start_index"] == r["ground_truth"]["exfil_session_range"][0]
        assert s["end_index"] == r["ground_truth"]["exfil_session_range"][1]

    def test_port_scan_probes_are_one_sided(self):
        r = _pipeline("port_scan")
        probes = [s for s in r["sessions"]
                  if s["src"] == nf.EXT_ATK and s["packet_count"] == 2]
        assert len(probes) == 24
        assert all(p["handshake_complete"] is False for p in probes)
        assert all(p["teardown_seen"] is True for p in probes)  # RST from defense

    def test_bidirectional_merge(self):
        r = _pipeline("baseline_clean")
        # background LAB-HTTP sessions are bidirectional (both directions
        # merged into one session)
        http = [s for s in r["sessions"] if s["dst_port"] == 80]
        assert len(http) == 2
        assert all(h["handshake_complete"] is True for h in http)
        assert all(h["bytes_out"] > 0 and h["bytes_in"] > 0 for h in http)

    def test_sessions_cover_every_packet(self):
        r = _pipeline("port_scan")
        covered = set()
        for s in r["sessions"]:
            covered.update(range(s["start_index"], s["end_index"] + 1))
        assert covered == set(range(len(r["packets"])))


# ---------------------------------------------------------------------------
# Protocol decoders
# ---------------------------------------------------------------------------

class TestDecoders:
    def test_lab_http(self):
        note = nf.decode_lab_http({"payload_label": "LAB-HTTP GET /synth/3"})
        assert note == {"protocol": "LAB-HTTP", "method": "GET", "path": "/synth/3"}
        assert nf.decode_lab_http({"payload_label": "nope"}) is None

    def test_lab_dns(self):
        note = nf.decode_lab_dns({"payload_label": "LAB-DNS Q update.synth.local"})
        assert note["protocol"] == "LAB-DNS"
        assert note["name"] == "update.synth.local"
        assert nf.decode_lab_dns({"payload_label": "LAB-HTTP GET /synth/1"}) is None

    def test_lab_beacon(self):
        note = nf.decode_lab_beacon({"payload_label": "LAB-BEACON id=7 status=ok"})
        assert note == {"protocol": "LAB-BEACON", "beacon_id": 7, "status": "ok"}
        assert nf.decode_lab_beacon({"payload_label": "LAB-BEACON id=x"}) is None

    def test_decode_note_first_match_wins(self):
        pkt = {"payload_label": "LAB-DNS R update.synth.local"}
        assert nf.decode_note(pkt)["protocol"] == "LAB-DNS"
        assert nf.decode_note({"payload_label": "LAB-NTP poll"}) is None


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

class TestAnomalies:
    def test_baseline_clean_zero_anomalies(self):
        r = _pipeline("baseline_clean")
        assert r["anomalies"] == []
        assert r["scope"]["anomaly_types"] == []

    def test_port_scan_flagged(self):
        r = _pipeline("port_scan")
        kinds = [a["type"] for a in r["anomalies"]]
        assert kinds == ["port_scan"]
        a = r["anomalies"][0]
        gt = r["ground_truth"]
        assert a["detail"]["distinct_ports"] == gt["scanned_ports"]
        assert a["detail"]["probe_count"] == 24
        # cited range covers the probes AND the denial replies
        assert a["start_index"] == gt["probe_range"][0]
        assert a["end_index"] == gt["probe_range"][1]
        denied = [p for p in r["packets"][a["start_index"]:a["end_index"] + 1]
                  if "DENIED" in p["flags"]]
        assert len(denied) == 24

    def test_beaconing_flagged_with_correct_interval(self):
        r = _pipeline("c2_beaconing")
        kinds = [a["type"] for a in r["anomalies"]]
        assert kinds == ["beaconing"]
        a = r["anomalies"][0]
        assert abs(a["detail"]["mean_interval_s"] - 60.0) < 1.0
        assert a["detail"]["beacon_count"] == 10
        assert a["detail"]["interval_cv"] <= nf.BASELINE["beacon_interval_cv_max"]

    def test_exfil_flagged_on_byte_deviation(self):
        r = _pipeline("data_exfiltration")
        kinds = [a["type"] for a in r["anomalies"]]
        assert kinds == ["byte_exfiltration"]
        a = r["anomalies"][0]
        assert a["detail"]["bytes_out"] == 560000
        assert a["detail"]["bytes_out"] > nf.BASELINE["exfil_byte_threshold"]
        assert a["packet_range"] == r["ground_truth"]["exfil_session_range"]

    def test_every_anomaly_cites_packet_range(self):
        for sc in nf.SCENARIOS:
            r = _pipeline(sc)
            n = len(r["packets"])
            for a in r["anomalies"]:
                pr = a["packet_range"]
                assert isinstance(pr, list) and len(pr) == 2
                assert 0 <= pr[0] <= pr[1] < n


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_matches_ground_truth(self):
        r = _pipeline("c2_beaconing")
        tl = r["timeline"]
        assert tl[0]["kind"] == "capture_start"
        assert tl[-1]["kind"] == "capture_end"
        ts_list = [e["ts"] for e in tl]
        assert ts_list == sorted(ts_list)
        # one alert event per anomaly, referencing the same packet range
        alerts = [e for e in tl if e["kind"] == "alert"]
        assert len(alerts) == len(r["anomalies"])
        for ev, a in zip(alerts, r["anomalies"]):
            assert ev["packet_range"] == a["packet_range"]

    def test_timeline_covers_all_sessions(self):
        r = _pipeline("port_scan")
        starts = [e for e in r["timeline"] if e["kind"] == "session_start"]
        assert len(starts) == len(r["sessions"])

    def test_beacon_timeline_within_expected_window(self):
        r = _pipeline("c2_beaconing")
        gt = r["ground_truth"]
        alert = [e for e in r["timeline"] if e["kind"] == "alert"][0]
        assert alert["packet_range"] == gt["beacon_range"]


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------

class TestScoping:
    def test_scope_derived_from_anomalies(self):
        r = _pipeline("port_scan")
        scope = r["scope"]
        assert nf.EXT_ATK in scope["affected_hosts"]
        assert nf.LAB_SRV01 in scope["affected_hosts"]
        assert scope["anomaly_types"] == ["port_scan"]
        assert scope["start_index"] == r["anomalies"][0]["start_index"]
        assert scope["end_index"] == r["anomalies"][0]["end_index"]
        assert scope["start_ts"] < scope["end_ts"]

    def test_exfil_scope_names_hosts(self):
        r = _pipeline("data_exfiltration")
        scope = r["scope"]
        assert nf.LAB_WS01 in scope["affected_hosts"]
        assert nf.EXT_WEB in scope["affected_hosts"]
        assert len(scope["affected_sessions"]) == 1

    def test_clean_scope_empty(self):
        r = _pipeline("baseline_clean")
        scope = r["scope"]
        assert scope["affected_hosts"] == []
        assert scope["start_ts"] is None


# ---------------------------------------------------------------------------
# Report: facts vs inference, citation enforcement
# ---------------------------------------------------------------------------

class TestReport:
    def test_ground_truth_match_all_scenarios(self):
        for sc in nf.SCENARIOS:
            r = _pipeline(sc)
            assert r["report"]["ground_truth_match"] is True, sc

    def test_every_claim_cites_packet_range(self):
        r = _pipeline("port_scan")
        rep = r["report"]
        n = rep["packet_count"]
        for claim in rep["facts"] + rep["inferences"]:
            pr = claim["packet_range"]
            assert isinstance(pr, list) and len(pr) == 2
            assert 0 <= pr[0] <= pr[1] < n

    def test_inference_without_confidence_rejected(self):
        r = _pipeline("baseline_clean")
        with pytest.raises(nf.NetForensicsError):
            nf.build_report("ref", "baseline_clean", 1, r["packets"], [], [],
                            {}, [], [{"statement": "guess",
                                       "packet_range": [0, 1]}])

    def test_fact_without_packet_range_rejected(self):
        r = _pipeline("baseline_clean")
        with pytest.raises(nf.NetForensicsError):
            nf.build_report("ref", "baseline_clean", 1, r["packets"], [], [],
                            {}, [{"statement": "no citation"}], [])

    def test_bad_packet_range_rejected(self):
        r = _pipeline("baseline_clean")
        with pytest.raises(nf.NetForensicsError):
            nf.build_report("ref", "baseline_clean", 1, r["packets"], [], [],
                            {},
                            [{"statement": "x", "packet_range": [5, 2]}],
                            [])

    def test_report_carries_banner_and_synthetic_flag(self):
        r = _pipeline("port_scan")
        assert r["report"]["synthetic"] is True
        assert "LAWFUL LAB ONLY" in r["report"]["ethical_banner"]

    def test_baseline_printed_in_report(self):
        r = _pipeline("port_scan")
        assert r["report"]["baseline"]["port_scan_min_ports"] == 10


# ---------------------------------------------------------------------------
# Persistence + migration rollback
# ---------------------------------------------------------------------------

class TestPersistence:
    def _save_all(self, conn, scenario="port_scan", ref="cap-1"):
        r = nf.run_full_pipeline(scenario, seed=20261023, capture_ref=ref)
        cid = nf.save_capture(conn, ref, scenario, 20261023, r["packets"])
        nf.save_sessions(conn, cid, r["sessions"])
        nf.save_anomalies(conn, cid, r["anomalies"])
        rep_id = nf.save_report(conn, cid, ref + "-report", r["report"])
        return cid, rep_id, r

    def test_round_trip(self, db_conn):
        cid, _, r = self._save_all(db_conn)
        assert len(nf.list_packets(db_conn, cid)) == len(r["packets"])
        assert len(nf.list_sessions(db_conn, cid)) == len(r["sessions"])
        assert len(nf.list_anomalies(db_conn, cid)) == len(r["anomalies"])
        got = nf.get_report(db_conn, cid)
        assert got["report"]["capture_ref"] == "cap-1"
        assert got["report"]["ground_truth_match"] is True

    def test_duplicate_capture_ref_rejected(self, db_conn):
        self._save_all(db_conn, ref="cap-dup")
        r = _pipeline("port_scan")
        with pytest.raises(nf.NetForensicsError):
            nf.save_capture(db_conn, "cap-dup", "port_scan", 1, r["packets"])

    def test_tables_missing_without_migration(self, tmp_path):
        conn = get_connection(str(tmp_path / "bare.db"))
        r = _pipeline("port_scan")
        with pytest.raises(nf.NetForensicsError):
            nf.save_capture(conn, "x", "port_scan", 1, r["packets"])
        conn.close()

    def test_migration_rollback_for_real(self, tmp_path):
        conn = get_connection(str(tmp_path / "rb.db"))
        applied = run_migrations(conn, nf_db_dir())
        assert "018_netforensics.sql" in applied
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "netforensics_captures" in tables
        # use it, then roll back
        cid = nf.save_capture(conn, "cap-rb", "port_scan", 1,
                              _pipeline("port_scan")["packets"])
        assert cid == 1
        rollback_migration(conn, "018_netforensics.sql", nf_db_dir())
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "netforensics_captures" not in tables
        # re-apply works (idempotent up-step after rollback)
        applied2 = run_migrations(conn, nf_db_dir())
        assert "018_netforensics.sql" in applied2
        conn.close()
